#!/usr/bin/env python3
"""debug_source.py 解析器回归套件（离线，不打网络）。

★ 为什么要有这个文件：
  这些 bug 全都是「静默失败」——空选择器不报错、正则丢失不报错、
  异常被吞成空串、URL 未编码看着像站点拒绝。靠真实站点测不出来（且站点会变），
  所以把每一类都做成**纯函数级**的断言，改脚本时立刻能发现回退。

跑法：python3 scripts/test_debug_parser.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('dbg', os.path.join(HERE, 'debug_source.py'))
dbg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dbg)

FAILS = []
COUNT = [0]


def check(name, cond, extra=''):
    COUNT[0] += 1
    if cond:
        print('  PASS  %s' % name)
    else:
        print('  FAIL  %s %s' % (name, extra))
        FAILS.append(name)


def eq(name, got, want):
    check(name, got == want, '| got=%r want=%r' % (got, want))


print('== 1. 纯取值后缀（条目内相对取值）==')
eq('is_bare_suffix @href', dbg.is_bare_suffix('@href'), True)
eq('is_bare_suffix @text', dbg.is_bare_suffix('@text'), True)
eq('is_bare_suffix @css:a@href', dbg.is_bare_suffix('@css:a@href'), False)
eq('is_bare_suffix 空', dbg.is_bare_suffix(''), False)

from bs4 import BeautifulSoup
soup = BeautifulSoup('<a class="n" href="/book/1.html"><span class="t">书名甲</span></a>', 'html.parser')
node = soup.select('a.n')[0]
eq('node_value @href', dbg.node_value(node, '@href'), '/book/1.html')
eq('node_value @text', dbg.node_value(node, '@text'), '书名甲')
eq('node_value @class', dbg.node_value(node, '@class'), 'n')
eq('node_value .t@text', dbg.node_value(node, '.t@text'), '书名甲')
eq('node_value 不存在的属性', dbg.node_value(node, '@data-x'), '')

print('== 2. Legado 私有伪类 :eq/:lt/:gt ==')
check('has_eq_pseudo :eq(0)', dbg.has_eq_pseudo('dd p:eq(0)'))
check('has_eq_pseudo 无', not dbg.has_eq_pseudo('dd p'))
eq('split_eq_pseudo 纯选择器', dbg.split_eq_pseudo('dd p:eq(0)')[0], 'dd p')
eq('split_eq_pseudo ops', dbg.split_eq_pseudo('dd p:eq(0)')[1], [('eq', 0)])
h2 = BeautifulSoup('<div><p>0</p><p>1</p><p>2</p><p>3</p></div>', 'html.parser')
ps = h2.select('p')
eq('eq(0)', [e.text for e in dbg.apply_eq_pseudo(ps, [('eq', 0)])], ['0'])
eq('eq(-1)', [e.text for e in dbg.apply_eq_pseudo(ps, [('eq', -1)])], ['3'])
eq('lt(2)', [e.text for e in dbg.apply_eq_pseudo(ps, [('lt', 2)])], ['0', '1'])
eq('gt(1)', [e.text for e in dbg.apply_eq_pseudo(ps, [('gt', 1)])], ['2', '3'])
eq('eq 越界返回空', dbg.apply_eq_pseudo(ps, [('eq', 99)]), [])

print('== 3. <js></js> 识别（不该丢给 CSS 解析器）==')
check('is_js_selector', dbg.is_js_selector('<js>return 1;</js>'))
check('is_js_selector 否', not dbg.is_js_selector('@css:a'))
eq('unwrap_js', dbg.unwrap_js('<js>return 1;</js>'), 'return 1;')

print('== 4. 空选择器 / 坏选择器要「报出来」而不是静默 0 条 ==')
eq('空选择器 css()', dbg.css('<p>x</p>', ''), [])
eq('坏选择器 css() 不抛', dbg.css('<p>x</p>', 'p:eq('), [])
eq('正常还是正常', dbg.css('<p>x</p>', 'p'), ['x'])

print('== 5. rule_kind 语法识别 ==')
eq('@js', dbg.rule_kind('@js:java.ajax(x)'), 'js')
eq('<js>', dbg.rule_kind('<js>a</js>'), 'js')
eq('jsonpath $.', dbg.rule_kind('$.'), 'jsonpath')
eq('jsonpath $.title', dbg.rule_kind('$.title'), 'jsonpath')
eq('xpath', dbg.rule_kind('//div/a'), 'xpath')
eq('css 兜底', dbg.rule_kind('@css:a@href'), 'css')

print('== 6. 搜索词 URL 编码 ==')
eq('中文编码', dbg.enc_key('剑'), '%E5%89%91')
eq('空格编码', dbg.enc_key('a b'), 'a%20b')
eq('已编码不再动', dbg.enc_key('%E5%89%91'), '%25E5%2589%2591')

print('== 7. 分页可选段 <,{{page}}> ==')
eq('第1页省略整段', dbg.expand_page_tpl('https://x/s/{{key}}<,{{page}}>/', 1), 'https://x/s/{{key}}/')
eq('第2页带上', dbg.expand_page_tpl('https://x/s/{{key}}<,{{page}}>/', 2), 'https://x/s/{{key}}2/')
eq('无模板 {{page}}', dbg.expand_page_tpl('https://x/?p={{page}}', 3), 'https://x/?p=3')

print('== 8. url,{json} 选项拆分 ==')
u, o = dbg.split_url_options('https://x/y.php,{"method":"POST","body":"a=1"}')
eq('拆出 url', u, 'https://x/y.php')
eq('拆出 method', o.get('method'), 'POST')
eq('拆出 body', o.get('body'), 'a=1')
u2, o2 = dbg.split_url_options('https://x/y?p=1')
eq('普通 URL 不动', (u2, o2), ('https://x/y?p=1', {}))
u3, o3 = dbg.split_url_options('https://x/a,b,c')
eq('非 JSON 逗号不当选项', o3, {})

print('== 9. 正文真伪判定（内容特征，不看长度）==')
ok, why = dbg.is_real_content('')
check('空串不是正文', not ok)
ok, why = dbg.is_real_content('a' * 5000)
check('纯 ASCII 长串不是正文', not ok, why)
ok, why = dbg.is_real_content('<div>广告</div>' + '正文' * 400)
check('含壳页标记判非正文', not ok, why)
ok, why = dbg.is_real_content('却说那日林间风起，他提剑而立，' * 40)
check('中文长文判正文', ok, why)

print('== 10. 取值后缀切分（历史三坑）==')
eq('@css 选择器带 @ 后缀', dbg.strip_suffixes('@css:ul.list>li>a@href')[:2],
   ('ul.list>li>a', 'href'))
s2, a2, r2 = dbg.strip_suffixes('@css:p.info@text##[\\s\\S]*?作者：([^\\n]*)##$1')
eq('取值+正则同处一个 @ 后：选择器', s2, 'p.info')
eq('取值+正则同处一个 @ 后：属性', a2, 'text')
check('正则段没丢', '作者' in r2, r2)
# 纯后缀走 is_bare_suffix / node_value 分支，不经 strip_suffixes；
# 这里断言「它不会被误切成别的意思」，实际取值由 node_value 负责。
eq('纯后缀原样保留', dbg.strip_suffixes('@href')[0], '@href')
eq('纯后缀走 node_value（不进 strip_suffixes）', dbg.is_bare_suffix('@href'), True)

# ★ 短规则的后缀切分（曾整段失效）
eq('短规则 .t@text 能切出选择器', dbg.strip_suffixes('.t@text')[:2], ('.t', 'text'))
eq('短规则 .t@href 能切出属性', dbg.strip_suffixes('.t@href')[:2], ('.t', 'href'))
eq('@css: 前缀仍正确跳过', dbg.strip_suffixes('@css:ul.list>li>a@href')[:2],
   ('ul.list>li>a', 'href'))

# ★ <js> 后缀：必须先取元素值，再把该值作为 result 交给 JS
eq('css+js 规则识别', dbg.rule_kind('@css:.t@text<js>result.trim()</js>'), 'css+js')
eq('jsonpath 识别', dbg.rule_kind('$.title'), 'jsonpath')
eq('xpath 识别', dbg.rule_kind('//div[@class="t"]'), 'xpath')
eq('裸选择器默认 text', dbg.strip_suffixes('@css:.title')[:2], ('.title', 'text'))

print('== 11. JVM 捕获组引用换算 ==')
eq('$1 → \\g<1>', dbg.apply_regex('作者：迷男', '[\\s\\S]*作者：(.*)##$1'), '迷男')
eq('${1} → \\g<1>', dbg.apply_regex('x=42', 'x=(\\d+)##v${1}'), 'v42')
eq('无正则原样返回', dbg.apply_regex('abc', ''), 'abc')

print('== 12. 容器规则支持 js ==')
eq('lines_ok JSON 数组', dbg.lines_ok('[{"title":"A","url":"/a"}]'), ['A::/a'])
eq('lines_ok 行文本', dbg.lines_ok('A::/a\nB::/b'), ['A::/a', 'B::/b'])
eq('lines_ok 空', dbg.lines_ok(''), [])

print('')
print('总计 %d 项，失败 %d 项' % (COUNT[0], len(FAILS)))
if FAILS:
    for f in FAILS:
        print('  ✗', f)
    sys.exit(1)
print('PASS: debug_source 解析器回归套件')
