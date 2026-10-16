#!/usr/bin/env python3
"""书源调试器 —— 对标 Legado「调试」面板（搜索 / 发现 / 详情 / 目录 / 正文）。

用法：
    python3 debug_source.py <书源.json> [--what search|explore|info|toc|content|all]
                            [--key 关键字] [--url 书籍页或章节页]
                            [--book 964] [--cat 玄幻] [--page 1]

设计要点（这几点是踩坑换来的，勿改）：
  1. **始终从书源文件现读规则**，绝不从中间缓存读。早期版本把规则另存成
     /tmp/cfg.json 再执行，书源改了、cfg 没改，跑出来是旧规则，白查半天（真事）。
  2. 含 @js: 的模块在参考执行器里会抛 UnsupportedHost，这里用 node 真跑
     （exec_js_rule_node，java.ajax 用 execSync('curl') 同步实现）；
     其余模块用 BeautifulSoup 复刻 @css / @attr / ##正则## 语义。
  3. 输出必须包含「真实请求 URL / 响应长度与特征 / 解析结果」。
     「看着有输出」不等于「输出是正文」——本站正文接口在错误路径上返回
     595 字节 JuicyAds 广告页，HTTP 200、长度正常，靠长度判必翻车。
     故正文一律按**内容特征**判定，不看长度。
  4. 目录顺序必须验：本站 ob 参数决定升降序；且第一页 25 条常属同一集，
     序数不连续，只判方向不判连续性。
"""
import argparse
import json
import os
import re
import subprocess

from bs4 import BeautifulSoup
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exec_js_rule_node as M  # noqa: E402

UA = 'curl/8.5.0'

# ★ 站点根一律从书源的 bookSourceUrl 推导，不写死。
#   写死会让脚本只能调试一个站，换个站就得出错误结论（真踩过）。
def site_of(src):
    u = str(src.get('bookSourceUrl') or '').strip()
    if not u:
        raise SystemExit('书源未填 bookSourceUrl，无法推导站点根')
    if not u.startswith('http'):
        u = 'https://' + u
    return u.rstrip('/')

# 这些是「取值后缀」，不能当 CSS 选择器的一部分
VALUE_TAILS = ('href', 'src', 'value', 'text', 'textNodes', 'ownText', 'html')

# 站点根由 bookSourceUrl 推出 —— ★ 不要写死站点，本脚本要能对任何书源使用
SITE = ''

# 书源 header 字段（JSON 字符串）解析后的 dict。
# ★ 真机 Legado 会带 header 发请求；脚本若不带，会把「站点因 UA 拒绝」误判成规则写错。
SRC_HEADER = {}


def set_site(u):
    """从 bookSourceUrl 推出站点根，供各页签拼默认地址。"""
    global SITE
    SITE = (u or '').rstrip('/')
    return SITE


def set_header(raw):
    """解析书源的 header 字段（JSON 字符串）→ 全局 SRC_HEADER。"""
    global SRC_HEADER
    SRC_HEADER = {}
    if not raw:
        return SRC_HEADER
    if isinstance(raw, dict):
        SRC_HEADER = {str(k): str(v) for k, v in raw.items()}
        return SRC_HEADER
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            SRC_HEADER = {str(k): str(v) for k, v in d.items()}
    except Exception:
        # 兼容 `k=v\nk2=v2` 形式
        for line in str(raw).splitlines():
            if '=' in line:
                k, _, v = line.partition('=')
                SRC_HEADER[k.strip()] = v.strip()
    return SRC_HEADER


def split_url_options(url):
    """Legado 允许 `url,{json}` 形式带请求参数（POST / headers / body）。

    ★ 不解析它就会把整段 JSON 当 URL 送出去 → HTTP 000，看着像站点挂了。
    """
    u = (url or '').strip()
    if ',' not in u:
        return u, {}
    head, _, tail = u.partition(',')
    tail = tail.strip()
    if not tail.startswith('{'):
        return u, {}
    try:
        return head.strip(), json.loads(tail)
    except Exception:
        return u, {}


def absolutize(u, base=None):
    """把相对地址补成绝对地址。

    ★ curl 不认识「/book/x/」这种相对路径 —— 会直接返回 exit 6，
      curl -w 打出的 %{http_code} 就是 000、len=0。
      这现象极像「站点挂了」，其实是我们没拼 URL（实测踩过）。
    """
    u = str(u or '').strip()
    if not u or u.startswith(('http://', 'https://')):
        return u
    b = (base or SITE or '').rstrip('/')
    if not b:
        return u
    return b + '/' + u.lstrip('/')


def get(url, ref=None):
    url, opts = split_url_options(url)
    url = absolutize(url, opts.get('_base') or SITE)
    cmd = ['curl', '-s', '-L', '--max-time', '30',
           '-w', '\n__CODE__%{http_code}']
    # ★ 书源 header 里若指定了 User-Agent，就用它；否则退回默认 UA。
    #   真机 Legado 会带 header，脚本不带会得出「规则错」的假结论。
    merged = dict(SRC_HEADER)
    hdr = opts.get('headers')
    if isinstance(hdr, dict):
        merged.update(hdr)
    if not any(k.lower() == 'user-agent' for k in merged):
        cmd += ['-A', UA]
    for k, v in merged.items():
        cmd += ['-H', '%s: %s' % (k, v)]
    if ref:
        cmd += ['-e', ref]
    method = str(opts.get('method', 'GET')).upper()
    body = opts.get('body', '')
    if method == 'POST':
        cmd += ['-X', 'POST']
        if body:
            cmd += ['--data-raw', str(body)]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True)
    body = r.stdout.decode('utf-8', 'replace')
    code = ''
    m = re.search(r'\n__CODE__(\d+)$', body)
    if m:
        code = m.group(1)
        body = body[:m.start()]
    return body, code


def css(html, sel, attr=None):
    """CSS 取值。★ 三类情况分别报清，绝不静默吞成「0 条」：

    - 选择器为空        → 打 `⚠ 解析异常`
    - `:eq()/:lt()/:gt()` → Legado 私有伪类，自行降级实现
    - 其他解析失败      → 打 `⚠ 解析异常`，返回空列表（不抛，页签继续）
    """
    from bs4 import BeautifulSoup
    if not (sel or '').strip():
        print('  ⚠ 解析异常：选择器为空（规则可能只写了取值后缀如 @href）')
        return []
    k = rule_kind(sel)
    if k in ('jsonpath', 'xpath'):
        print('  ⚠ 未支持：该规则是 %s 语法（%r），本脚本只实现 CSS 与 @js'
              % ('JSONPath' if k == 'jsonpath' else 'XPath', sel[:40]))
        return []
    pure, ops = split_eq_pseudo(sel) if has_eq_pseudo(sel) else (sel, [])
    try:
        soup = BeautifulSoup(html, 'html.parser')
        els = soup.select(pure) if pure.strip() else []
    except Exception as e:
        print('  ⚠ 解析异常：CSS 解析失败（%s）｜选择器 %r'
              % (e.__class__.__name__, sel))
        return []
    if ops:
        els = apply_eq_pseudo(els, ops)
    if attr == 'textNodes':
        # ★ 真机语义：取元素下的**所有文本节点**并保留换行。
        #   这是搜书类站点正文分段的**标准写法**（悠空网/书迷楼/小说巴士/无限小说网
        #   均用 `p@textNodes`）。它与 `@text` 的差别在**是否插入段落换行**：
        #   `@text` 把多个 `<p>` 拼成一坨（真机表现为「整段挤在一起、没有分段」），
        #   `@textNodes` 保留各段边界 → 正常分段。
        #   本脚本旧版把 `textNodes` 静默降级为 `text`（白名单外一律转 text），
        #   因而**无法复现「一坨 vs 分段」这一差异**，会放过这类规则缺陷。
        out = []
        for e in els:
            seg = ''.join(e.strings) if hasattr(e, 'strings') else e.get_text()
            for ln in re.split(r'\r?\n', seg):
                if ln.strip():
                    out.append(ln.strip())
        return out
    if attr == 'ownText':
        # 只取直接文本子节点，忽略后代元素文本
        out = []
        for e in els:
            seg = ''.join(t for t in e.find_all(string=True, recursive=False))
            if seg.strip():
                out.append(seg.strip())
        return out
    if attr:
        return [e.get(attr) for e in els]
    return [e.get_text(strip=True) for e in els]


# ---------------------------- 选择器安全化（多书源实测） ----------------------------
# ★ 教训：CSS 解析失败必须「报出来并继续」，不能把整个页签崩掉；
#   更要区分「确实没匹配到」与「选择器自己就是错的 / 是别的语法」——
#   这三类此前混成一个「结果 0 条」，害我误判过规则。

JS_WRAP = re.compile(r'^\s*<js>([\s\S]*)</js>\s*$')
_EQ_PSEUDO = re.compile(r':(eq|lt|gt)\(\s*(-?\d+)\s*\)')


def is_js_selector(sel):
    """选择器整体被 <js></js> 包住 → 这是 JS 语法，不是 CSS。"""
    return bool(JS_WRAP.match(sel or ''))


def unwrap_js(sel):
    m = JS_WRAP.match(sel or '')
    return m.group(1) if m else sel


def has_eq_pseudo(sel):
    """Legado 私有伪类 :eq(n) / :lt(n) / :gt(n)，soupsieve 不支持。"""
    return bool(_EQ_PSEUDO.search(sel or ''))


def split_eq_pseudo(sel):
    """拆出 (纯净选择器, [(op, n), ...])，供自己在 NodeList 上二次筛选。"""
    ops = []

    def _grab(m):
        ops.append((m.group(1), int(m.group(2))))
        return ''

    pure = _EQ_PSEUDO.sub(_grab, sel or '')
    return pure, ops


def apply_eq_pseudo(nodes, ops):
    """按 jQuery 语义在已选出的节点上应用 :eq/:lt/:gt（负数为倒数）。"""
    out = list(nodes)
    for op, n in ops:
        if op == 'eq':
            i = n if n >= 0 else len(out) + n
            out = [out[i]] if 0 <= i < len(out) else []
        elif op == 'lt':
            k = n if n >= 0 else len(out) + n
            out = out[:max(0, k)]
        elif op == 'gt':
            k = n if n >= 0 else len(out) + n
            out = out[max(0, k) + 1:]
    return out


def strip_suffixes(rule):
    """切掉 Legado 规则的取值后缀。

    ★ 后缀有两个，且都含 `@` / `#`，必须先切再交给 soup.select，
      否则 BeautifulSoup 抛 `Invalid character '@'`：
        - 取值类型：`@css:sel@href`、`@css:sel@text`
        - 正则后处理：`选择器##正则##替换`（本项目就有 `##^\\s*作者：\\s*##`）
    ★ 从**左往右**扫，但**跳过前 3 个字符**（`@cs` 是 `@css:` 的前缀）：
      第一个 `@` 属于 `@css:` 标记本身，从它开始扫会把选择器切空。
      （实测：`split_at=0` → expr=''，且不报错，只静静地匹配 0 条。）
      之后第一个「后随非字母」的 `@` 才是取值分隔符。
      这一点也踩过大坑：`@css:p.info@text##...##` 里用 rpartition 会取到
      正则串结尾的 `@text`，把选择器切成 `p.info@text##...##`，
      而它**恰好是个合法 CSS 选择器**（属性选择器）→ 不报错也不匹配。
    """
    s = rule or ''
    split_at = -1
    # ★ 起始位置不能一律写 3：
    #   `@css:` 前缀占 5 字符，跳过前 3 是为了避开 `@cs` 里的 @；
    #   但 .t@text / @href 这类**短规则**会被 range(3,...) 整段跳过，
    #   于是后缀切不下来 → 选择器带着 '@text' 直接喂给 soupsieve →
    #   SelectorSyntaxError（或静默取到错值）。这是实测踩到的坑。
    start = 0
    if s.lower().startswith('@css:'):
        start = 1
    elif s.lower().startswith(('@xpath:', '@json:')) or s.startswith('@'):
        start = 0
    for k in range(max(start, 1 if s.startswith('@') else 0), len(s)):
        if s[k] != '@':
            continue
        nxt = s[k + 1:k + 2]
        if nxt and not nxt.isalpha():
            continue
        split_at = k
        break
    if split_at >= 0:
        # ★ 取值与正则可能**同处一个 `@` 之后**：`...@text##正则##替换`。
        #   此时 `@` 后面是整段 `text##...##$1`，需要再劈一次
        #   ——只切第一个 `@` 的话，正则整段丢失，规则会吐出整串原文
        #   （author 直接变成 p.info 的全部文字）。实测踩过。
        expr = s[:split_at]
        tail = s[split_at + 1:]
        attr, _, rest = tail.partition('##')
        regex = rest if rest else ''
    else:
        expr, attr = s, 'text'
        regex = ''
        m = re.search(r'##(.*?)##(.*)$', expr, re.S)
        if m:
            regex = m.group(1) + '##' + m.group(2)
            expr = expr[:m.start()]
    if expr.startswith('@css:'):
        expr = expr[5:]
    if attr not in VALUE_TAILS and attr != 'text':
        attr = 'text'
    expr = expr.strip()
    if not expr:
        print('  ⚠ 解析异常：选择器为空，原串=%r' % (rule,))
    return expr, attr, regex


def apply_regex(value, regex):
    """处理 '正则##替换' 后缀（Legado 的取值后处理）。

    ★ 替换串里的 `$1` / `${1}` 是 JVM Matcher 的**捕获组引用**，Python 不认。
      换算成 `\\g<1>` 再交给 re.sub。（本项目 detail 页的 author/wordCount
      就靠它，写错会原样吐出 `$1`，看着像规则失效。）
    """
    if not regex:
        return value
    pat, _, rep = regex.partition('##')
    rep = re.sub(r'\$\{?(\w+)\}?', r'\\g<\1>', rep)
    try:
        return re.sub(pat, rep, value)
    except re.error:
        return value


def init_rule(rule, html, base):
    """@init 段先跑（Legado 有此机制，常用于把「最新章节」存进 map）。"""
    m = re.match(r'@init:\s*(@js:|<js>)(.*)', rule or '', re.S)
    if not m:
        return
    out, log = M.run('@js:' + m.group(2), base, {})
    print('    [@init] 执行完成，java.ajax %d 次' % len(log))
    if log:
        print('            ' + log[0][:80])


# ★ 纯取值后缀（只有「取什么」，没有选择器）：Legado 语义是
#   「在当前条目节点上取」，而非去整页找。如 bookUrl='@href'、coverUrl='@src'、
#   detail='@text'。判据见 is_bare_suffix + strip_suffixes 的返回值。
BARE_SUFFIX = re.compile(r'^@(?:[a-zA-Z_][\w-]*)$')


def is_bare_suffix(rule):
    """整条规则就是一个 `@attr`（无选择器）→ 在当前节点上取值。"""
    return bool(BARE_SUFFIX.match((rule or '').strip()))


# ★ Legado 的 `tag.<标签>.<序号>@取值` 简写（目录页高频）：
#   `tag.a.0@href` = 条目内第 0 个 <a> 的 href；`tag.span.1@text` = 第 1 个 span 的文本。
#   不支持时选择器会变成字面 'tag.a.0' → soupsieve 抛 SelectorSyntaxError 或取空，
#   表现为「目录 0 条」，很容易被误判成站点改版（三个源都用了这个写法）。
TAG_SHORT = re.compile(r'^tag\.([A-Za-z][\w-]*)\.(-?\d+)\s*(?:@(\w+))?$')


def parse_tag_short(rule):
    """解析 tag.a.0@href → ('a', 0, 'href')；不是该写法返回 None。"""
    m = TAG_SHORT.match((rule or '').strip())
    if not m:
        return None
    return m.group(1), int(m.group(2)), (m.group(3) or 'text')


def node_value(node, rule):
    """在指定节点上跑规则：只支持「纯后缀」与「@css:相对选择器@attr」。

    条目内相对取值是搜书类书源的高频写法，缺了它整页 bookUrl/coverUrl 全空。
    """
    if node is None:
        return ''
    r = (rule or '').strip()
    if is_bare_suffix(r):
        attr = r[1:]
        if attr == 'text':
            return node.get_text(strip=True)
        if attr == 'html':
            return str(node)
        v = node.get(attr)
        if v is None:
            return ''
        return v if not isinstance(v, list) else (v[0] if v else '')
    ts = parse_tag_short(r)
    if ts:
        tname, idx, tattr = ts
        try:
            found = node.find_all(tname)
        except Exception:
            found = []
        if not found or abs(idx) > len(found):
            return ''
        el = found[idx]
        return el.get_text(strip=True) if tattr == 'text' else (el.get(tattr) or '')
    sel, attr, regex = strip_suffixes(r)
    # ★ 相对选择器同样可能要处理 :eq() 之类的私有伪类；
    #   且必须用「切完后缀」的纯选择器去 select，否则 '@text' 会被当
    #   属性选择器塞给 soupsieve → SelectorSyntaxError（实测踩过）。
    if has_eq_pseudo(sel):
        pure, ops = split_eq_pseudo(sel)
    else:
        pure, ops = sel, []
    try:
        els = node.select(pure) if (pure or '').strip() else [node]
    except Exception as e:
        print('  ⚠ 解析异常：条目内选择器失败（%s）｜%r' % (e.__class__.__name__, sel))
        return ''
    if ops:
        els = apply_eq_pseudo(els, ops)
    if not els:
        return ''
    v = els[0].get_text(strip=True) if attr == 'text' else els[0].get(attr)
    if v is None:
        v = ''
    if isinstance(v, list):
        v = v[0] if v else ''
    return apply_regex(str(v), regex)


def eval_field(rule, html, base, subrules=None, binds=None, node=None):
    """跑一条非 JS 规则，返回单值。空值统一返回（空）。

    node 非空时按「条目内相对取值」处理（见 node_value）。
    """
    if not rule:
        return ''
    init_rule(rule, html, base)
    if rule.startswith('@js:'):
        out, _log = M.run(rule, base, subrules or {}, binds or {})
        return out if out is not None else ''
    if '<js>' in rule:
        # ★ `@css:...@text<js>result.replace(...)</js>` 是高频写法：
        #   必须**先按 CSS 取到值**，再把该值作为 result 交给 <js> 处理。
        #   早期实现把整条规则直接丢给 JS 执行器 → 页面 HTML 根本不是 result，
        #   规则恒返回空，看着像选择器写错（实测：悠空网 author 整列为空）。
        head = rule.split('<js>')[0]
        code = rule.split('<js>', 1)[1].rsplit('</js>', 1)[0]
        if head:
            if node is not None and (is_bare_suffix(head) or '<' not in head):
                cur = node_value(node, head)
            else:
                _sel, _attr, _re = strip_suffixes(head)
                _vals = css(html, _sel, None if _attr == 'text' else _attr)
                cur = _vals[0] if _vals else ''
                if isinstance(cur, list):
                    cur = cur[0] if cur else ''
                cur = apply_regex(cur if cur is not None else '', _re)
        else:
            cur = ''
        out, _log = M.run(code if code.strip().startswith(('return', 'var')) else code,
                          base, subrules or {}, dict(binds or {}, result=cur, src=cur))
        return out if out is not None else ''
    if node is not None and (is_bare_suffix(rule) or parse_tag_short(rule) or '<' not in rule):
        # 条目内相对取值：**只在该节点上求值**。
        # ★ 不可因取到空就退回整页 css() —— 那会对整页重解析一次，
        #   目录 1596 章 × 2 字段 = 3000+ 次全页解析，实测 194 秒并被 OOM 杀掉。
        #   节点上取不到就是空，这是正确语义（真机亦然）。
        return node_value(node, rule)
    sel, attr, regex = strip_suffixes(rule)
    vals = css(html, sel, attr if attr in ('textNodes', 'ownText') else (None if attr == 'text' else attr))
    # ★ 真机语义：`sel@text` 命中多个元素时，Legado 会把它们的文本**全部拼接**
    #   （正文 `#nr1 p@text` 逐段取值即依赖此行为，38 段全都要）。
    #   旧版一律 `vals[0]` → 只返回第一段（实测 38 段只给出 15 字），
    #   **会把正确的逐段规则误判成「取值过短」**。
    #   `@textNodes` / `@ownText` 同样是多值语义，一并拼接。
    if attr in ('text', 'textNodes', 'ownText'):
        v = '\n'.join(x for x in vals if isinstance(x, str) and x.strip())
    else:
        v = vals[0] if vals else ''
        if isinstance(v, list):
            v = v[0] if v else ''
    return apply_regex(v if v is not None else '', regex)


def eval_container(rule, html, base, subrules=None):
    """跑容器规则（bookList / chapterList），返回元素列表。"""
    init_rule(rule, html, base)
    if rule.startswith('@js:') or is_js_selector(rule) or '<js>' in rule:
        out, _log = M.run(rule, base, subrules or {})
        return str(out or '').split('\n')
    sel, attr, regex = strip_suffixes(rule)
    # ★ 容器规则必须返回**元素对象**，供后续按章取值（chapterName/chapterUrl）。
    #   旧版直接返回 css() 的字符串列表 → 目录循环拿到的是 str，
    #   再取 @text / @href 自然全空（且不报错）。实测踩过。
    return css_nodes(html, sel)


def css_nodes(html, sel):
    """按 CSS 选出**元素对象**列表（供容器规则逐条取值）。"""
    from bs4 import BeautifulSoup
    if not (sel or '').strip():
        print('  ⚠ 解析异常：选择器为空（规则可能只写了取值后缀如 @href）')
        return []
    pure, ops = split_eq_pseudo(sel) if has_eq_pseudo(sel) else (sel, [])
    try:
        soup = BeautifulSoup(html, 'html.parser')
        els = soup.select(pure) if pure.strip() else []
    except Exception as e:
        print('  ⚠ 解析异常：CSS 解析失败（%s）｜选择器 %r'
              % (e.__class__.__name__, sel))
        return []
    return apply_eq_pseudo(els, ops) if ops else els


def title(t):
    print('\n' + '-' * 64)
    print('【%s】' % t)
    print('-' * 64)


# 反爬站常在错误请求上返回「广告页 / 空壳页」而非错误码：
# HTTP 200、长度正常，靠状态码与长度判成败必翻车。
# 故这里只认**内容特征**——中文长文，且不含明显的壳页标记。
SHELL_MARKERS = (
    'uicyAds', 'adsbygoogle', 'googletag', 'window.location', '<script',
    '<html', '<div', 'document.cookie', 'Just a moment', 'Attention Required',
)


def is_real_content(s):
    """正文判定：看内容特征，不看长度。"""
    if not s:
        return False, '空'
    low = s
    for mk in SHELL_MARKERS:
        if mk in low:
            return False, '含壳页/广告标记 %r（多半是错误路径返回的页面，不是正文）' % mk
    zh = len(re.findall(r'[\u4e00-\u9fff]', s))
    if len(s) > 200 and zh / max(1, len(s)) > 0.5:
        return True, '中文占比 %.0f%%' % (100 * zh / len(s))
    if len(s) > 1000:
        return False, '长度看着正常但中文仅 %d 字 —— 疑似非正文' % zh
    return False, '疑似非正文（长度 %d，中文 %d）' % (len(s), zh)


def cn_num(s):
    m = re.match(r'[第（(]?\s*([零一二三四五六七八九十百\d]+)\s*[章回]', s)
    if not m:
        return None
    t = m.group(1)
    if t.isdigit():
        return int(t)
    d = {c: i for i, c in enumerate('零一二三四五六七八九')}
    if t == '十':
        return 10
    if '十' in t:
        x, _, y = t.partition('十')
        return (d.get(x, 1) if x else 1) * 10 + (d.get(y, 0) if y else 0)
    return d.get(t)


def judge_order(names):
    """判目录升降序（只判方向；分集会导致序数重置，不做连续性判断）。"""
    nums = [cn_num(n) for n in names]
    nums = [x for x in nums if x]
    if len(nums) < 3:
        return '样本不足（%d 条带序数）' % len(nums), nums
    asc = sum(1 for i in range(len(nums) - 1) if nums[i] < nums[i + 1])
    desc = sum(1 for i in range(len(nums) - 1) if nums[i] > nums[i + 1])
    if asc and not desc:
        return '升序 ✓', nums
    if desc and not asc:
        return '降序 ✗（章程颠倒，检查 ob=asc 是否生效）', nums
    return '方向混杂（升 %d / 降 %d）：本站按「集」分块，序数每集重置，属正常' % (asc, desc), nums


# ---------------------------- 各页签 ----------------------------


def tab_search(src, key, url):
    title('搜索')
    su = src.get('searchUrl', '')
    print('searchUrl: %s' % (su[:80] or '(空)'))
    rs = src.get('ruleSearch', {})
    list_rule = rs.get('bookList', '')
    # ★ 先取搜索入口。多数站点的 searchUrl 是 @js（要做编码），
    #   而 @js 规则里往往引用 key —— 务必显式注入，否则 ReferenceError
    #   会被吞成「输出空字符串」，看着像规则写错。
    if su.startswith('@js:'):
        out, log = M.run(su, url or SITE, {}, {'key': key})
        for u in log:
            print('  过程 java.ajax →', u)
        u = str(out or '')
        print('  @js 生成 → %r' % u)
    elif su:
        u = expand_page_tpl(su, 1).replace('{{key}}', enc_key(key))
    else:
        u = ''
        print('  未配置 searchUrl，改用 ruleSearch.bookList 的 @js 拼 URL')
    if not u and list_rule.startswith('@js:'):
        u = str(M.run(list_rule, url or SITE, {}, {'key': key})[0] or '')
        print('  由 bookList 生成 → %s' % (u[:90] + ('…' if len(u) > 90 else '')))
    if not u:
        print('  ✗ URL 为空，无法继续')
        return
    bare, _o = split_url_options(u)
    full = u if str(bare).startswith('http') else SITE + '/' + str(u).lstrip('/')
    html, code = get(full)
    _bu, _bo = split_url_options(full)
    # ★ 绝对化基准要用「纯 URL」，不能带 ,{...} 选项 —— 否则 bookUrl 会被
    #   拼成 'https://site/search.html, {"method":"POST"...' 这种垃圾。
    _base = _bu if str(_bu).startswith('http') else SITE
    _m = str(_bo.get('method', 'GET')).upper()
    print('  请求 %s %s' % (_m, _bu))
    if _m == 'POST' and _bo.get('body'):
        print('  POST 体 %s' % str(_bo['body'])[:100])
    print('  响应 HTTP %s  len=%d' % (code, len(html)))

    if list_rule.startswith('@js:'):
        # bookList 是 @js：它内部多半直接产出 JSON 字符串（真机上就是书名+链接的数组）
        out, log = M.run(list_rule, full, {})
        print('  过程 java.ajax:')
        for x in log:
            print('      →', x)
        raw = str(out or '')
        items = []
        try:
            j = json.loads(raw)
            items = j if isinstance(j, list) else [j]
        except Exception:
            print('  结果（非 JSON，原样末 200 字）: %s' % raw[-200:])
        print('  结果 %d 条' % len(items))
        for it in items[:5]:
            if isinstance(it, dict):
                print('    ', {k: str(v)[:40] for k, v in list(it.items())[:4]})
            else:
                print('    ', str(it)[:70])
        return

    _k = rule_kind(list_rule)
    if _k in ('jsonpath', 'xpath'):
        print('  ⚠ 未支持：bookList 为 %s 语法（%r）\u2014\u2014 本脚本只实现 CSS 与 @js，'
              '真机由 Legado 解析' % (_k, list_rule[:30]))
        # 仍尝试把该页抓下来给人看，避免「什么都没输出」
    items = eval_container(list_rule, html, full)
    # ★ 子规则要在「条目节点」上取值（bookUrl='@href' 是高频写法）；
    #   只传整页 html 会让这类字段全空，看着像规则写错。
    node = None
    if not (list_rule.startswith('@js:') or '<js>' in list_rule):
        # ★ 这里要的是**元素对象**（供 node.select/on.get），不是 css() 的文本结果。
        #   用 css() 拿到的字符串交给 node_value 会 AttributeError —— 实测踩过。
        sel0, _a0, _r0 = strip_suffixes(list_rule)
        pure0, ops0 = split_eq_pseudo(sel0) if has_eq_pseudo(sel0) else (sel0, [])
        try:
            _soup = BeautifulSoup(html, 'html.parser')
            els0 = _soup.select(pure0) if pure0.strip() else []
        except Exception as e:
            print('  ⚠ 解析异常：容器选择器失败（%s）｜%r' % (e.__class__.__name__, sel0))
            els0 = []
        if ops0:
            els0 = apply_eq_pseudo(els0, ops0)
        node = els0[0] if els0 else None
    print('  结果 %d 条' % len(items))
    if items:
        print('    首: %s' % str(items[0])[:60])
    for f in ('name', 'author', 'bookUrl', 'kind', 'coverUrl'):
        raw = rs.get(f, '')
        if not raw:
            continue
        v = eval_field(raw, html, full, node=node)
        if f in ('bookUrl', 'coverUrl') and v and not str(v).startswith(('http', 'data:')):
            # ★ 相对路径要以**站点根**为基准绝对化；用页面 URL 会拼出
            #   '/page/search.html/34.html' 这类垃圾（实测踩过）。
            v = absolutize(str(v), SITE)
        print('    %-9s %r' % (f, str(v)[:60]))
    if not (rs.get('name') or rs.get('bookUrl')):
        print('    （该源未单列字段规则，条目名与链接由 bookList 容器一次取出）')


# ---- 非 CSS 的其他规则语法：要能识别并给出「不支持」的明确提示，而不是崩 ----
# 真机 Legado 支持 CSS / XPath / JSONPath($.) / @json / @js / @XPath:，
# 本脚本只实现 CSS 与 @js。识别出来并明说，胜过拿 CSS 解析器去硬解、抛个 SelectorSyntaxError。

def rule_kind(rule):
    r = (rule or '').strip()
    if not r:
        return 'empty'
    if r.startswith('@js:') or is_js_selector(r):
        return 'js'
    if r.startswith('@json:') or r.startswith('$.') or r.startswith('$['):
        return 'jsonpath'
    if r.startswith('@xpath:') or r.startswith('//') or r.startswith('xpath:'):
        return 'xpath'
    if '<js>' in r:
        return 'css+js'
    return 'css'


def enc_key(key):
    """搜索词需 URL 编码。

    ★ 直接把中文塞进 URL，站点会返回 400（部分 curl 版本还会直接报
      "URL rejected: Malformed input"）。Legado 真机是会自动编码的，
      脚本不编码就会把「站点正常、规则正常」误判成规则有错。
    """
    import urllib.parse
    return urllib.parse.quote(str(key), safe='')


def expand_page_tpl(u, page):
    """展开 Legado 的分页模板。

    ★ `{{key}}<,{{page}}>` 里的 `<,...>` 是**可选段**：第 1 页整段省略，
      第 2 页起才带上。若当成字面量直接送出去（`/s/剑<,1>/`），
      站点多半 200 返回首页或 301 —— 看着像「翻页失效」，其实是模板没展开。
    """
    u = u or ''
    u = expand_host_vars(u)
    m = re.search(r'<,([^>]*)>', u)
    if m:
        seg = m.group(1).replace('{{page}}', str(page))
        rep = '' if str(page) in ('1', '', '0') else seg
        u = u[:m.start()] + rep + u[m.end():]
    return u.replace('{{page}}', str(page))

def expand_host_vars(u, base=''):
    """展开 Legado 宿主变量：{{baseUrl}} / {{bookUrl}} / {{key}} 等。

    ★ 真机 Legado 在 tocUrl / 正文等规则里会注入这些变量；脚本若不展开，
      会把 '{{baseUrl}}' 当字面 URL 送出去 → 看着像「规则写错」。
    """
    if not u:
        return u
    u = u.replace('{{baseUrl}}', (base or SITE or '').rstrip('/'))
    u = u.replace('{{bookUrl}}', base or '')
    return u


def lines_ok(raw):
    """展开 exploreUrl：兼容 JSON 数组与「组名::地址」两种写法。"""
    if not raw:
        return []
    t = str(raw).strip()
    if t.startswith('['):
        try:
            data = json.loads(t)
            return ['%s::%s' % (d.get('title', ''), d.get('url', '')) for d in data]
        except Exception:
            return []
    return [ln for ln in t.split('\n') if ln.strip()]


def tab_explore(src, cat, page, url):
    title('发现')
    raw = src.get('exploreUrl', '')
    if not lines_ok(raw):
        print('  \u2717 exploreUrl 与 explore 字段均为空 \u2014\u2014 该源无发现页，跳过')
        return
    base = url or SITE
    if str(raw).startswith('@js:'):
        out, log = M.run(raw, base, {}, {'page': str(page)})
        for x in log:
            print('  过程 java.ajax →', x)
        raw = str(out or '')
        print('  exploreUrl 由 @js 生成 %d 行' % len([x for x in raw.split('\n') if x.strip()]))
    lines = [ln for ln in raw.split('\n') if ln.strip()]
    print('发现入口 %d 个' % len(lines))
    pick = None
    for ln in lines:
        if ln.split('::')[0].strip() == cat:
            pick = ln
            break
    if pick is None:
        pick = lines[0] if lines else ''
    if not pick:
        print('  ✗ 无可用入口')
        return
    name, _, u = pick.partition('::')
    print('选用入口: %s' % name.strip())
    if u.startswith('@js:'):
        out, _ = M.run(u, url or base, {}, {'page': str(page)})
        u = str(out or '')
    u = u.replace('{{page}}', str(page))
    u = expand_page_tpl(u, page)
    bare, _o = split_url_options(u)
    full = u if str(bare).startswith('http') else base + '/' + u.lstrip('/')
    html, code = get(full)
    print('  请求 %s' % full)
    print('  响应 HTTP %s  len=%d' % (code, len(html)))
    re_ = src.get('ruleExplore', {})
    raw2 = re_.get('bookList', '')
    if str(raw2).startswith('@js:'):
        out, log = M.run(raw2, full, {})
        print('  过程 java.ajax:')
        for x in log:
            print('      →', x)
        s = str(out or '')
        print('  结果长度 %d，末 200 字: %s' % (len(s), s[-200:]))
        return
    items = eval_container(raw2, html, full)
    node2 = None
    if not (str(raw2).startswith('@js:') or '<js>' in str(raw2)):
        sel2, _a2, _r2 = strip_suffixes(raw2)
        try:
            _s2 = BeautifulSoup(html, 'html.parser')
            _e2 = _s2.select(sel2) if sel2.strip() else []
        except Exception as e:
            print('  ⚠ 解析异常：容器选择器失败（%s）｜%r' % (e.__class__.__name__, raw2))
            _e2 = []
        node2 = _e2[0] if _e2 else None
    print('  结果 %d 条' % len(items))
    if items:
        print('    首: %s' % str(items[0])[:60])
    for f in ('name', 'author', 'bookUrl', 'kind', 'intro', 'coverUrl', 'wordCount', 'lastChapter'):
        r = re_.get(f, '')
        if r:
            # ★ 逐条目取值：像 bookUrl='@href' 这种相对写法只有拿到条目节点才对。
            v = eval_field(r, html, full, node=node2)
            if f in ('bookUrl', 'coverUrl') and v and not str(v).startswith(('http', 'data:')):
                # 相对路径以站点根为基准（真机 Legado 亦如此）
                v = absolutize(str(v), SITE)
            print('    %-11s %r' % (f, str(v)[:60]))


def tab_info(src, book, url):
    title('详情')
    bu = url or SITE
    html, code = get(bu)
    print('  请求 %s' % bu)
    print('  响应 HTTP %s  len=%d' % (code, len(html)))
    bi = src.get('ruleBookInfo', {})
    subr = {}
    m = re.search(r'java\.getString\("([^"]+)"\)', bi.get('tocUrl', '') or '')
    if m:
        sr = m.group(1)
        subr[sr] = eval_field(sr, html, bu)
        print('  过程 java.getString(%s) -> %r' % (sr, subr[sr]))
    for f in ('name', 'author', 'kind', 'wordCount', 'intro', 'coverUrl', 'tocUrl'):
        r = bi.get(f, '')
        if not r:
            continue
        # ★ tocUrl 常写 {{baseUrl}}（指本书详情页）；须先展开宿主变量，
        #   否则会被当 CSS 选择器送进解析器 → SelectorSyntaxError。
        if f == 'tocUrl' and '{{' in r:
            v = expand_host_vars(r, bu).replace('{{id}}', str(book or ''))
        else:
            v = eval_field(r, html, bu, subr)
        if f == 'coverUrl' and v and not str(v).startswith(('http', 'data:')):
            v = absolutize(str(v), SITE)
        print('    %-9s %r' % (f, str(v)[:70]))


def tab_toc(src, book, url):
    title('目录')
    toc = src.get('ruleToc', {})
    bi = src.get('ruleBookInfo', {})
    b_id = book
    m = re.search(r'book-(\d+)', url or '')
    if m:
        b_id = m.group(1)
    # ★ 不写死站点路径：优先用 --url；否则用书源的目录地址规则自己算。
    #   旧版写死 /m/book-%s.html，只对 aabook 有效，换站必错。
    bu = url or ''
    bh = ''
    if not bu:
        pat = src.get('bookUrlPattern', '') or ''
        if b_id and pat:
            bu = pat.replace('{{id}}', b_id).replace('{{bookId}}', b_id)
        if not bu:
            # 无 --url、也无 bookUrlPattern：无法猜出本站书籍页形态。
            # 直接把 tocUrl 指向站点根让规则自证（如 ruleBookInfo.tocUrl 用 {{baseUrl}}）。
            bu = SITE
            print('  \u26a0 未给 --url 且书源无 bookUrlPattern，'
                  '以站点根请求（目录规则应基于书籍页，建议显式给 --url）')
    bh, _ = get(bu)
    subr = {}
    m2 = re.search(r'java\.getString\("([^"]+)"\)', bi.get('tocUrl', '') or '')
    if m2:
        subr[m2.group(1)] = eval_field(m2.group(1), bh, bu)
    # ★ {{baseUrl}} 在 tocUrl 里指「本书详情页地址」；须先展开，否则会被
    #   当成 CSS 选择器送进解析器 → SelectorSyntaxError（看着像规则写错）。
    tpl = bi.get('tocUrl', '') or ''
    if '{{' in tpl:
        turl = expand_host_vars(tpl, bu).replace('{{id}}', b_id or '')
    else:
        turl = eval_field(tpl, bh, bu, subr)
    if not turl:
        print('  \u2717 tocUrl 未生成地址 —— 请给书源补 ruleBookInfo.tocUrl（可用 {{baseUrl}}）')
        return
    print('  目录地址: %s' % turl)
    # 排序由站点决定、规则无法左右；末行会按「第 N 章」实测判定升/降序，
    # 故这里不再对特定站点参数（ob= 之类）作硬编码假设。
    html, code = get(str(turl))
    print('  响应 HTTP %s  len=%d' % (code, len(html)))
    cl = toc.get('chapterList', '')
    print('  chapterList: %s' % cl)
    # ★ 逐条目按「节点」取值，而不是整页批量取 name/href 再 zip：
    #   批量取在站点结构不对称时会错位，且无法支持 tag.a.0@href 这类相对写法。
    #   统一走 eval_container（支持 :eq/:has 等），避免此处的选择器处理与主链路不一致。
    try:
        _els2 = eval_container(cl, html, str(turl))
    except Exception as e:
        print('  ⚠ 解析异常：目录容器选择器失败（%s）｜%r' % (e.__class__.__name__, cl))
        _els2 = []
    n_rule = toc.get('chapterName', '')
    u_rule = toc.get('chapterUrl', '')
    names, urls = [], []
    for _el in _els2:
        _n = eval_field(n_rule, html, str(turl), node=_el) if n_rule else _el.get_text(strip=True)
        _u = eval_field(u_rule, html, str(turl), node=_el) if u_rule else ''
        _n = str(_n or '').strip()
        if not _n:
            continue
        names.append(_n)
        urls.append(str(_u or '').strip())
    print('  章节 %d 条' % len(names))
    if not names:
        print('  ✗ 未取到章节。请核 chapterList 选择器是否命中本页：%r' % cl)
        return
    print('      首: %s' % names[0][:34])
    print('      末: %s' % names[-1][:34])
    verdict, _nums = judge_order(names)
    print('  顺序: %s' % verdict)
    opts = css(html, 'div.mod.page select>option', 'value')
    print('  分页 option %d 个' % len(opts))
    nt = toc.get('nextTocUrl', '')
    if nt.startswith('@js:') and opts:
        m3 = re.search(r'java\.getString\("([^"]+)"\)', nt)
        s3 = m3.group(1) if m3 else '@css:div.mod.page select>option@value'
        out, _ = M.run(nt, str(turl), {s3: '\n'.join(opts)})
        urls = [x for x in str(out or '').split('\n') if x.strip()]
        print('  nextTocUrl -> %d 条' % len(urls))
        if urls:
            print('      首 %s' % urls[0])
            print('      末 %s' % urls[-1])
            mm = re.search(r'p=(\d+)', urls[-1])
            if mm:
                print('      末页页码 p=%s（站点对越界页码返回第 1 页，不报错，'
                      '多章风险看这里）' % mm.group(1))
            # 逐页抓取代价高（站点限流），只取末页验越界行为：
            # 站点对越界 p 会静默返回第 1 页内容而非报错，多章/循环风险就在这里。
            last_html, _ = get(urls[-1])
            last_names = css(last_html, sel)
            print('      末页实际条数: %d（首:%s）' % (
                len(last_names), last_names[0][:24] if last_names else '-'))
    elif nt:
        print('  nextTocUrl（非 @js）: %s' % nt[:60])
    else:
        print('  nextTocUrl: (空) —— 只有一页')


def tab_content(src, url):
    title('正文')
    rc = src.get('ruleContent', {}).get('content', '')
    cu = url
    if not cu:
        print('  ✗ 正文页签需要 --url 指定一个章节页')
        return
    print('  章节页: %s' % cu)
    if rc.startswith('@js:'):
        out, log = M.run(rc, cu, {})
        print('  过程 java.ajax:')
        for u in log:
            print('      ->', u)
        s = str(out or '')
        ok, why = is_real_content(s)
        print('  结果长度=%d  判定=%s' % (len(s), ('✓ 正文（%s）' % why) if ok else '✗ ' + why))
        paras = [p for p in s.split('\n') if p.strip()]
        print('  段数=%d' % len(paras))
        if paras:
            print('      首段: %s' % paras[0][:44])
            print('      末段: %s' % paras[-1][:44])
        if not ok:
            print('  ⚠ 判定为「非正文」时，先怀疑接口路径，而不是先怀疑选择器：')
            print('     反爬站常对错误路径返回广告页/空壳页，HTTP 200、长度正常，')
            print('     靠状态码与长度判成败必翻车；应改用「内容特征」判定。')
    else:
        html, code = get(cu)
        print('  响应 HTTP %s len=%d' % (code, len(html)))
        v = eval_field(rc, html, cu)
        print('  规则取值长度=%d' % len(str(v)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--what', default='all',
                    choices=['all', 'search', 'explore', 'info', 'toc', 'content'])
    ap.add_argument('--key', default='')
    ap.add_argument('--url', default='')
    ap.add_argument('--book', default='')
    ap.add_argument('--cat', default='')
    ap.add_argument('--page', default='1')
    a = ap.parse_args()

    src = json.load(open(a.source, encoding='utf-8'))
    set_site(src.get('bookSourceUrl', ''))
    set_header(src.get('header', ''))
    print('书源：%s' % src.get('bookSourceName'))
    print('入口：%s' % src.get('bookSourceUrl'))
    print('限流：concurrentRate=%s' % src.get('concurrentRate'))
    print('header：%s' % src.get('header'))

    w = a.what
    if w in ('all', 'search'):
        tab_search(src, a.key, a.url)
    if w in ('all', 'explore'):
        tab_explore(src, a.cat, a.page, a.url)
    if w in ('all', 'info'):
        tab_info(src, a.book, a.url)
    if w in ('all', 'toc'):
        tab_toc(src, a.book, a.url)
    if w in ('all', 'content'):
        tab_content(src, a.url)
    print()


if __name__ == '__main__':
    main()
