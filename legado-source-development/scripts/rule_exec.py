#!/usr/bin/env python3
"""Legado 规则参考执行器（Python 实现）。

定位：规则层「参考执行」，不是目标同版本引擎。
- 能做：Default / CSS / JSONPath / XPath(受限) / 正则三态 / 相对 URL / 连接符
        规则列表上下文（chapterList / bookList 建节点，再跑字段规则）
- 不能做：Rhino JS 宿主、WebView、Cookie、Android 文件、完整网络生命周期
- 遇到未实现的能力必须显式失败（UnsupportedHost），不得静默跳过。

★ 含 @js:/<js> 的书源如何被检查（2026-10-16 定案）
  任一模块含 JS 规则时，eval_module 会在该模块上抛 UnsupportedHost，
  CLI 会打印 {"count":0,"errors":1,"raw":"UnsupportedHost: ..."} 且 rc=1，**其余模块不受影响**。
  这是**预期行为**，不是缺陷：参考执行器没有 Rhino，不能假装跑通 JS。
  因此：
    1. 校验含 JS 的书源，应当**逐模块运行** eval_module，把 UnsupportedHost 记为「未验证」，
       只对其余模块断言 errors==0；不要对整源断言 errors==0。
    2. JS 模块的真伪只能靠**真机**或在沙箱外以等价逻辑复现（如 live_*.py 用 Python 复写清洗步骤）。
    3. 绝不可因为「CLI 返回了 JSON」就认为该模块通过——count=0 时必须先分辨是
       「真没数据」还是「JS 未执行」，后者在输出里体现为 raw 字段含 UnsupportedHost。
"""
import json
import re
import sys
from urllib.parse import urljoin

MODE_RE = re.compile(r"^\s*(?:@css:|@json:|@xpath:|@js:|:)")


class RuleError(Exception):
    pass


class UnsupportedHost(RuleError):
    """目标引擎具备、参考执行器未实现的宿主能力。"""


class SelectorError(RuleError):
    pass


def split_connectors(rule):
    """按 && / || / %% 切分顶层连接符（感知括号、引号、标签）。"""
    parts, buf, depth = [], [], 0
    quote = None
    i = 0
    while i < len(rule):
        ch = rule[i]
        if quote:
            if ch == quote:
                quote = None
            buf.append(ch)
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "([":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif depth == 0 and rule[i:i + 2] in ("&&", "||", "%%"):
            parts.append(("".join(buf), rule[i:i + 2]))
            buf = []
            i += 2
            continue
        else:
            buf.append(ch)
        i += 1
    parts.append(("".join(buf), None))
    return parts


def strip_post(rule):
    """剥离 ## 正则后处理，返回 (主体, 正则, 替换, 是否仅替换首个)。

    对齐 AnalyzeRule.SourceRule.makeUpRule()：
        ruleStrS = rule.split("##")
        rule         = ruleStrS[0]
        replaceRegex = ruleStrS[1]
        replacement  = ruleStrS[2]
        replaceFirst = ruleStrS.size > 3
    """
    if "##" not in rule:
        return rule, "", "", False
    body, rest = rule.split("##", 1)
    chunks = rest.split("##")
    regex = chunks[0]
    repl = chunks[1] if len(chunks) > 1 else ""
    only_one = len(chunks) > 2      # 出现第 4 段（索引 >2）即为 replaceFirst
    return body, regex, repl, only_one


def js_guard(rule):
    if "@js:" in rule or "<js>" in rule or "@put:" in rule or "@get:" in rule:
        raise UnsupportedHost("JS / @put / @get 需目标同版本 Rhino 引擎验证")


def pick_mode(rule, body):
    """返回 (mode, payload)。未标模式时按 Default。"""
    text = rule.strip()
    if text.startswith("@css:"):
        return "css", text[5:].strip()
    if text.startswith("@json:") or text.startswith("$.") or text.startswith("$["):
        payload = text[6:].strip() if text.startswith("@json:") else text
        return "json", payload
    if text.startswith("@xpath:") or text.startswith("//") or text.startswith("/html"):
        payload = text[7:].strip() if text.startswith("@xpath:") else text
        return "xpath", payload
    if text.startswith("@js:"):
        raise UnsupportedHost("@js: 规则需目标同版本 Rhino 引擎验证")
    if text.startswith(":") and body:
        return "regex-allinone", text[1:]
    return "default", text


# ---------------------------------------------------------------- CSS

CSS_ATTR_RE = re.compile(r"^(?:(?P<sel>.*?)@)?(?P<attr>[A-Za-z][\w:-]*)$")


MATCHESOWN_RE = re.compile(r":matchesOwn\(([^)]*)\)")
MATCHESTEXT_RE = re.compile(r":matches\((?!Own)([^)]*)\)")
# ★ Jsoup 1.16.2 原生支持 `:contains(text)`（QueryParser 里有 "contains" 分支，
#   Evaluator.ContainsText，作用于元素**全部后代文本**）；cssselect2 不认它。
#   实测：不归一化时 `p:contains(作者)` 在参考执行器抛
#   SelectorError: ('Unknown pseudo-class', 'contains')，而该规则在真机合法。
#   这里转成等价的 :matches(转义后的字面量) 复用同一套链路语义。
CONTAINS_RE = re.compile(r":contains(Own)?\(")


def _matches_simple(el, selector):
    """伪类候选的元素级粗判。

    伪类（:matchesOwn）出现在组合器链的中间时，不能只看末段。此处取**整条链的
    最后一个简单选择器**做 tag/class/id 过滤，随后仍由真实 CSS 引擎复核上下文，
    故只作收窄、不作定论。
    """
    tail = re.split(r"[ >+~]", selector.strip())
    last = tail[-1].strip() if tail else ""
    if not last or last == "*":
        return True
    tag_m = re.match(r"^([A-Za-z][\w-]*)?((?:\.[\w-]+)*)(?:#([\w-]+))?", last)
    if not tag_m:
        return True
    tag, cls_chain, eid = tag_m.groups()
    el_tag = el.tag
    if not isinstance(el_tag, str):
        return False
    if tag and el_tag.lower() != tag.lower():
        return False
    el_classes = (el.get("class") or "").split()
    for c in re.findall(r"\.([\w-]+)", cls_chain or ""):
        if c not in el_classes:
            return False
    if eid and el.get("id") != eid:
        return False
    return True


def _normalize_contains(selector):
    """`:contains(x)` / `:containsOwn(x)` → `:matches(转义字面量)`。

    只处理**括号配平**的那一处（x 内若含括号则原样保留，交给引擎报错），
    避免把 `:not(:contains(a))` 这类嵌套拆坏。
    """
    s = selector or ""
    m = CONTAINS_RE.search(s)
    if not m:
        return s
    start = m.end()          # 左括号之后
    depth, i = 1, start
    while i < len(s):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        return s             # 括号不配平，交回原引擎处理
    literal = s[start:i]
    escaped = re.sub(r'([.^$*+?\[\]{}|\\])', r"\\\1", literal)
    head = "" if m.group(1) else ""      # containsOwn 暂按 contains 处理（后代文本）
    return s[:m.start()] + ":matches(" + escaped + ")" + s[i + 1:]


def _apply_jsoup_pseudos(html, selector):
    """把 Jsoup 伪类 :matchesOwn() / :matches() 落到可执行形式。

    关键语义：伪类作用在**它在链中所处位置的那个元素**上，而非最终命中元素。
    例如 `h3:matchesOwn(^章节列表)+.block-box ul>li` 中，正则校验的是 h3，
    命中结果却是 li。故实现分三步：
      1. 把去掉伪类后的选择器交给真实 CSS 引擎，得到最终候选集；
      2. 对每个候选，沿链走一遍，取出伪类所在位置的元素；
      3. 用正则校验该元素文本，不匹配则剔除。

    对 `<a>下一页 <i/></a>` 这类混合内容，ownText 取后代全部文本即可。
    """
    from lxml import html as lhtml
    selector = _normalize_contains(selector)
    own = MATCHESOWN_RE.search(selector)
    anyt = MATCHESTEXT_RE.search(selector)
    if own:
        pattern = own.group(1)
        pre = selector[:own.start()]
        post = selector[own.end():]
        base = (pre + post).strip() or "*"
    elif anyt:
        pattern = anyt.group(1)
        pre = selector[:anyt.start()]
        post = selector[anyt.end():]
        base = (pre + post).strip() or "*"
    else:
        return None
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise SelectorError(f"matchesOwn 正则非法: {exc}") from exc

    root = lhtml.fromstring(html)
    try:
        final = _select_elements_css(root, base)
    except UnsupportedHost:
        return [el for el in root.iter()
                if isinstance(el.tag, str) and rx.search(" ".join(el.itertext()))]

    if not post.strip():
        # 伪类位于链末：直接校验最终元素自身
        return [el for el in final if rx.search(" ".join(el.itertext()).strip())]

    # 伪类在链中段：解析其后的部分，回溯定位伪类所作用的祖先元素。
    steps = _parse_chain(post)
    picked = []
    for el in final:
        anchor = _walk_back(el, steps)
        if anchor is not None and rx.search(" ".join(anchor.itertext()).strip()):
            picked.append(el)
    return picked


CHAIN_STEP_RE = re.compile(r"\s*([>+~]?)\s*([^>+~\s]+)")


def _parse_chain(selector):
    """把 '> .block-box ul > li' 解析为 [(组合器, 简单选择器), ...]。"""
    return [(m.group(1) or " ", m.group(2)) for m in CHAIN_STEP_RE.finditer(selector)]


def _walk_back(el, steps):
    """从最终元素沿组合器链回溯，返回伪类所在的祖先元素。

    steps 形如 [('+', '.block-box'), (' ', 'ul.chapter-list'), ('>', 'li')]，
    其中组合器描述「本段元素与**下一段**元素的连接方式」，末段组合器描述它与
    伪类元素的关系。回溯顺序：先按末段组合器走到父/兄，再校验该元素是否满足
    更前一段的选择器，如此往复，最终停在伪类所作用的元素上。
    """
    if not steps:
        return el
    combs = [c for c, _ in steps]
    sels = [s for _, s in steps]
    # 末段：最终元素须满足末段选择器
    if not _matches_simple(el, sels[-1]):
        return None
    cur = el
    # i 走到 0 时，得到的正是伪类所作用的元素：先按 combs[0] 的关系定位，
    # 再由调用方用正则校验其文本。
    for i in range(len(sels) - 1, -1, -1):
        comb = combs[i]
        ref = sels[i - 1] if i > 0 else None
        if i == 0:
            # 伪类所在段：按它自己的组合器定位关系端
            if comb == ">":
                cur = cur.getparent()
            elif comb == "+":
                prev = cur.getprevious()
                while prev is not None and not isinstance(prev.tag, str):
                    prev = prev.getprevious()
                cur = prev
            elif comb == "~":
                prev = cur.getprevious()
                found = None
                while prev is not None:
                    if isinstance(prev.tag, str):
                        found = prev
                        break
                    prev = prev.getprevious()
                cur = found
            else:
                cur = cur.getparent()
            if cur is None or not isinstance(cur.tag, str):
                return None
            continue
        if comb == ">":
            cur = cur.getparent()
        elif comb == "+":
            prev = cur.getprevious()
            while prev is not None and not isinstance(prev.tag, str):
                prev = prev.getprevious()
            cur = prev
        elif comb == "~":
            prev = cur.getprevious()
            found = None
            while prev is not None:
                if isinstance(prev.tag, str) and _matches_simple(prev, ref):
                    found = prev
                    break
                prev = prev.getprevious()
            cur = found
        else:  # 后代
            anc = cur.getparent()
            found = None
            while anc is not None:
                if isinstance(anc.tag, str) and _matches_simple(anc, ref):
                    found = anc
                    break
                anc = anc.getparent()
            cur = found
        if cur is None or not isinstance(cur.tag, str):
            return None
        if not _matches_simple(cur, ref):
            return None
    return cur


def _select_elements_css(root, selector):
    """在已解析的 lxml root 上执行 CSS（不叠加伪类处理）。"""
    try:
        from cssselect2 import ElementWrapper, Matcher, compile_selector_list
    except ImportError as exc:
        raise UnsupportedHost("CSS 执行需要 cssselect2") from exc
    wrapper_root = ElementWrapper.from_html_root(root)
    matcher = Matcher()
    for sel_obj in compile_selector_list(selector):
        matcher.add_selector(sel_obj, None)
    out = []
    for w in wrapper_root.iter_subtree():
        if bool(matcher.match(w)) and w.etree_element is not None:
            out.append(w.etree_element)
    return out


def _pseudo_anchor(base):
    return ""


EQ_RE = re.compile(r":eq\(\s*(-?\d+)\s*\)")


def _strip_eq(selector):
    """剥离 :eq(n) 并返回 (纯选择器, [n,...])。

    ★ 2026-10-26：`:eq(n)` 是目标客户端的自有扩展（真机在用，如 55kxs、素书卷），
      但 cssselect2 不认，会抛 Unknown pseudo-class —— 把合法规则误判成源缺陷。
      语义与调试脚本一致：对**该层级**的候选集取第 n 个（支持负数，-1 为末项）。
      多个 :eq 依次作用（自左向右）。
    """
    idxs = [int(m.group(1)) for m in EQ_RE.finditer(selector or "")]
    if not idxs:
        return selector, []
    return EQ_RE.sub("", selector), idxs


def _apply_eq(elements, idxs):
    out = list(elements)
    for n in idxs:
        if not out:
            return []
        i = n if n >= 0 else len(out) + n
        out = [out[i]] if 0 <= i < len(out) else []
    return out


def _select_elements(html, selector):
    """CSS 选择 → 元素列表。优先 lxml+cssselect2，退化到内置受限选择器。"""
    selector, eq_idxs = _strip_eq(selector)
    if eq_idxs:
        base_sel = selector.strip() or "*"
        try:
            from lxml import html as lhtml
            from cssselect2 import ElementWrapper, Matcher, compile_selector_list
            root = lhtml.fromstring(html)
            wrapper_root = ElementWrapper.from_html_root(root)
            matcher = Matcher()
            for sel_obj in compile_selector_list(base_sel):
                matcher.add_selector(sel_obj, None)
            picked = []
            for w in wrapper_root.iter_subtree():
                if bool(matcher.match(w)) and w.etree_element is not None:
                    picked.append(w.etree_element)
            return _apply_eq(picked, eq_idxs)
        except ImportError:
            pass  # 交给下面的通用路径
        except Exception:
            pass
    pseudo = _apply_jsoup_pseudos(html, selector)
    if pseudo is not None:
        return pseudo
    try:
        from lxml import html as lhtml
        try:
            from cssselect2 import ElementWrapper, Matcher, compile_selector_list
            root = lhtml.fromstring(html)
            wrapper_root = ElementWrapper.from_html_root(root)
            matcher = Matcher()
            for sel_obj in compile_selector_list(selector or "*"):
                matcher.add_selector(sel_obj, None)
            picked = []
            for w in wrapper_root.iter_subtree():
                if bool(matcher.match(w)) and w.etree_element is not None:
                    picked.append(w.etree_element)
            return picked
        except ImportError as exc:
            raise UnsupportedHost("CSS 执行需要 cssselect2（apk add py3-cssselect2）") from exc
    except ImportError as exc:
        raise UnsupportedHost("CSS 执行需要 lxml（apk add py3-lxml）") from exc


def _simple_select(text, selector):
    """无 lxml 时的退化：只用正则取标签块，供纯文本环境兜底。"""
    tag_m = re.match(r"^([A-Za-z][\w-]*)?(?:\.([\w-]+))?", selector.strip())
    if not tag_m:
        raise UnsupportedHost("退化选择器无法解析: " + selector)
    tag = tag_m.group(1) or r"[A-Za-z]+"
    cls = tag_m.group(2)
    pat = re.compile(rf"<{tag}\b[^>]*>[\s\S]*?</{tag}>", re.I)
    blocks = [m.group(0) for m in pat.finditer(text)]
    if cls:
        blocks = [b for b in blocks if re.search(rf'class\s*=\s*"[^"]*\b{re.escape(cls)}\b', b)]
    return blocks


def _val_from_element(el, attr, lhtml=None):
    if attr == "text":
        return " ".join(el.itertext()).strip() if hasattr(el, "itertext") else ""
    if attr == "ownText":
        return (el.text or "").strip() if hasattr(el, "text") else ""
    if attr in ("html", "all", "outerHtml"):
        return lhtml.tostring(el, encoding="unicode") if lhtml else str(el)
    return el.get(attr, "") if hasattr(el, "get") else ""


def css_values(html, payload, multi_join="\n", list_root=False):
    """CSS 取值。多命中结果按 Legado 语义用 multi_join 连接成单值。

    list_root=True 表示这条规则用于建立列表节点上下文（bookList/chapterList），
    此时允许纯选择器；其余字段缺 @取值属规则错误，必须报出而非静默返回标记。
    """
    segments = split_connectors(payload)
    out = []
    for seg, conn in segments:
        seg = seg.strip()
        if not seg:
            continue
        # 列表根：纯选择器，无 @取值 → 返回元素本身（保留为节点上下文）
        if "@" not in seg:
            if not list_root:
                raise SelectorError(f"CSS 字段缺少 @取值: {seg}")
            el = _select_elements(html, seg)
            try:
                from lxml import html as lhtml
                vals = [lhtml.tostring(x, encoding="unicode") for x in el]
            except ImportError:
                vals = [str(x) for x in el]
            vals = [x for x in vals if x]
            if conn == "||" and vals:
                out.extend(vals)
                break
            out.extend(vals)
            continue
        m = CSS_ATTR_RE.match(seg)
        if not m:
            raise SelectorError(f"CSS 片段无法解析: {seg}")
        sel, attr = m.group("sel") or "", m.group("attr")
        el = _select_elements(html, sel or "*")
        try:
            from lxml import html as lhtml
        except ImportError:
            lhtml = None
        vals = [v for v in (_val_from_element(x, attr, lhtml) for x in el) if v]
        if conn == "||" and vals:
            out.extend(vals)
            break
        out.extend(vals)
    return out


# ---------------------------------------------------------------- Default

DEFAULT_PART_RE = re.compile(r"^(?P<tag>[A-Za-z][\w-]*)\.(?P<cls>[\w-]+)")

# 含 `A > B` 或多级后代空格的 Default 规则属于合法 CSS 组合写法；旧实现按
# `.` / `>` 硬切，会把 `h2.bookname > a@text` 的 `a` 当成取值部分而恒返回空。
CSS_COMBO_RE = re.compile(r"\s*>|\s+[A-Za-z*.#\[]")


def default_values(html, payload):
    """支持子集：tag.class / .class / tag#id / tag，位置与 @取值。"""
    from lxml import html as lhtml
    segments = split_connectors(payload)
    out = []
    for seg, conn in segments:
        seg = seg.strip()
        if not seg:
            continue
        if seg.startswith("{{") and seg.endswith("}}") and "@" not in seg:
            # ★ Legado 语义：Default 规则里不含 @ 时返回规则**原文**
            #   （AnalyzeRule.evalRule → 无 @ 即取字符串本身，宿主变量已在
            #   上游展开）。`tocUrl: {{baseUrl}}` 就是靠这条生效的。
            #   旧版一律抛「缺少 @取值」→ 把合法写法报成源的缺陷。
            out.append(seg)
            continue
        at = seg.rfind("@")
        if at < 0:
            raise SelectorError(f"Default 规则缺少 @取值: {seg}")
        head, attr = seg[:at], seg[at + 1:]
        # ★ 2026-10-27 修：原实现把 head 按 `.` / `>` 硬切再逐层 .// 取，凡是
        #   CIDR 组合写法（`h2.bookname > a`、`div.cat > a`、`div#content.x`、
        #   `a.b.c`、`div#allchapter dl > dd > a`）都会把后半段吞进取值部分，
        #   字段恒返回空——这是把合法规则误判成源缺陷的主因。凡 head 不是
        #   「tag.class / .class / tag#id / tag」这种单一简单选择器，一律交给
        #   CSS 引擎（含 :eq / :contains / 属性选择器）。
        if "@" not in head and not _SIMPLE_DEFAULT_RE.fullmatch(head.strip()):
            els = _select_elements(html, head.strip())
            try:
                from lxml import html as lhtml2
            except ImportError:
                lhtml2 = None
            vals0 = [v for v in (_val_from_element(x, attr, lhtml2) for x in els) if v]
        else:
            vals0 = _default_simple(html, head, attr)
        if conn == "||" and vals0:
            out.extend(vals0)
            break
        out.extend(vals0)
    return out


_SIMPLE_DEFAULT_RE = re.compile(r"^(?:[A-Za-z][\w-]*)?(?:\.([\w-]+))?(?:#[\w-]+)?$")


def _default_simple(html, head, attr):
    """兼容旧写法：tag.class / .class / tag#id / tag（可带 .n 位序）。"""
    from lxml import html as lhtml
    root = lhtml.fromstring(html)
    out = []
    index = None
    m = re.search(r"\.(?P<idx>-?\d+)$", head)
    if m:
        index = int(m.group("idx"))
        head = head[:m.start()]
    segs = [s for s in re.split(r"[.>]", head.lstrip(".")) if s]
    nodes = [root]
    for s in segs:
        nxt = []
        for n in nodes:
            if "." in s:
                tag, cls = s.split(".", 1)
                nxt.extend(n.xpath(f".//{tag or '*'}[contains(concat(' ',normalize-space(@class),' '),' {cls} ')]"))
            elif s.startswith("#"):
                nxt.extend(n.xpath(f".//*[@id='{s[1:]}']"))
            else:
                nxt.extend(n.xpath(f".//{s}"))
        nodes = nxt
    if index is not None and nodes:
        nodes = [nodes[index]]
    vals = []
    for n in nodes:
        if attr == "text":
            v = " ".join(n.itertext()).strip()
        elif attr == "textNodes":
            v = (n.text or "").strip()
        elif attr == "html":
            v = lhtml.tostring(n, encoding="unicode")
        elif attr == "href" or attr == "src":
            v = n.get(attr, "")
        else:
            v = n.get(attr, "") or " ".join(n.itertext()).strip()
        if v:
            vals.append(v)
    out.extend(vals)
    return out


# ---------------------------------------------------------------- JSON

def json_values(data, payload):
    try:
        from jsonpath_ng.ext import parse as jparse
    except ImportError as exc:
        raise UnsupportedHost("JSONPath 执行需要 jsonpath-ng（pip install jsonpath-ng 或 apk add py3-...）") from exc
    expr = payload.strip()
    if expr.startswith("$"):
        expr = expr[1:].lstrip(".")
    matches = jparse(expr).find(data)
    out = []
    for m in matches:
        v = m.value
        if isinstance(v, list):
            out.extend(str(x) for x in v)
        elif isinstance(v, dict):
            out.append(json.dumps(v, ensure_ascii=False))
        else:
            out.append(str(v))
    return out


# ---------------------------------------------------------------- XPath

def xpath_values(html, payload):
    from lxml import html as lhtml
    if "normalize-space(" in payload:
        raise UnsupportedHost("MD3 真机已确认 JsoupXpath 2.5.5 不支持 normalize-space()")
    root = lhtml.fromstring(html)
    return [x if isinstance(x, str) else " ".join(x.itertext()).strip()
            for x in root.xpath(payload)]


# ---------------------------------------------------------------- 正则

def regex_all_values(text, pattern):
    return [m.group(0) for m in re.finditer(pattern, text)]


def _java_repl_to_python(repl):
    """对齐 Legado 的替换串语义。

    Legado（AnalyzeRule.replaceRegex）用 Kotlin `Regex.replace(input, replacement)`，
    替换串遵循 Java 语义；Java 对未知转义（如 \\s）会抛异常，而 Legado 用
    runCatching 静默兜底。本执行器在 Python 侧做等价还原：Python 认得的转义原样
    保留，其余把反斜杠去掉、保留字符本身——这样 [\\s\\S] 这类字符类才不会被破坏。
    """
    KNOWN = set('ntrfvab0') | set('0123456789') | {'\\'}
    out, i, n = [], 0, len(repl)
    while i < n:
        c = repl[i]
        if c == '\\' and i + 1 < n:
            nxt = repl[i + 1]
            if nxt in KNOWN:
                out.append(c + nxt)
            else:
                out.append(nxt)
            i += 2
            continue
        # Java 的 $0 = 整个匹配；Python 的 \0 是 NUL 字节，必须用 \g<0>。
        # 注意：$0 必须在 $<数字> 之前判断，否则会被上面的分支吃掉。
        if c == '$' and repl[i + 1:i + 2] == '0':
            out.append('\\g<0>')
            i += 2
            continue
        # Java 用 $1 引用捕获组，Python 用 \1。$ 后跟数字时改写。
        if c == '$' and i + 1 < n and repl[i + 1].isdigit():
            j = i + 1
            while j < n and repl[j].isdigit():
                j += 1
            out.append('\\' + repl[i + 1:j])
            i = j
            continue
        # Java 的 $0 = 整个匹配
        if c == '$' and i + 1 < n and repl[i + 1] == '0':
            out.append('\\g<0>')
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def apply_post(values, regex, repl, only_one):
    if not regex:
        return values
    repl = _java_repl_to_python(repl)
    out = []
    for v in values:
        try:
            if only_one:
                m = re.search(regex, v)
                if m:
                    out.append(m.expand(repl))
            else:
                out.append(re.sub(regex, repl, v))
        except re.error as exc:
            raise RuleError(f"正则非法: {exc}") from exc
    return out


# ---------------------------------------------------------------- 入口

def eval_rule(rule, html, base="", nodes=None, list_root=False):
    """执行单条规则，返回字符串列表。nodes 为列表上下文节点（HTML 片段）。"""
    if not isinstance(rule, str) or not rule.strip():
        return []
    js_guard(rule)
    body, regex, repl, only_one = strip_post(rule)
    mode, payload = pick_mode(body, body)
    if mode == "regex-allinone":
        values = regex_all_values(html, payload)
    elif mode == "css":
        values = css_values(html, payload, list_root=list_root)
        if list_root:
            # ★ 2026-10-27 修：css_values 在 list_root 分支已返回「节点 HTML 片段」，
            #   但随后 apply_post 会再跑一遍 default_values（片段含 '@' 即抛
            #   SelectorError），dedupe 后 count 只剩 1 —— 任何 bookList/chapterList
            #   都表现为「只有 1 条」。列表上下文不得再做二次取值。
            return values
    elif list_root:
        # 未写模式头的纯选择器容器（如 `div.bookbox`）：Legado 的 Default 同样接受
        # CSS 选择器，这里按列表上下文取节点，不走 default_values（它要求 @取值）。
        values = css_values(html, "@css:" + payload, list_root=True)
        return values
    elif mode == "json":
        values = json_values(json.loads(html) if isinstance(html, str) else html, payload)
    elif mode == "xpath":
        values = xpath_values(html, payload)
    else:
        values = default_values(html, payload)
    values = apply_post(values, regex, repl, only_one)
    return dedupe(values)


def dedupe(values):
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def eval_field(rule, ctx_html, base=""):
    """字段取值。Legado 语义：多命中用 \\n 连接为单值，而非取首项。"""
    vals = eval_rule(rule, ctx_html, base)
    if not vals:
        return ""
    # ★ 2026-10-26 修：原写法 `isinstance(rule,str) and rule.endswith("@href") or "Url" in rule`
    #   因 and/or 优先级，只要有 "...Url" 就无条件 urljoin —— 把 JS 返回的绝对地址
    #   又拼了一次基址（实测 tocUrl="<js>baseUrl</js>" 变成 `…/1737/{{baseUrl}}`）。
    #   且旧实现在拼接前就用 \n 合并了多值，拼出来的是一串地址。
    #   正确做法：逐个值补全相对地址，再按 Legado 语义用 \n 连接。
    is_url_rule = isinstance(rule, str) and (
        rule.strip().endswith("@href") or rule.strip().endswith("@src")
        or rule.strip().endswith("@data-href"))
    if is_url_rule and base:
        fixed = []
        for v in vals:
            if v and not v.startswith(("http://", "https://", "//")):
                v = urljoin(base, v)
            fixed.append(v)
        vals = fixed
    v = vals[0] if len(vals) == 1 else "\n".join(vals)
    return v


def eval_module(source, module, response_text, base="", max_items=3):
    """按模块执行：列表规则先建节点上下文，再逐项跑字段规则。"""
    rules = source.get(module)
    if not isinstance(rules, dict):
        raise RuleError(f"源内没有模块 {module}")
    list_key = {"ruleToc": "chapterList", "ruleSearch": "bookList",
                "ruleExplore": "bookList"}.get(module)
    report = {"module": module, "count": 0, "errors": 0, "rows": [], "unsupported": []}
    if list_key and rules.get(list_key):
        items = eval_rule(rules[list_key], response_text, base, list_root=True)
    else:
        items = [response_text]
    report["count"] = len(items)
    for i, item in enumerate(items[:max_items]):
        row = {}
        for key, rule in rules.items():
            if key == list_key or not isinstance(rule, str) or not rule.strip():
                continue
            try:
                ctx = response_text if key in ("nextTocUrl", "nextContentUrl") else item
                row[key] = eval_field(rule, ctx, base)
            except UnsupportedHost as exc:
                report["unsupported"].append(f"{key}: {exc}")
                row[key] = "__UNSUPPORTED__"
            except Exception as exc:  # noqa: BLE001
                report["errors"] += 1
                row[key] = f"__ERROR__ {type(exc).__name__}: {exc}"
        report["rows"].append(row)
    if report["count"] == 0:
        report["errors"] += 1
    return report


def main():
    import argparse
    p = argparse.ArgumentParser(description="Legado 规则参考执行器")
    p.add_argument("source")
    p.add_argument("module")
    p.add_argument("response")
    p.add_argument("base", nargs="?", default="")
    p.add_argument("--max", type=int, default=3)
    a = p.parse_args()
    with open(a.source, encoding="utf-8-sig") as fh:
        src = json.load(fh)
    if isinstance(src, list):
        src = src[0]
    with open(a.response, encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    try:
        rep = eval_module(src, a.module, body, a.base, a.max)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"module": a.module, "count": 0, "errors": 1,
                          "raw": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 1 if rep["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
