#!/usr/bin/env python3
"""原样执行书源里的 @js: 规则（node 版），用 execSync('curl') 同步实现 java.ajax。

为什么用 node 而不是 /tmp/legadoSkill 的 js_engine：
  那套引擎的 java.ajax 依赖 `from debugger.js_engine import ...`，沙箱 sys.path 里没有
  debugger 包，必然 ModuleNotFoundError；且它对任何 @js: 一律返回空（连 @js:'HELLO'
  都是 ''），完全不能用来判定规则真假。
  node + execSync('curl') 是最贴近 Rhino 同步语义的做法。

差异说明（必须牢记）：
  * Rhino 取「最后一条表达式的值」作为规则结果；node 的 Function 不然。
    故这里把结尾的裸表达式包成显式 return —— 语义等价，不是改规则。
  * java.getString(rule) 在真机是「对当前响应文档再跑一条子规则」。
    这里用 Python 侧先算好子规则，再注入为常量。

用法: python3 exec_js_rule_node.py <rule.json> <baseUrl> [subrules.json]
   rule.json    : {"rule": "@js:..."}
   subrules.json: {"@css:xxx@value": "已算好的文本"}
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

CTX = __import__('ssl').create_default_context()
CTX.check_hostname = False
CTX.verify_mode = __import__('ssl').CERT_NONE
UA = {'User-Agent': 'curl/8.5.0'}


def fetch(url):
    req = urllib.request.Request(url)
    for k, v in UA.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def host_of(u):
    import re
    m = re.match(r'^(https?://[^/]+)', u)
    return m.group(1) if m else u


def _top_level_tail_start(body):
    """返回末尾「顶层语句」的起始下标（用于把裸表达式包成 return）。

    为什么不能简单地按最后一个 ';' 切：JS 语句体内部也有 ';'，切错会把
    `return` 塞进 for 循环体里 —— 这正是本工具早期返回空的真因（实测过）。

    做法：先跳过尾部空白；若末尾是 ';' 或 '}' 之外的表达式，则从后往前找
    深度为 0 的最近一个语句边界（';' 或关闭的顶层 '}'），其后的内容即尾语句。
    """
    s = body.rstrip()
    if not s:
        return len(body)
    # 末尾是分号/花括号 → 没有裸表达式，无需改写
    if s[-1] in ';{}':
        return len(s)
    # 找最后一个「顶层分号」。这里**不做字符串/正则解析**：
    # JS 正则里的 / 与字符串里的引号会互相干扰，越猜越错；
    # 而这条规则要处理的尾表达式（t.trim() / out.join("\n")）都不含分号，
    # 故「最后一个分号之后」即为尾语句——简单且可辩护。
    idx = s.rfind(';')
    if idx < 0:
        return 0
    # 分号可能在 for(;;) 头里：若其后的片段含未配平的括号，说明切早了，向前再找
    while idx >= 0:
        cand = s[idx + 1:]
        if _balanced(cand):
            return idx + 1
        idx = s.rfind(';', 0, idx)
    return 0


def _balanced(fragment):
    depth = 0
    for ch in fragment:
        if ch in '{([':
            depth += 1
        elif ch in '})]':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0



def build_driver(js_body, base_url, subrules, binds=None, charset=None):
    """生成 node driver。

    java.ajax       -> execSync('curl')，最贴近 Rhino 的同步语义
    java.getString  -> 读预置子规则（真机是「对响应文档再跑一条规则」，此处预置）
    末值语义        -> 先用 new Function 直接跑；若规则以裸表达式结尾（Rhino 会取它
                       的值），则用「最后一行表达式求值」兜住。
    binds           -> 注入规则里引用的宿主变量（key / page 等）。
                       ★ 不注入就会 ReferenceError；早期 driver 把整段 try/catch
                       吞了，表现为「输出空字符串」，看起来像规则写错（真事）。
    """
    sub_json = json.dumps(subrules, ensure_ascii=False)
    # ★ `result` 与 `src` 是 Legado 的隐式入参：<js>result.replace(...)</js>
    #   这类规则全靠它。不注入 → ReferenceError → 被 catch 吞成空串，
    #   现象与「规则写错」一模一样（实测：悠空网 author 整列为空）。
    allbinds = dict(binds or {})
    allbinds.setdefault('result', allbinds.get('src', ''))
    allbinds.setdefault('src', allbinds.get('result', ''))
    bind_js = '\n'.join('global.%s = %s;' % (k, json.dumps(v, ensure_ascii=False))
                        for k, v in allbinds.items())
    return '''
const { execSync } = require('child_process');
const SUBS = %s;
const ENC = %s;
const LOG = [];
global.baseUrl = %s;
%s
global.java = {
  ajax: function(u){
    LOG.push(String(u));
    // ★ 2026-10-27：同 js_eval.js —— 加 --compressed，并按 ENC 解码
    const out = execSync('curl -s -L --compressed --max-time 30 -A "curl/8.5.0" ' + JSON.stringify(String(u)),
                         {maxBuffer: 64*1024*1024});
    return out.toString(ENC);
  },
  getString: function(rule){ return SUBS[rule] !== undefined ? SUBS[rule] : ''; },
  encodeURI: function(s){ return encodeURIComponent(String(s)); },
  log: function(){}
};

const SRC = %s;
let out;
// Rhino 取「最后一条表达式的值」。做法：先整体当语句执行，
// 若结果为空且源码以裸表达式结尾，则把该表达式改成 return 再跑一次。
function evalWhole(src) {
  return new Function(src + '\\n;')();
}
function evalWithReturn(src) {
  // 从后往前找「能组成合法尾表达式」的位置：候选点取所有 ';' 与 '}' 之后，
  // 用 new Function 真语法检查，第一个通过的即为尾表达式。
  const cuts = [];
  for (let i = 0; i < src.length; i++) {
    if (src[i] === ';' || src[i] === '}') cuts.push(i + 1);
  }
  cuts.push(0);
  for (let c = cuts.length - 1; c >= 0; c--) {
    const head = src.slice(0, cuts[c]);
    const tail = src.slice(cuts[c]).trim();
    if (!tail) continue;
    if (/^(return|var |let |const |if *\\(|for *\\(|while *\\()/.test(tail) || tail === '}' || tail.startsWith('else')) continue;
    try {
      // 头必须是合法语句序列，尾必须是合法表达式
      new Function(head);
      new Function('return (' + tail + ');');
      return new Function(head + '\\nreturn (' + tail + ');')();
    } catch (e) { /* 换更靠前的切点 */ }
  }
  return undefined;
}
let ERR = '';
try {
  out = evalWhole(SRC);
  if (out === undefined || out === null || out === '') {
    const r2 = evalWithReturn(SRC);
    if (r2 !== undefined) out = r2;
  }
} catch (e) {
  // ★ 不能只 console.error 了事：真实规则里的 ReferenceError（例如没注入 key）
  //   会被吞成「输出空字符串」，看上去像规则写错，实测就骗过一次。
  //   故这里把错误信息一并回传，由 Python 侧打印。
  try { out = evalWithReturn(SRC); } catch (e2) {
    ERR = String(e2 && e2.message || e2);
    out = null;
  }
}
if (typeof out === 'undefined' || out === null) out = '';
process.stdout.write(JSON.stringify({out: out, log: LOG, err: ERR}));
''' % (sub_json, json.dumps(charset or 'utf-8'), json.dumps(base_url), bind_js, json.dumps(js_body))


def run(rule, base_url, subrules=None, binds=None, charset=None):
    """执行 @js: 规则。

    ★ 不再用 Python 去猜「哪一段是结尾表达式」——JS 的字符串、正则、模板串
      都能骗过朴素扫描（`replace(/[?&]$/,'')` 里的 `''` 就骗过一次）。
      改为把**整段规则原样**交给 node：用 new Function 逐句执行，并在
      `catch` 中回退到「把最后一行当表达式求值」，与 Rhino 取末值语义对齐。

    ★ 2026-10-26 改：走常驻 node worker（js_worker.py）。此前每条规则都 spawn
      一次 node，实测冷启动 203 ms；目录 1001 章逐条求值约需 200 秒，必然超时。
      常驻后单条约 0.6 ms。worker 不可用时自动退回一次性调用。
    """
    from js_worker import shared_worker
    out, log = shared_worker().eval(rule, base_url, subrules, binds, charset)
    return out, log or []


if __name__ == '__main__':
    cfgs = json.load(open(sys.argv[1], encoding='utf-8'))
    base = sys.argv[2]
    subs = json.load(open(sys.argv[3], encoding='utf-8')) if len(sys.argv) > 3 else {}
    for key, rule in cfgs.items():
        print('=== %s ===' % key)
        out, log = run(rule, base, subs)
        print('  java.ajax 请求:')
        for u in log:
            print('    ', u)
        if out is None:
            print('  执行失败')
            continue
        s = str(out)
        if '\n' in s:
            lines = [x for x in s.split('\n') if x.strip()]
            print('  输出 %d 行，首: %s' % (len(lines), lines[0][:60] if lines else ''))
            print('  末: %s' % (lines[-1][:60] if lines else ''))
        else:
            print('  输出: %r' % s[:200])
