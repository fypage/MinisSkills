#!/usr/bin/env python3
"""validate_source.py 新增静态铁律的回归测试（2026-10-26）。

覆盖五类借自上游 official-rule-pack.json 的检查：
  1. ;post= / ;get= 写法
  2. jQuery 扩展伪类
  3. @css 多 action 链
  4. ruleBookInfo.summary 错名
  5. User-Agent 完整性

用法：python3 scripts/test_validator_lint.py
"""
import json
import subprocess
import tempfile
from pathlib import Path

V = Path(__file__).with_name('validate_source.py')


def run(*a):
    return subprocess.run(['python3', str(V), *map(str, a)], text=True, capture_output=True)


def write(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False), encoding='utf-8')


def base(**kw):
    d = {"bookSourceUrl": "https://x.test", "bookSourceName": "书源", "bookSourceType": 0}
    d.update(kw)
    return d


def one(d, path):
    write(path, d)
    return run('--json', path)


def main():
    cases = []
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # ---- 1. ;post= / ;get= ----
        for token in (';post=', ';get='):
            p = d / 'opt.json'
            q = one(base(searchUrl="/s" + token + "a=b"), p)
            r = json.loads(q.stdout)[0]
            assert r['errors'] == 1, (token, r)
            assert 'JSON 选项' in q.stdout, q.stdout
            cases.append(token)

        # ---- 2. jQuery 伪类 ----
        for sel in (':has(', ':visible(', ':hidden('):
            p = d / 'jq.json'
            q = one(base(ruleBookInfo={"name": "@css:div" + sel + "x)@text"}), p)
            r = json.loads(q.stdout)[0]
            assert r['errors'] >= 1, (sel, r)
            assert 'jQuery' in q.stdout, (sel, q.stdout)
            cases.append(sel)

        # `:eq(n)` 是目标客户端自有扩展（真机已在用），不得误报
        p = d / 'eq.json'
        q = one(base(ruleBookInfo={"wordCount": "div.p span:eq(1)@text"}), p)
        assert json.loads(q.stdout)[0]['errors'] == 0, q.stdout
        cases.append('eq-allowed')

        # `:contains(文本)` 在参考执行器（soupsieve）可用，且成品源大量在用；不得报错
        p = d / 'contains.json'
        q = one(base(ruleBookInfo={"author": "@css:div.info>p:contains(作者)@text"}), p)
        assert json.loads(q.stdout)[0]['errors'] == 0, q.stdout
        cases.append('contains-allowed')

        # 豁免：nextContentUrl / nextTocUrl 里的 :contains 用于排除导航文字，不判错
        p = d / 'jq-exempt.json'
        q = one(base(ruleContent={"nextContentUrl": "@css:a:not(:contains(下一章))@href"}), p)
        assert json.loads(q.stdout)[0]['errors'] == 0, q.stdout
        cases.append('jquery-exempt')

        # ---- 3. @css 多 action 链 ----
        p = d / 'chain-bad.json'
        q = one(base(ruleBookInfo={"intro": "@css:.a@text@js:result.replace('x','y');"}), p)
        assert json.loads(q.stdout)[0]['errors'] == 1, q.stdout
        assert '多 action' in q.stdout, q.stdout
        cases.append('css-chain-bad')

        # 正常单 action + @js 不误报
        p = d / 'chain-ok.json'
        q = one(base(ruleBookInfo={"intro": "@css:.a@text"}), p)
        assert json.loads(q.stdout)[0]['errors'] == 0, q.stdout
        cases.append('css-chain-ok')

        # ---- 4. ruleBookInfo.summary ----
        p = d / 'summary.json'
        q = one(base(ruleBookInfo={"summary": "@css:.intro@text"}), p)
        assert json.loads(q.stdout)[0]['errors'] == 1, q.stdout
        assert 'intro' in q.stdout, q.stdout
        cases.append('summary')

        # 正确写法 intro 不报错
        p = d / 'intro.json'
        q = one(base(ruleBookInfo={"intro": "@css:.intro@text"}), p)
        assert json.loads(q.stdout)[0]['errors'] == 0, q.stdout
        cases.append('intro-ok')

        # ---- 5. UA 完整性 ----
        ua_bad = ('{"User-Agent":"Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/91.0.4472.120"}')
        p = d / 'ua-bad.json'
        q = one(base(header=ua_bad), p)
        r = json.loads(q.stdout)[0]
        assert r['errors'] == 0 and r['warnings'] >= 1, q.stdout
        assert '截断' in q.stdout, q.stdout
        assert run('--strict', p).returncode == 2, 'UA 完整性应为 warning，strict 下返回 2'
        cases.append('ua-truncated')

        # 无引擎标识的残段 UA，应命中「脚本客户端」分支
        ua_scriptlike = '{"User-Agent":"Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36"}'
        p = d / 'ua-scriptlike.json'
        q = one(base(header=ua_scriptlike), p)
        assert '脚本客户端' in q.stdout, q.stdout
        cases.append('ua-no-engine')

        ua_ok = ('{"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                 'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}')
        p = d / 'ua-ok.json'
        q = one(base(header=ua_ok), p)
        assert json.loads(q.stdout)[0]['warnings'] == 0, q.stdout
        cases.append('ua-full')

        ua_script = '{"User-Agent":"curl/8.5.0"}'
        p = d / 'ua-script.json'
        q = one(base(header=ua_script), p)
        assert json.loads(q.stdout)[0]['warnings'] == 1, q.stdout
        assert '脚本客户端' in q.stdout, q.stdout
        cases.append('ua-script')

        # 含模板的 header 跳过 UA 检查（动态值留给真机）
        p = d / 'ua-tpl.json'
        q = one(base(header='{"User-Agent":"{{$.ua}}"}'), p)
        assert json.loads(q.stdout)[0]['warnings'] == 0, q.stdout
        cases.append('ua-template-skip')

    print('PASS: validator lint suite (%d cases)' % len(cases))


if __name__ == '__main__':
    main()
