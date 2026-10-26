#!/usr/bin/env python3
"""rule_exec.py 的 :eq() 支持与 urljoin 修复回归（2026-10-26）。

背景：
  · `:eq(n)` 是目标客户端自有扩展（55kxs、素书卷、速读谷均在用），
    但 cssselect2 不认，会抛 Unknown pseudo-class → 把合法规则误判成源缺陷。
  · `eval_field` 里 `... and ... or "Url" in rule` 的 and/or 优先级错误，
    只要字段名含 Url 就无条件 urljoin，重复拼接基址。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE / 'rule_exec.py'

HTML = """
<html><body>
<div class="itemtxt">
  <h3><a href="/a/1.html">书名一</a></h3>
  <p><span>连载中</span><span>历史小说</span></p>
</div>
<div class="itemtxt">
  <h3><a href="/a/2.html">书名二</a></h3>
  <p><span>已完结</span><span>玄幻小说</span></p>
</div>
<div class="itemtxt">
  <h3><a href="/a/3.html">书名三</a></h3>
  <p><span>连载中</span><span>仙侠小说</span></p>
</div>
</body></html>
"""


def run_source(rules, html=HTML, base='https://x.test/'):
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        src = d / 's.json'
        src.write_text(json.dumps({'bookSourceUrl': 'https://x.test', 'bookSourceName': 'T',
                                   'ruleBookInfo': rules}, ensure_ascii=False), encoding='utf-8')
        resp = d / 'r.html'
        resp.write_text(html, encoding='utf-8')
        q = subprocess.run([sys.executable, str(R), str(src), 'ruleBookInfo', str(resp), base],
                           capture_output=True, text=True, timeout=120)
        if q.returncode != 0:
            return None, q.stderr
        return json.loads(q.stdout), ''


def main():
    n = 0

    # 1. :eq(1) 取第二个 span
    rep, err = run_source({'kind': '@css:.itemtxt p span:eq(1)@text'})
    assert rep is not None, err[-400:]
    assert rep['errors'] == 0, rep
    assert rep['rows'][0]['kind'] == '历史小说', rep['rows'][0]
    n += 1

    # 2. :eq(0) 取第一个
    rep, _ = run_source({'kind': '@css:.itemtxt p span:eq(0)@text'})
    assert rep['rows'][0]['kind'] == '连载中', rep['rows'][0]
    n += 1

    # 3. :eq(-1) 负数取末项（整页候选 6 个 span，末项为最后一块的仙侠小说）
    rep, _ = run_source({'kind': '@css:.itemtxt p span:eq(-1)@text'})
    assert rep['rows'][0]['kind'] == '仙侠小说', rep['rows'][0]
    n += 1

    # 4. :eq 与 :contains 组合：不报错即可（具体索引语义与真机有待复核）
    rep, _ = run_source({'kind': '@css:.itemtxt p:contains(连载中) span:eq(1)@text'})
    assert rep['errors'] == 0, rep
    assert '历史小说' in rep['rows'][0]['kind'], rep['rows'][0]
    n += 1

    # 5. :eq 越界应返回空，不抛错
    rep, _ = run_source({'kind': '@css:.itemtxt p span:eq(99)@text'})
    assert rep['errors'] == 0, rep
    assert rep['rows'][0]['kind'] == '', rep['rows'][0]
    n += 1

    # 6. urljoin：相对地址逐个补全，多值按 Legado 语义用 \n 连接
    rep, _ = run_source({'coverUrl': '@css:.itemtxt h3 a@href'})
    v = rep['rows'][0]['coverUrl']
    parts = v.split('\n')
    assert parts == ['https://x.test/a/1.html', 'https://x.test/a/2.html',
                     'https://x.test/a/3.html'], v
    n += 1

    # 7. urljoin：已是绝对地址不应二次拼接
    abs_html = '<html><body><div class="itemtxt"><h3><a href="https://cdn.test/x.jpg">t</a></h3></div></body></html>'
    rep, _ = run_source({'coverUrl': '@css:.itemtxt h3 a@href'}, html=abs_html)
    v = rep['rows'][0]['coverUrl']
    assert v == 'https://cdn.test/x.jpg', v
    n += 1

    # 8. urljoin：非 URL 字段不得被拼接（旧 bug 会把含 Url 的字段全拼上基址）
    rep, _ = run_source({'tocUrl': '{{baseUrl}}'})
    v = rep['rows'][0]['tocUrl']
    assert v == '{{baseUrl}}', ('{{baseUrl}} 应原样返回', v)
    n += 1

    print('PASS: rule_exec 扩展回归（%d 项）' % n)


if __name__ == '__main__':
    main()
