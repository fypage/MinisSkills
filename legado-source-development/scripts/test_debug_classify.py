#!/usr/bin/env python3
"""debug_source.py 失败分型（errorCode）回归测试（2026-10-26）。

只测新加的诊断函数，不跑网络：
  classify_container / classify_content / code_of
"""
import io
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import debug_source as D  # noqa: E402


def cap(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **kw)
    return r, buf.getvalue()


def main():
    n = 0

    # ---- classify_container ----
    r, out = cap(D.classify_container, 'toc', 'div.list > li', [])
    assert r == 'toc.SELECTOR_EMPTY', (r, out)
    n += 1

    r, out = cap(D.classify_container, 'toc', 'div.list > li', ['a', 'b'])
    assert r is None, (r, out)
    n += 1

    r, out = cap(D.classify_container, 'toc', '//li', [])
    assert r == 'toc.HARNESS_UNSUPPORTED', (r, out)
    assert '未评估' in out
    n += 1

    r, out = cap(D.classify_container, 'search', '@js:java.ajax(u)', [])
    assert r == 'search.HARNESS_UNSUPPORTED', (r, out)
    n += 1

    # ---- classify_content ----
    cases = [
        ('', None, 'content.CONTENT_EMPTY'),
        ('短', None, 'content.CONTENT_TOO_SHORT'),
        ('x' * 300, 404, 'content.HTTP_BLOCKED'),
        ('<html>Just a moment...</html>' + '正' * 200, 200, 'content.CONTENT_IS_CAPTCHA_PAGE'),
        ('请登录后继续阅读' + '正' * 200, 200, 'content.CONTENT_IS_LOGIN_PAGE'),
        ('VIP会员专享，购买本章' , 200, 'content.CONTENT_IS_VIP_LOCK_PAGE'),
    ]
    for text, code, expect in cases:
        r, out = cap(D.classify_content, text, code)
        assert r == expect, (text[:20], code, expect, r)
        n += 1

    # 空壳：中文极少 + 有 script
    shell = '<html><body><div id="app"></div><script>render()</script></body></html>' + 'x' * 150
    r, out = cap(D.classify_content, shell, 200)
    assert r == 'content.CONTENT_IS_CSR_SHELL', (r, out)
    n += 1

    # 正常正文不应命中任何分型
    ok = '第1章 开始\n' + '这是一段正文内容，用来测试分型不会误判。' * 20
    r, out = cap(D.classify_content, ok, 200)
    assert r is None, (r, out)
    n += 1

    # ---- code_of 输出格式 ----
    r, out = cap(D.code_of, 'toc', 'TOC_EMPTY', 'ruleToc.chapterName', '容器命中但名称为空')
    assert r == 'toc.TOC_EMPTY'
    assert '✗' in out and 'ruleToc.chapterName' in out and '容器命中但名称为空' in out
    n += 1

    print('PASS: 失败分型回归（%d 项）' % n)


if __name__ == '__main__':
    main()
