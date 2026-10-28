// Legado @js 末值求值器（Rhino 语义近似）
// 用法: node js_eval.js <rule.json> <baseUrl>
// rule.json: {"rule":"@js:..." 或 "<js>...</js>"}
'use strict';
const fs = require('fs');
const { execSync } = require('child_process');

function scriptOf(rule) {
  let r = String(rule || '').trim();
  if (r.startsWith('<js>') && r.endsWith('</js>')) r = r.slice(4, -5);
  else if (r.startsWith('@js:')) r = r.slice(4);
  return r;
}

function stripTrailing(src) {
  return String(src).replace(/[\s;]+$/, '');
}

// 判断位置 i 的 `/` 是否开始一个正则字面量（而不是除号/注释）。
// 规则：向前找第一个非空白字符，若它是操作符、开括号、逗号、分号、冒号或不存在，
// 则此处 `/` 只能起正则。够用且不会把 `a / b` 误判 —— 那里前一个字符是操作数。
const REGEX_PREV = '(,=:[!&|?{};+-*%<>~^';
function regexAllowed(src, i) {
  for (let j = i - 1; j >= 0; j--) {
    const c = src[j];
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') continue;
    if (REGEX_PREV.indexOf(c) >= 0) return true;
    if (/[A-Za-z0-9_$]/.test(c)) {
      // 关键字 return/typeof/case/in/of/new/delete/void/instanceof 之后也可起正则
      const w = src.slice(Math.max(0, j - 10), j + 1).match(/([A-Za-z_$][\w$]*)$/);
      return !!w && /^(return|typeof|case|in|of|new|delete|void|instanceof)$/.test(w[1]);
    }
    return false;
  }
  return true;
}

// 找出所有「顶层语句边界」候选：depth 0 处的 ';' 之后、或闭合顶层 '}' 之后
function cuts(src) {
  const out = [];
  let depth = 0, str = null;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (str) {
      if (ch === '\\') { i++; continue; }
      if (ch === str) str = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') { str = ch; continue; }
    // ★ 2026-10-25 修：正则字面量里的 `//`（如 /^(.*\/list_)(\d+)\.html$/）曾被误判成行注释，
    //   整行被跳过 → 切点全错 → 末值恒空串，表现为「规则写错」。判断依据：
    //   上一个有效字符是「操作符或行首」时，`/` 起的是正则而非注释。
    if (ch === '/' && src[i + 1] === '/' && !regexAllowed(src, i)) { const j = src.indexOf('\n', i); i = j < 0 ? src.length : j; continue; }
    if (ch === '/' && src[i + 1] === '*') { const j = src.indexOf('*/', i); i = j < 0 ? src.length : j + 1; continue; }
    if ('([{'.indexOf(ch) >= 0) depth++;
    else if (')]}'.indexOf(ch) >= 0) { depth = Math.max(0, depth - 1); if (depth === 0) out.push(i + 1); }
    else if (ch === ';' && depth === 0) out.push(i + 1);
  }
  out.push(0);
  return out;
}

function evalRule(src, scope) {
  const s = stripTrailing(src);
  // 1) 先把「除末句外」的部分当语句执行，末句当表达式求值
  const cs = cuts(s);
  for (let c = cs.length - 1; c >= 0; c--) {
    const head = s.slice(0, cs[c]);
    const tail = s.slice(cs[c]).trim();
    if (!tail) continue;
    if (/^(var|let|const|if|for|while|do|return|function|switch|try|throw|class|break|continue)\b/.test(tail)) continue;
    try {
      new Function(head);
      new Function('return (' + tail + ');');
    } catch (e) { continue; }
    return new Function('__s', '__j', 'with(__s){' + head + '\nreturn (' + tail + ');}')(scope, scope.java);
  }
  // 2) 退化：整段当语句，显式 return 的规则（可能含 return）
  try {
    return new Function('__s', '__j', 'with(__s){' + s + '}')(scope, scope.java);
  } catch (e) {
    return undefined;
  }
}

// 2026-10-26：抽出 evaluate()，使本文件既能被 CLI 执行，也能被常驻 worker require。
// 原因：目录 1001 章逐条 spawn node，单次冷启动 203 ms → 约 200 秒超时。
function evaluate(rule, baseUrl, subrules, bindsIn) {
  const cfg = { rule: rule, subrules: subrules || {}, binds: bindsIn || {} };
  const logs = [];
  const scope = {};
  const binds = cfg.binds || {};
  for (const k of Object.keys(binds)) scope[k] = binds[k];
  if (baseUrl) scope.baseUrl = baseUrl;
  if (scope.result === undefined) scope.result = '';
  if (scope.src === undefined) scope.src = scope.result;
  scope.java = {
    ajax(u) {
      logs.push(String(u));
      try {
        // ★ 2026-10-27 修：必须 --compressed（站点可能无视 Accept-Encoding 直接回 gzip），
        //   且按响应头 charset 解码。真机 OkHttp 自动解压；Rhino 的 String 是 UTF-16，
        //   GBK 站点若按 utf8 解会整段乱码 → 看着像规则错。默认 utf-8，可用 cfg.charset 覆盖。
        const enc = (cfg && cfg.charset) || 'utf-8';
        return execSync('curl -s -L --compressed --max-time 30 -A "curl/8.5.0" ' + JSON.stringify(String(u)),
          { maxBuffer: 64 * 1024 * 1024 }).toString(enc);
      } catch (e) { return ''; }
    },
    getString(rule) { return (cfg.subrules && cfg.subrules[rule] !== undefined) ? cfg.subrules[rule] : ''; },
    encodeURI(s) { return encodeURIComponent(String(s)); },
    log(x) { logs.push(String(x)); },
    put() {}, get() { return null; },
  };
  let out = '';
  try {
    const v = evalRule(scriptOf(cfg.rule), scope);
    out = v === undefined || v === null ? '' : String(v);
  } catch (e) {
    return { out: '', log: logs, err: String(e && (e.message || e)) };
  }
  return { out: out, log: logs, err: '' };
}

function main() {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const baseUrl = process.argv[3] || '';
  const r = evaluate(cfg.rule, baseUrl, cfg.subrules, cfg.binds);
  process.stdout.write(JSON.stringify({ out: r.out, logs: r.log, err: r.err }));
}

module.exports = { evaluate: evaluate };

if (require.main === module) main();
