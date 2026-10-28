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

    ★ 2026-10-26 修：以 `/` 开头的路径必须补到**域名根**，不能直接拼在
      当前页地址后面。旧实现在正文分页场景把 `/1737/x_2.html` 拼成了
      `…/1737/1450832.html/1737/x_2.html` → 404 空页，看着像「正文取值为空」。
    """
    u = str(u or '').strip()
    if not u or u.startswith(('http://', 'https://')):
        return u
    b = (base or SITE or '').rstrip('/')
    if not b:
        return u
    if u.startswith('//'):          # 协议相对
        return 'https:' + u
    if u.startswith('/'):
        # 取基址的 scheme://host 部分
        m = re.match(r'^(https?://[^/]+)', b)
        return (m.group(1) if m else b) + u
    # 相对当前目录
    if b.endswith('/'):
        return b + u
    return b.rsplit('/', 1)[0] + '/' + u


def pick_charset(opts, content_type, raw):
    """响应解码字符集：URL 选项 charset → 响应头 → HTML meta → utf-8。

    ★ 真机 Legado 走 NetworkUtils.getCharset(contentType, bytes)，GBK 站若这里
      硬按 utf-8 解码，中文全成替换字符 —— 现象是「选择器全空/乱码」，
      极易被误判成规则写错。实测 wap.xbqg87.com（charset=gbk）即如此。
    """
    enc = (opts or {}).get('charset')
    if enc:
        return str(enc)
    m = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type or '', re.I)
    if m:
        return m.group(1)
    m = re.search(rb'charset\s*=\s*["\']?([\w-]+)', raw[:4096], re.I)
    if m:
        return m.group(1).decode('latin-1')
    return 'utf-8'

def get(url, ref=None):
    url, opts = split_url_options(url)
    url = absolutize(url, opts.get('_base') or SITE)
    # ★ 2026-10-27 修：必须带 --compressed。部分站点（实测 www.wxgbq.cc 的分类页）
    #   不看 Accept-Encoding，对没有 Accept-Encoding 头的请求也直接回 gzip 压缩体，
    #   解码出来全是乱码 → 选择器 0 条，看着像「规则写错了」。真机 OkHttp 默认
    #   自动解压，所以这是脚本自身的缺陷，不是书源问题。
    cmd = ['curl', '-s', '-L', '--compressed', '--max-time', '30',
           '-w', '\n__CODE__%{http_code}__CT__%{content_type}']
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
    raw = r.stdout
    code, ctype = '', ''
    # 尾部标记是 ASCII，先在 bytes 上切掉，避免编码不对时正则失配
    m = re.search(rb'\n__CODE__(\d+)__CT__([^\n]*)$', raw)
    if m:
        code = m.group(1).decode()
        ctype = m.group(2).decode('latin-1')
        raw = raw[:m.start()]
    enc = pick_charset(opts, ctype, raw)
    try:
        body = raw.decode(enc, 'replace')
    except LookupError:
        body = raw.decode('utf-8', 'replace')
    return body, code


def _jp_tokens(path):
    """把 `$.a.b[0].c` 切成 ['a','b',0,'c']；支持 $、.key、[n]、['key']。"""
    import re as _re
    p = path.strip()
    p = re.sub(r'^\$', '', p)
    toks = []
    i = 0
    while i < len(p):
        c = p[i]
        if c == '.':
            i += 1
            m = re.match(r'[A-Za-z_$][\w$\-]*', p[i:])
            if m:
                toks.append(m.group(0)); i += len(m.group(0))
        elif c == '[':
            j = p.find(']', i)
            if j < 0: break
            inner = p[i+1:j].strip()
            if (inner.startswith("'") and inner.endswith("'")) or \
               (inner.startswith('"') and inner.endswith('"')):
                toks.append(inner[1:-1])
            else:
                try: toks.append(int(inner))
                except ValueError: toks.append(inner)
            i = j + 1
        else:
            i += 1
    return toks


def _jp_get(obj, toks):
    """按 tokens 逐层取值；任一层缺失返回 None。数字键先按 list 下标，失败再按 str 键。"""
    cur = obj
    for t in toks:
        if cur is None: return None
        if isinstance(cur, dict):
            cur = cur.get(t)
        elif isinstance(cur, list):
            if isinstance(t, int) and 0 <= t < len(cur):
                cur = cur[t]
            else:
                return None
        else:
            return None
    return cur


def jsonpath(payload, sel, attr=None):
    """JSONPath 取值（Legado `$.` 语法子集）。

    支持：`$.a.b`、`$.a[0].b`、`$['a']['b']`、`$.a[*].b`
    语义对齐 Legado：返回**列表**（命中多个即多条，命中单个也包成单元素列表）。
    `attr` 为 `text` 时转字符串；payload 本身非 JSON 时**明确报错**，不静默成 0 条。
    """
    import json as _json
    sel = (sel or '').strip()
    if isinstance(payload, (dict, list)):
        data = payload
    else:
        try:
            data = _json.loads(payload)
        except Exception:
            print('  ⚠ JSONPath 作用于非 JSON 响应（%r 开头），请确认 searchUrl 返回 JSON'
                  % (str(payload)[:40]))
            return []
    toks = _jp_tokens(sel)

    # 支持 `[*]` 通配：逐段展开
    values = [data]
    for t in toks:
        nxt = []
        for v in values:
            if t == '*':
                if isinstance(v, list): nxt.extend(v)
                elif isinstance(v, dict): nxt.extend(v.values())
            else:
                got = _jp_get(v, [t])
                if got is not None:
                    nxt.append(got)
        values = nxt

    out = []
    for v in values:
        if isinstance(v, (dict, list)):
            out.append(_json.dumps(v, ensure_ascii=False))
        else:
            out.append('' if v is None else str(v))
    if not out:
        print('  ⚠ JSONPath %r 无命中（响应已解析为 JSON，非格式问题）' % sel)
    return out


def css(html, sel, attr=None):
    """取值统一入口。html 可以是 HTML 字符串，也可以是**dict 条目**（API 站场景）。"""
    # ★ dict 条目（来自 JSONPath 容器）：直接跑 JSONPath 取字段
    if isinstance(html, (dict, list)):
        k = rule_kind(sel)
        if k == 'jsonpath' or (sel or '').strip().startswith('$.') or sel == '$':
            return jsonpath(html, sel, attr)
        # 非 JSONPath 的取值（如 @text/@href）在 dict 上无意义，明确报错
        print('  ⚠ JSONPath 容器下，取值也必须是 JSONPath（当前 %r）' % sel)
        return []

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
    if k == 'jsonpath':
        return jsonpath(html, sel, attr)
    if k == 'xpath':
        print('  ⚠ 未支持：该规则是 %s 语法（%r），本脚本只实现 CSS、JSONPath 与 @js'
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
    if attr == 'html':
        # ★ 真机语义：`@html` 取元素的 outerHTML（含自身标签），正文净化阶段
        #   再把 <br>/<p> 还原为换行。旧版走 e.get('html') 恒 None → 正文恒空。
        return [str(e) for e in els]
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
    # ★ 2026-10-26 修：取值后缀不限于固定清单。Legado 里 `sel@data-src`、
    #   `sel@title`、`sel@alt`、`sel@content` 等任何属性都合法。
    #   旧实现把未知后缀一律降级成 `text`，于是 `class.x@img@src`（Default 规则里
    #   CSS 写法的空元素标签）被截断成选择器 `class.x@img` + 取值 `src`：
    #   选择器里残留 `@img` → 匹配 0 条 → 字段整列为空，看着像选择器写错。
    #   实测：uaamanhua.com 详情页 name/coverUrl 全空即由此而来。
    if attr not in VALUE_TAILS and not re.fullmatch(r'[A-Za-z][\w:.-]*', attr or ''):
        attr = 'text'
    expr = expr.strip()
    if not expr:
        print('  ⚠ 解析异常：选择器为空，原串=%r' % (rule,))
    return expr, attr, regex


def _expand_refs(rep, mt):
    """把替换串里的 $n / ${n} 换成对应捕获组，其余字符原样保留。"""
    res = []
    i = 0
    n = len(rep)
    while i < n:
        ch = rep[i]
        if ch == "$" and i + 1 < n:
            if rep[i + 1] == "{":
                j = rep.find("}", i + 2)
                if j > 0 and rep[i + 2:j].isdigit():
                    try:
                        res.append(mt.group(int(rep[i + 2:j])) or "")
                    except Exception:
                        res.append("")
                    i = j + 1
                    continue
            k = i + 1
            while k < n and rep[k].isdigit():
                k += 1
            if k > i + 1:
                try:
                    res.append(mt.group(int(rep[i + 1:k])) or "")
                except Exception:
                    res.append("")
                i = k
                continue
        res.append(ch)
        i += 1
    return "".join(res)


def apply_regex(value, regex):
    """处理「正则##替换」后缀，按 Jsoup Matcher 语义。

    写法（与 Legado 一致）：
      `前缀##正则##替换`    命中一次，替换为「替换」（可含 $1..$n）
      `前缀##正则##`        命中一次，直接删除
    未命中 → 空串（Jsoup 的 replaceAll 返回空串；Python 的 re.sub 会原样返回）。
    """
    if not regex:
        return value
    pieces = regex.split("##")
    if len(pieces) < 2:
        return value
    pat = pieces[0]
    replacement = pieces[1] if len(pieces) == 2 else pieces[2]
    try:
        obj = re.compile(pat)
    except re.error:
        return value
    if obj.search(value) is None:
        return ""
    if replacement:
        return obj.sub(lambda mt: _expand_refs(replacement, mt), value, count=1)
    return obj.sub("", value, count=1)


def init_rule(rule, html, base):
    """@init 段先跑（Legado 有此机制，常用于把「最新章节」存进 map）。

    ★ 2026-10-26 此处曾在一次批量替换中被误删，导致搜索/发现页签直接
      NameError。补回时按调用方期望保持「返回 None，异常不外抛」。
    """
    m = re.match(r'@init:\s*(@js:|<js>)(.*)', rule or '', re.S)
    if not m:
        return
    try:
        out, log = M.run('@js:' + m.group(2), base, {})
    except Exception as exc:  # noqa: BLE001
        print('    [@init] 执行失败：%s' % exc)
        return
    print('    [@init] 执行完成，java.ajax %d 次' % len(log or []))
    if log:
        print('            ' + str(log[0])[:80])
    return out


def _has_ref(rep):
    return bool(re.search(r"\$\{?\d+\}?", rep))


def _literal_refs(rep):
    """把除 $n 之外的 `$` 转义，避免 Python 模板把它当分组引用。"""
    return re.sub(r"\$(?![\d{])", chr(92) + "$", rep)


def is_bare_suffix(rule):
    """整条规则就是一个 `@属性`（无选择器）→ 在当前节点上取值。

    ★ 2026-10-26 该函数在批量替换中被误删，导致 node_value 与搜索页签
      NameError。按回归测试 test_debug_parser.py 的契约补回。
    """
    return bool(BARE_SUFFIX.match((rule or '').strip()))


BARE_SUFFIX = re.compile(r'^@[A-Za-z][\w-]*$')


def parse_tag_short(rule):
    """解析 `tag.a.0@href` → ('a', 0, 'href')；不是该写法返回 None。"""
    m = TAG_SHORT.match((rule or '').strip())
    if not m:
        return None
    idx = int(m.group(2)) if m.group(2) is not None else 0
    attr = m.group(3) or 'text'
    return m.group(1), idx, attr


TAG_SHORT = re.compile(r'^tag\.([A-Za-z][\w-]*)(?:\.(-?\d+))?\s*(?:@([\w-]+))?$')


def _rank(nodes, soup=None):
    """多个候选时按「内部文本长度」降序取前 3 个（同分保持文档序）。"""
    def size(e):
        try:
            return len(e.get_text(strip=True))
        except Exception:
            return 0
    return [e for _i, e in sorted(enumerate(nodes),
                                  key=lambda t: (-size(t[1]), t[0]))][:3]


def _default_step(node, seg):
    """Default 规则里的**一段**：tag / .class / tag.class / #id，返回其子孙元素。

    条目自身若就匹配该段（如条目是 <a>、段是 `a`），也算命中 ——
    Jsoup 的选择链含首元素自身匹配，漏掉会让 `tag.a@href` 恒空。
    """
    seg = (seg or '').strip()
    if not seg:
        return [node]
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(str(node), 'html.parser')
        root = soup.find()
        if root is None:
            return []
        sel = seg
        if seg.startswith('class.'):
            sel = '.' + seg[len('class.'):]
        elif seg.startswith('tag.'):
            sel = seg[len('tag.'):]
        name = re.split(r'[.#]', seg)[0]
        if name in ('class', 'tag'):
            name = ''
        classes = [c for c in re.findall(r'\.([\w-]+)', seg)]
        ids = re.findall(r'#([\w-]+)', seg)
        ok = True
        if name and getattr(root, 'name', None) != name:
            ok = False
        if classes:
            root_cls = root.get('class') or []
            if not all(c in root_cls for c in classes):
                ok = False
        if ids and (root.get('id') != ids[0]):
            ok = False
        hits = [node] if ok else []
        try:
            inner = node.select(sel)
        except Exception:
            inner = []
        for el in inner:
            if el is not node:
                hits.append(el)
        return hits
    except Exception:
        return []


def node_value(node, rule):
    """在指定节点上跑规则：只支持「纯后缀」与「@css:相对选择器@attr」。

    条目内相对取值是搜书类书源的高频写法，缺了它整页 bookUrl/coverUrl 全空。
    ★ `@text##正则##替换##` 这类「裸后缀 + 后处理」要**先取值、再应用正则**
      （旧版把整条当选择器 → soupsieve 抛 SelectorSyntaxError → 章节 0 条，
       看着像站点改版）。
    """
    if node is None:
        return ''
    r = (rule or '').strip()
    # 裸后缀 + 可选 `##正则##替换##` 后处理
    head, sep, tail = r.partition('##')
    if is_bare_suffix(head):
        attr = head[1:]
        if attr == 'text':
            val = node.get_text(strip=True)
        elif attr == 'html':
            val = str(node)
        else:
            _v = node.get(attr)
            val = '' if _v is None else (_v[0] if isinstance(_v, list) and _v else _v)
            if attr == 'title' and not val:
                # `@title` 缺失时回落 class 名（uaamanhua 的搜索条目没有 class 属性，
                # 但 a/@title 有值；反之部分站点把类型写在 class 里）
                _c = node.get('class') or []
                val = _c[0] if isinstance(_c, list) and _c else (_c or '')
        if sep and tail:
            return apply_regex(val, tail)
        return val
    ts = parse_tag_short(r)
    if ts and '##' not in r and r.strip().startswith('tag.'):
        tname, idx, tattr = ts
        try:
            found = node.find_all(tname)
        except Exception:
            found = []
        if node.name == tname:
            found = [node] + found
        if not found or abs(idx) >= len(found):
            return ''
        el = found[idx]
        val = el.get_text(strip=True) if tattr == 'text' else (el.get(tattr) or '')
        if tattr == 'title' and not val:
            _c = el.get('class') or []
            val = _c[0] if isinstance(_c, list) and _c else (_c or '')
        return val
    # ★ 2026-10-26 修：条目内的相对选择器**不要再走 strip_suffixes**。
    #   strip_suffixes 把任何 `@字母` 之后都当作取值后缀，`tag.a@href` 被切成
    #   选择器 `tag.a` + 取值 `href` —— 而 Default 规则里 `tag.a` 是「条目内所有
    #   <a>」，条目本身就是 <a>、内部没有 <a>，于是 select 命中 0 条，bookUrl/
    #   coverUrl 整列为空（实测 uaamanhua 搜索与发现都是如此，看着像选择器写错）。
    #   Legado 语义：`tag.x.序号@attr` 由 parse_tag_short 处理；`tag.a@href`
    #   是「条目内第一个 <a> 的 href」，条目自身就是 <a> 时仍应命中自身。
    m = re.fullmatch(r'tag\.([A-Za-z][\w-]*)(?:\.(-?\d+))?\s*(?:@([\w-]+))?(##.*)?', r, re.S)
    if m:
        tname, idx, tattr, post = m.group(1), m.group(2), m.group(3) or 'text', m.group(4) or ''
        try:
            found = node.find_all(tname)
        except Exception:
            found = []
        # 选择器命中自身也算（Jsoup 的 select 含自身祖先语义）
        if node.name == tname:
            found = [node] + found
        if not found:
            return ''
        if idx is not None:
            i0 = int(idx)
            if abs(i0) > len(found):
                return ''
            found = [found[i0]]
        el = found[0]
        val = el.get_text(strip=True) if tattr == 'text' else (el.get(tattr) or '')
        if tattr == 'title' and not val:
            # 条目自身没有 @title 时回落 class 名（部分站点把类型写进 class）
            _c = el.get('class') or []
            val = _c[0] if isinstance(_c, list) and _c else (_c or '')
        if post:
            return apply_regex(val, post[2:])
        return val
    sel, attr, regex = strip_suffixes(r)
    # ★ 2026-10-26 修：条目路径也必须认 Default 写法 `class.xxx@img@src`。
    #   strip_suffixes 只认**最后一个** `@`，`class.gap-2@a@title` 会被切成
    #   选择器 `class.gap-2@a`（soupsieve 抛 SelectorSyntaxError → 章节全空），
    #   而 Legado 的 Default 语义是「逐段下钻：class.gap-2 → a → 取 title」。
    if re.search(r'(^|\.)class\.[^\s@]+@', sel) and '/' in sel:
        # Tailwind 类名 `text-white/90` 只有 class 写法需要转义；CSS 选择器
        # （`p.text-sm`）里出现 `/` 是站点自己的类名，不能动。
        head_c, _, rest_c = sel.partition('@')
        sel = head_c.replace('/', '\\/') + ('@' + rest_c if rest_c else '')
    if re.search(r'(^|\.)class\.[^\s@]+(@|$)', sel):
        # 条目内同样支持 Default 写法 `class.a@tag.b@text`：逐段下钻；
        # 若是 `class.x@src` 这种「属性挂在容器自身」的写法，直接取属性。
        segs_c = [x for x in sel.split('@') if x.strip()]
        if len(segs_c) == 1 and attr not in ('text', 'textNodes', 'ownText'):
            cur = [node]
            for x in segs_c:
                cur = [e for c in cur for e in _default_step(c, x)]
            cur = [e for e in cur if e.get(attr)]
            return apply_regex('\n'.join(e.get(attr) or '' for e in cur), regex) if cur else ''
        cur = [node]
        for x in segs_c:
            cur = [e for c in cur for e in _default_step(c, x)]
        if not cur:
            return ''
        if attr in ('text', 'textNodes', 'ownText'):
            _v = '\n'.join(e.get_text(strip=True) for e in cur)
        else:
            _v = cur[0].get(attr) or ''
        return apply_regex(_v, regex)
    if not sel.startswith(('.', '#', '@css:', '@css ', '*', '[')):
        # ★ 只有「Default 分段写法」才下钻：`tag.a@title`、`class.x@a@text`。
        #   普通 CSS 选择器（`p.text-sm`、`div.a > b`）**不能**按 `@` 再切，
        #   否则 `p.text-sm##…##` 的后处理会丢（实测 uaamanhua 搜索 kind 全错）。
        segs = [x for x in sel.split('@') if x.strip()]
        is_default_chain = len(segs) > 1 and all(
            re.match(r'^(tag|class)\.[^\s.>#]+', x) or re.match(r'^[A-Za-z][\w-]*$', x)
            for x in segs)
        if is_default_chain:
            cur = [node]
            for s in segs[:-1]:
                nxt = []
                for c in cur:
                    nxt.extend(_default_step(c, s.strip()))
                cur = nxt
            if not cur:
                return ''
            el = cur[0]
            val = el.get_text(strip=True) if attr == 'text' else (el.get(attr) or '')
            return apply_regex(val, regex) if regex else val
    # ★ 相对选择器同样可能要处理 :eq() 之类的私有伪类；
    #   且必须用「切完后缀」的纯选择器去 select，否则 '@text' 会被当
    #   属性选择器塞给 soupsieve → SelectorSyntaxError（实测踩过）。
    sel = sel.replace('\\/', '/')
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
    # ★ `@html` 不是属性：旧版走 els[0].get('html') 恒得 None → 正文页签永远
    #   「取值长度=0」，与「正文规则写错」长得一模一样（实测 xbqg87 即此坑）。
    if attr == 'html':
        v = str(els[0])
    elif attr == 'text':
        v = els[0].get_text(strip=True)
    else:
        v = els[0].get(attr)
    if v is None:
        v = ''
    if isinstance(v, list):
        v = v[0] if v else ''
    return apply_regex(str(v), regex)


def _class_default_field(rule, html, attr, regex):
    """Default 规则里的 `class.xxx@a@text` 链式写法。

    Legado 的 Default 语义是**逐段下钻**（`class.x` 选容器 → `tag.a` 在其内找
    <a> → 取 text）。soupsieve 不认识 `class.` 前缀，直接喂进去必然抛
    SelectorSyntaxError（实测 uaamanhua 详情页 name/coverUrl 全空）。
    这里自己实现：每段用 CSS 选子孙，`tag.x` 段按标签名处理，条目自身也算命中。
    多个类名候选按文本量择优（`nav` 里常有同名小元素排在前面）。
    """
    from bs4 import BeautifulSoup
    segs = [s for s in rule.strip().partition('##')[0].split('@') if s.strip()]
    if not segs:
        return ''
    # rule 里若已包含取值段（`class.x@img@src`），末尾那段是取值而非选择器
    if len(segs) > 1 and segs[-1] == attr:
        segs = segs[:-1]
    first = segs[0][len('class.'):]
    soup = BeautifulSoup(html, 'html.parser')
    try:
        cur = _rank(soup.select('.' + first), soup)
    except Exception:
        cur = _rank([e for e in soup.find_all(True)
                     if first in (e.get('class') or [])], soup)
    for s in segs[1:]:
        m = re.match(r'^tag\.([A-Za-z][\w-]*)$', s)
        if m:
            tag = m.group(1)
            nxt = []
            for c in cur:
                if c.name == tag:
                    nxt.append(c)
                nxt.extend(c.find_all(tag))
            cur = nxt
            continue
        nxt = []
        for c in cur:
            try:
                nxt.extend(c.select(s))
            except Exception:
                pass
        cur = nxt
    if not cur:
        return ''
    if attr in ('text', 'textNodes', 'ownText'):
        v = '\n'.join(x.get_text(strip=True) for x in cur)
    else:
        v = '\n'.join(x.get(attr) or '' for x in cur)
    if not v.strip():
        return ''
    if regex and '(' not in regex.partition('##')[0]:
        # `##[\s\S]*简介：([\s\S]*)##$1` 这类**没有捕获组**的规则是「整段萃取」，
        # 直接取第一个匹配，不能用替换语义（会把匹配替换成空、留下别的部分）。
        try:
            mt = re.search(regex.partition('##')[0], v)
            return mt.group(0).strip() if mt else ''
        except re.error:
            pass
    # ★ 2026-10-26 修：`class.x@text##正则##替换` 的截断不能用 apply_regex
    #   （那是「替换全部匹配」语义）。Legado 的 `##正则##` 是**从文本里萃取**：
    #   无捕获组时取「第一个匹配到的片段」。实测 uaamanhua 的 author 规则被
    #   替换语义吞掉了后面的部分。
    #   → 若正则带捕获组，交给 apply_regex（替换 $1）；否则返回整段匹配。
    if regex:
        _pat = regex.partition('##')[0]
        try:
            if '##' not in _pat and '(' not in _pat:
                mt = re.search(_pat, v)
                return mt.group(0).strip() if mt else ''
        except re.error:
            pass
    return apply_regex(v, regex)


def eval_field(rule, html, base, subrules=None, binds=None, node=None):
    """跑一条非 JS 规则，返回单值。空值统一返回（空）。

    node 非空时按「条目内相对取值」处理（见 node_value）。
    ★ node 也可以是 **dict 条目**（JSONPath 容器场景），此时规则按其语义解释。
    """
    if not rule:
        return ''
    # ★ 2026-10-26 新增：Default 链式规则 `class.xxx@…@attr` 单独走
    #   `_class_default_field`。早前把它夹在 eval_field 中段，因分支语义
    #   互相干扰（取值后缀被当成属性过滤），一直取到空串。
    if (node is None and rule.lstrip().startswith('class.')
            and '@' in rule and '<js>' not in rule and '@js:' not in rule):
        head, _, post = rule.strip().partition('##')
        m2 = re.match(r'^(.*)@([A-Za-z][\w-]*)$', head)
        if m2:
            return _class_default_field(head, html, m2.group(2), post)
        return ''
    # ★ 条目是 dict（来自 `$.data.list` 这类 JSONPath 容器）：
    #   - `$.字段`  → 在该条目上跑 JSONPath
    #   - 含 `{{$.x}}` 的模板（如 /book/{{$.id}}.html）→ 从该条目插值
    #   - 其余（@text/@href 之类 HTML 取值）在 JSON 上无意义，明确报错
    if isinstance(node, (dict, list)):
        r = rule.strip()
        if r.startswith('$.') or r.startswith('$[') or r == '$':
            vals = jsonpath(node, r)
            return vals[0] if vals else ''
        if '{{$.' in r:
            return expand_host_vars(r, base, node)
        print('  ⚠ JSONPath 容器下取值 %r：条目是 JSON，取字段请用 $.字段' % r[:30])
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
        # ★ 规则里可能有**两段** <js>：`https://m.x.com<js>路径</js>@css:...@text<js>净化</js>`。
        #   旧实现取「第一个 <js> 之前」当选择器、取「第一个 <js> 到最后一个 </js>」
        #   当脚本，于是只有前缀地址（如 https://m.wxgbq.cc）被当选择器解析 →
        #   SelectorSyntaxError、取值恒空。正确做法：先把非末段的 <js> 段当模板求值，
        #   剩下最后一段才是后处理脚本。
        _seg = rule.rsplit('<js>', 1)
        head = _seg[0]
        code = _seg[1].rsplit('</js>', 1)[0] if len(_seg) == 2 else ''
        if head:
            # ★ 带 URL 前缀（`https://m.x.com/path@css:...`）必须走「取另一页」分支，
            #   不能被 '<' not in head 误判成条目内相对取值。
            if (node is not None and '<' not in head
                    and not re.match(r'^https?://', head.strip())):
                cur = node_value(node, head)
            elif node is not None and is_bare_suffix(head):
                cur = node_value(node, head)
            else:
                head_s = head.strip()
                # 前缀里的 <js> 段（拼路径）先就地求值，与真机逐段求值一致
                # ★ 求值前把 result/src/text 置空：保留 CSS 变量的话，js_eval 会走
                #   「expression-replace」通路（把表达式替换进占位符后当 CSS 用），
                #   拿到的是原值而非 JS 结果。
                if '<js>' in head_s:
                    _o, _l = M.run(head_s.split('<js>', 1)[1].split('</js>', 1)[0],
                                   base, {}, dict(binds or {}, baseUrl=base,
                                                  bookUrl=base, result='', src='', text=''))
                    # ★ 用 rsplit 取「最后一个 <js> 之后」的尾巴；split('<js>')[0]
                    #   会把后缀（@css:…@text）一起丢掉，导致只剩一个地址。
                    _tail = head_s.rsplit('</js>', 1)[1] if '</js>' in head_s else ''
                    head_s = head_s.split('<js>', 1)[0] + str(_o or '') + _tail
                # ★ URL 前缀：Legado 允许规则写成「地址@css:…」，表示去那个
                #   地址取值。原实现把整串当选择器 → SelectorSyntaxError、取值恒空。
                #   切法：定位模式头（@css:/@xpath:/@json:），其前为地址。
                src_html, src_base = html, base
                head_s = head_s.replace('<js>', '').replace('</js>', '')
                _p = head_s.find('@css:')
                for _k in (head_s.find('@xpath:'), head_s.find('@json:')):
                    if _k > 0 and (_p < 0 or _k < _p):
                        _p = _k
                if _p > 0:
                    _addr = head_s[:_p].strip().rstrip('&').strip()
                    if _addr.startswith('http'):
                        src_html, _c = get(_addr)
                        src_base = _addr
                        head_s = head_s[_p:]
                _sel, _attr, _re = strip_suffixes(head_s)
                _vals = css(src_html, _sel, None if _attr == 'text' else _attr)
                cur = _vals[0] if _vals else ''
                if isinstance(cur, list):
                    cur = cur[0] if cur else ''
                cur = apply_regex(cur if cur is not None else '', _re)
        else:
            cur = ''
        out, _log = M.run(code, base, subrules or {},
                          dict(binds or {}, result=cur, src=cur, text=cur, __inner=cur))
        out = out if out is not None else ''
        return out
    if node is not None and (is_bare_suffix(rule) or is_bare_suffix(rule.split('##')[0])
                             or parse_tag_short(rule) or '<' not in rule):
        # 条目内相对取值：**只在该节点上求值**。
        # ★ 不可因取到空就退回整页 css() —— 那会对整页重解析一次，
        #   目录 1596 章 × 2 字段 = 3000+ 次全页解析，实测 194 秒并被 OOM 杀掉。
        #   节点上取不到就是空，这是正确语义（真机亦然）。
        return node_value(node, rule)
    # ★ 含多个 `@` 的 Default 链式规则（`class.x@img@src`）不能交给
    #   strip_suffixes —— 它只认最后一个 `@`，会把倒数第二个 `@img` 当取值。
    if rule.count('@') > 1 and '@css:' not in rule and '<js>' not in rule:
        head, _, post = rule.partition('##')
        m2 = re.match(r'^(.*)@([A-Za-z][\w-]*)$', head)
        if m2:
            sel, _a, _ = strip_suffixes(m2.group(1))
            attr = m2.group(2)
            regex = post
    else:
        sel, attr, regex = strip_suffixes(rule)
    if sel == 'ERRCLASS':
        return ''
    # ★ 顶层（整页）的 `tag.x@attr` 简写：Legado Default 语义是「页面里第一个
    #   <x>」。旧实现把 `tag.h1` 原样交给 soupsieve → 匹配 0 条（tag 不是标签名），
    #   详情页书名整列为空（实测 uaamanhua）。
    m_top = re.match(r'^tag\.([A-Za-z][\w-]*)(?:\.(-?\d+))?$', sel)
    if m_top:
        try:
            soup_top = BeautifulSoup(html, 'html.parser')
            found_top = soup_top.find_all(m_top.group(1))
        except Exception:
            found_top = []
        if m_top.group(2) is not None:
            idx_top = int(m_top.group(2))
            found_top = [found_top[idx_top]] if abs(idx_top) <= len(found_top) else []
        else:
            found_top = found_top[:1]
        if not found_top:
            return ''
        el_top = found_top[0]
        v_top = (el_top.get_text(strip=True) if attr in ('text', 'textNodes', 'ownText')
                 else (el_top.get(attr) or ''))
        return apply_regex(v_top, regex)
    vals = css(html, sel, attr if attr in ('textNodes', 'ownText') else (None if attr == 'text' else attr))
    # ★ 真机语义：`sel@text` 命中多个元素时，Legado 会把它们的文本**全部拼接**
    #   （正文 `#nr1 p@text` 逐段取值即依赖此行为，38 段全都要）。
    #   旧版一律 `vals[0]` → 只返回第一段（实测 38 段只给出 15 字），
    #   **会把正确的逐段规则误判成「取值过短」**。
    #   `@textNodes` / `@ownText` 同样是多值语义，一并拼接。
    if attr in ('text', 'textNodes', 'ownText'):
        v = '\n'.join(x for x in vals if isinstance(x, str) and x.strip())
    else:
        # ★ 属性取值同样是**多值**语义：图片型书源 `div.box img@src` 就是靠
        #   它拿到整个章节的所有图。旧版只取 vals[0] → 60 张图只给 1 张，
        #   把正确的图集规则误判成「非正文」。
        clean = [x for x in vals if isinstance(x, str) and x.strip()]
        if not clean:
            v = ''
        elif len(clean) == 1:
            v = clean[0]
        else:
            v = '\n'.join(clean)
    return apply_regex(v if v is not None else '', regex)


def eval_container(rule, html, base, subrules=None):
    """跑容器规则（bookList / chapterList），返回元素列表。"""
    init_rule(rule, html, base)
    if rule.startswith('@js:') or is_js_selector(rule) or '<js>' in rule:
        out, _log = M.run(rule, base, subrules or {})
        return str(out or '').split('\n')
    sel, attr, regex = strip_suffixes(rule)
    # ★ JSONPath 容器（API 站）：返回 **dict 条目列表**，供后续 $.字段 逐条取值
    if rule_kind(sel) == 'jsonpath':
        import json as _json
        try:
            data = _json.loads(html)
        except Exception:
            print('  ⚠ 解析异常：容器是 JSONPath（%r）但响应不是 JSON' % rule)
            return []
        toks = _jp_tokens(sel)
        vals = [data]
        for t in toks:
            nxt = []
            for v in vals:
                if t == '*':
                    if isinstance(v, list): nxt.extend(v)
                    elif isinstance(v, dict): nxt.extend(v.values())
                else:
                    g = _jp_get(v, [t])
                    if g is not None: nxt.append(g)
            vals = nxt
        if len(vals) == 1 and isinstance(vals[0], list):
            return vals[0]
        return vals
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

# —— 失败分型（2026-10-26 借自 Narylr350/book-source-creator-skill 的 errorCode 思路）
# 目的：把「取不到东西」拆成可定位的几类，避免一律报「规则写错了」。
# 不改任何求值逻辑，只补诊断输出；HARNESS 项表示本脚本能力边界，不是源的缺陷。
def code_of(phase, code, failed_field=None, detail=''):
    tag = '%s.%s' % (phase, code)
    msg = '  ✗ [%s]' % tag
    if failed_field:
        msg += ' 字段 %s' % failed_field
    if detail:
        msg += ' —— %s' % detail
    print(msg)
    return tag

def classify_container(phase, rule, items):
    """容器级失败分型：区分「没匹配」与「匹配了但 0 条」。"""
    if items:
        return None
    if rule_kind(rule) in ('xpath', 'js') or '<js>' in str(rule):
        return code_of(phase, 'HARNESS_UNSUPPORTED', None,
                       '该容器规则形态本脚本无法求值（xpath/@js），真机由 Legado 解析；本项记「未评估」')
    return code_of(phase, 'SELECTOR_EMPTY', None,
                   '容器在本次响应上匹配 0 个节点；先确认响应是否为目标页（bodyPreview/长度）')

def classify_content(s, code=None):
    """正文分型：把「非正文」落到具体错误码。"""
    try:
        code_int = int(code) if code is not None and str(code).strip().isdigit() else None
    except (TypeError, ValueError):
        code_int = None
    if not s:
        return code_of('content', 'CONTENT_EMPTY', 'ruleContent.content', '规则取值为空')
    if code_int == 404:
        return code_of('content', 'HTTP_BLOCKED', None, 'HTTP 404，请求路径不存在')
    if code_int and code_int >= 400:
        return code_of('content', 'HTTP_BLOCKED', None, 'HTTP %s' % code_int)
    low = str(s)
    if 'Just a moment' in low or 'Attention Required' in low:
        return code_of('content', 'CONTENT_IS_CAPTCHA_PAGE', None, '响应是 Cloudflare 人机验证页')
    if re.search(r'(请登录|登录后|扫码登录|sign in|log in)', low[:2000], re.I):
        return code_of('content', 'CONTENT_IS_LOGIN_PAGE', None, '响应像登录页，需 Cookie/登录态')
    if re.search(r'(VIP|会员|订阅|付费|购买本章)', low[:2000]) and len(low) < 800:
        return code_of('content', 'CONTENT_IS_VIP_LOCK_PAGE', None, '响应是付费/会员提示页，只能记 degraded')
    zh = len(re.findall(r'[\u4e00-\u9fff]', low))
    if len(low) < 100:
        return code_of('content', 'CONTENT_TOO_SHORT', 'ruleContent.content',
                       '仅 %d 字符，低于 100 字符门槛' % len(low))
    if zh < 20 and '<script' in low[:4000]:
        return code_of('content', 'CONTENT_IS_CSR_SHELL', 'ruleContent.content',
                       '中文极少且含脚本，疑似前端渲染空壳，需 webView/webJs')
    return None


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
    if _k == 'xpath':
        print('  ⚠ 未支持：bookList 为 xpath 语法（%r）—— 本脚本只实现 CSS 与 JSONPath，'
              '真机由 Legado 解析' % (list_rule[:30],))
    items = eval_container(list_rule, html, full)
    # ★ 子规则要在「条目节点」上取值（bookUrl='@href' 是高频写法）；
    #   只传整页 html 会让这类字段全空，看着像规则写错。
    node = None
    if not (list_rule.startswith('@js:') or '<js>' in list_rule):
        # ★ 这里要的是**元素对象**（供 node.select/on.get），不是 css() 的文本结果。
        #   用 css() 拿到的字符串交给 node_value 会 AttributeError —— 实测踩过。
        # ★ 若容器是 JSONPath（返回 dict 条目），node 直接用**当前条目**，
        #   不能再拿 BeautifulSoup 去 HTML 里选（JSON 站点选不出东西，字段全空）。
        if items and isinstance(items[0], (dict, list)):
            node = items[0]
        else:
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
# 本脚本实现 CSS、JSONPath 与 @js（xpath 未实现）。识别出来并明说，胜过拿 CSS 解析器去硬解、抛个 SelectorSyntaxError。

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
    u = expand_host_vars(u, '', None)
    m = re.search(r'<,([^>]*)>', u)
    if m:
        seg = m.group(1).replace('{{page}}', str(page))
        rep = '' if str(page) in ('1', '', '0') else seg
        u = u[:m.start()] + rep + u[m.end():]
    return u.replace('{{page}}', str(page))

def expand_host_vars(u, base='', item=None):
    """展开 Legado 宿主变量：{{baseUrl}} / {{bookUrl}} / {{key}} 等。

    ★ 真机 Legado 在 tocUrl / 正文等规则里会注入这些变量；脚本若不展开，
      会把 '{{baseUrl}}' 当字面 URL 送出去 → 看着像「规则写错」。
    """
    if not u:
        return u
    # ★ 不要 rstrip('/')：真机注入的 baseUrl 是 bookUrl 原文，`/5/5518/` 这类
    #   以斜杠结尾的书籍页被剥成 `/5/5518` 会 404，看着像「目录规则写错」。
    u = u.replace('{{baseUrl}}', (base or SITE or ''))
    u = u.replace('{{bookUrl}}', base or '')
    # ★ `<js>…</js>` 段在 Legado 里是逐段求值：它前面的部分只是「把值拼进来」。
    #   脚本若整体当选择器送进 CSS 解析，就会出现「选择器 'https://m.xxx' 解析失败」。
    #   这里把首段 <js> 就地求值（用 baseUrl 做宿主变量），与真机语义一致。
    m_js = re.search(r'<js>([\s\S]*?)</js>', u)
    if m_js:
        try:
            out, _log = M.run(m_js.group(1), base or SITE or '', {},
                              {'baseUrl': base or SITE or '', 'bookUrl': base or ''})
            if out is None:
                out = ''
            u = u[:m_js.start()] + str(out) + u[m_js.end():]
        except Exception:
            pass
    # ★ {{$.xxx}} —— 从「当前条目」的 JSON 取值插值（如 bookUrl: /book/{{$.id}}.html）
    if '{{$.' in u and item is not None:
        import re as _re

        def _rep(m):
            toks = _jp_tokens('$.' + m.group(1))
            v = _jp_get(item, toks)
            return '' if v is None else str(v)

        u = re.sub(r'\{\{\$\.([\w.$\[\]]+)\}\}', _rep, u)
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
            _e2 = css_nodes(html, sel2)
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
    m = re.search(r'java\.getString\("((?:[^"\\]|\\.)+)"\)', bi.get('tocUrl', '') or '')
    if m:
        sr = m.group(1)
        subr[sr] = eval_field(sr, html, bu)
        print('  过程 java.getString(%s) -> %r' % (sr, subr[sr]))
    for f in ('name', 'author', 'kind', 'wordCount', 'intro', 'coverUrl',
              'lastChapter', 'updateTime', 'tocUrl'):
        r = bi.get(f, '')
        if not r:
            continue
        # ★ tocUrl 常写 {{baseUrl}}（指本书详情页）；须先展开宿主变量，
        #   否则会被当 CSS 选择器送进解析器 → SelectorSyntaxError。
        if f == 'tocUrl' and '{{' in r:
            v = expand_host_vars(r, bu, r).replace('{{id}}', str(book or ''))
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
    # ★ 从 --url 提取书籍 ID：不可写死某一站的形态（旧版写死 'book-(\d+)'，
    #   只对 aabook 有效，换站必空 → tocUrl 展开成 'indexList-.html'）。
    #   改为通用：先试 bookUrlPattern（书源自带，最权威），再退化为「路径中
    #   最长的一段数字」。
    _m = None
    _pat = src.get('bookUrlPattern', '') or ''
    if _pat and url:
        _pm = re.search(_pat, url)
        if _pm and _pm.groups():
            _m = _pm
    if not _m and url:
        _cands = re.findall(r'\d{3,}', url)
        if _cands:
            b_id = max(_cands, key=len)
    elif _m:
        b_id = _m.group(1)
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
    m2 = re.search(r'java\.getString\("((?:[^"\\]|\\.)+)"\)', bi.get('tocUrl', '') or '')
    if m2:
        subr[m2.group(1)] = eval_field(m2.group(1), bh, bu)
    # ★ {{baseUrl}} 在 tocUrl 里指「本书详情页地址」；须先展开，否则会被
    #   当成 CSS 选择器送进解析器 → SelectorSyntaxError（看着像规则写错）。
    tpl = bi.get('tocUrl', '') or ''
    # ★ 真机 Legado 在 tocUrl 里**只有 {{baseUrl}} 等变量，没有 {{bookId}}**
    #   （{{bookId}} 是早期本脚本私加的，会让真机报 `ReferenceError: bookId 未定义`，
    #    已在书海阁上实测踩到）。
    #   本脚本一律按**真机语义**处理：展开变量后，再应用 `##正则##替换##`，
    #   绝不能对真机不认的占位符放行。
    if '{{' in tpl:
        turl = expand_host_vars(tpl, bu, None)
    else:
        turl = eval_field(tpl, bh, bu, subr)
    # `##正则##替换##`（tocUrl 常见写法：从详情页 URL 提取书籍 ID）
    if turl.count('##') >= 2:
        _head, _rest = turl.split('##', 1)
        turl = apply_regex(_head, _rest)
    # 兼容老写法：{{id}} 展开（部分书源确实这么用）
    if b_id:
        turl = turl.replace('{{id}}', b_id)
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
        # ★ 分型：容器有节点但章节名全空 ≠ 容器没匹配（此前两者都只报一句“未取到章节”）
        if _els2:
            code_of('toc', 'TOC_EMPTY', 'ruleToc.chapterName',
                    '容器命中 %d 个节点但章节名全空；先查 chapterName 是否带 @text 取值' % len(_els2))
        else:
            code_of('toc', 'TOC_SELECTOR_EMPTY', 'ruleToc.chapterList',
                    '容器在本页匹配 0 个节点')
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
        if not ok:
            classify_content(s)
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
        cu2 = cu
        if '<js>' in cu:
            cu2 = expand_host_vars(cu, cu)
            print('  URL 求值后: %s' % cu2)
        html, code = get(cu2)
        print('  响应 HTTP %s len=%d' % (code, len(html)))
        v = eval_field(rc, html, cu2)
        print('  规则取值长度=%d' % len(str(v)))
        _ok, _why = is_real_content(str(v))
        if not _ok:
            print('  判定=✗ %s' % _why)
            classify_content(str(v), code)
        else:
            print('  判定=✓ 正文（%s）' % _why)
        s = str(v)
        print('      首段: %s' % s[:44].strip())
        print('      末段: %s' % s[-44:].strip())


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

    src = json.load(open(a.source, encoding='utf-8-sig'))
    # Legado 书源标准导出是数组 [{...}]，也允许单对象。两种形态都接受，
    # 数组时取第 1 项（调试面板一次只针对一个源）。
    if isinstance(src, list):
        if not src:
            print('✗ 文件是空数组，没有书源可调试')
            return
        if len(src) > 1:
            print('⚠ 文件含 %d 个书源，只调试第 1 个：%s'
                  % (len(src), src[0].get('bookSourceName')))
        src = src[0]
    if not isinstance(src, dict):
        print('✗ 顶层不是对象或数组，无法识别为书源')
        return
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
