#!/usr/bin/env python3
import json,subprocess,tempfile
from pathlib import Path
V=Path(__file__).with_name('validate_source.py')
def run(*a):return subprocess.run(['python3',str(V),*map(str,a)],text=True,capture_output=True)
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False),encoding='utf-8')
def main():
 with tempfile.TemporaryDirectory() as d:
  d=Path(d)
  book=d/'book.json';write(book,{"bookSourceUrl":"https://x.test","bookSourceName":"书源","bookSourceType":0,"searchUrl":"/s/{{key}}","ruleSearch":{"bookList":"@css:.item","name":"@css:a@text","bookUrl":"@css:a@href"}})
  assert run(book).returncode==0,run(book).stdout
  rss=d/'rss.json';write(rss,{"sourceUrl":"https://x.test/rss","sourceName":"RSS"})
  assert run(rss).returncode==0,run(rss).stdout
  rssbad=d/'rssbad.json';write(rssbad,{"sourceUrl":"https://x.test/r","sourceName":"R","ruleArticles":"@css:article"})
  q=run(rssbad);assert q.returncode==1 and 'ruleTitle' in q.stdout and 'ruleLink' in q.stdout,q.stdout
  xp=d/'xp.json';write(xp,{"bookSourceUrl":"https://x.test","bookSourceName":"XPath","bookSourceType":0,"ruleToc":{"nextTocUrl":"@XPath://a[contains(normalize-space(.),'下一页')]/@href"}})
  q=run(xp);assert q.returncode==1 and 'normalize-space' in q.stdout,q.stdout
  csshead=d/'csshead.json';write(csshead,{"bookSourceUrl":"https://x.test","bookSourceName":"CSS头","bookSourceType":0,"ruleBookInfo":{"kind":"@css:.a@text&&@css:.b@text"}})
  q=run(csshead);assert q.returncode==1 and '只在整条规则开头写一次' in q.stdout,q.stdout
  selectbad=d/'selectbad.json';write(selectbad,{"bookSourceUrl":"https://x.test","bookSourceName":"下拉分页","ruleToc":{"nextTocUrl":"select[name='p']@value"}})
  q=run(selectbad);assert q.returncode==0 and 'option@value' in q.stdout,q.stdout
  assert run('--strict',selectbad).returncode==2
  selectwarn=d/'selectwarn.json';write(selectwarn,{"bookSourceUrl":"https://x.test","bookSourceName":"下拉警告","ruleToc":{"nextTocUrl":"select option:not([selected])@value"}})
  q=run(selectwarn);assert q.returncode==0 and '前页和后页' in q.stdout,q.stdout
  nextchapter=d/'nextchapter.json';write(nextchapter,{"bookSourceUrl":"https://x.test","bookSourceName":"正文串章","ruleContent":{"nextContentUrl":"text.下一章@href"}})
  q=run(nextchapter);assert q.returncode==1 and '只用于同一章节续页' in q.stdout,q.stdout
  liststring=d/'liststring.json';write(liststring,{"bookSourceUrl":"https://x.test","bookSourceName":"列表字符串","ruleToc":{"nextTocUrl":"@js:var pages=[];JSON.stringify(pages);"}})
  q=run(liststring);assert q.returncode==0 and '直接返回数组' in q.stdout,q.stdout
  assert run('--strict',liststring).returncode==2
  nested=d/'nested.json';write(nested,{"bookSourceUrl":"https://x.test","bookSourceName":"嵌套","bookSourceType":0,"searchUrl":"/s, {\"method\":\"POST\",\"headers\":{\"Referer\":\"https://x.test\"},\"body\":\"q={{key}}\"}"})
  assert run(nested).returncode==0,run(nested).stdout
  dup=d/'dup.json';dup.write_text('{"bookSourceUrl":"a","bookSourceUrl":"b","bookSourceName":"D"}',encoding='utf-8')
  q=run(dup);assert q.returncode==1 and '重复 JSON 键' in q.stdout,q.stdout
  boolean=d/'bool.json';write(boolean,{"bookSourceUrl":"x","bookSourceName":"B","bookSourceType":True})
  assert run(boolean).returncode==1,run(boolean).stdout
  cases=[
   ('ruleContent','nextContentUrl','@css:a:not(:contains(下一章))@href',0,1),
   ('ruleContent','nextContentUrl','@XPath://a[not(contains(text(),"下一章"))]/@href',0,1),
   ('ruleContent','nextContentUrl','text.下一章@href@js:result="";',0,1),
   ('ruleContent','nextContentUrl','@js:var s="下一章"; "";',0,0),
   ('ruleContent','nextContentUrl','@css:a.next-page@href',0,0),
   ('ruleToc','nextTocUrl','@css:select#pages.pager[name="p"]@value',0,1),
   ('ruleToc','nextTocUrl','tag.select@value',0,1),
   ('ruleToc','nextTocUrl','@css:select option@value',0,0),
   ('ruleToc','nextTocUrl','@css:.select@value',0,0),
   ('ruleToc','nextTocUrl','@css:[data-label="select@value"]@href',0,0),
   ('ruleToc','nextTocUrl','@js:var x="select@value"; [x];',0,0),
   ('ruleToc','nextTocUrl','@js:var body=JSON.stringify({page:2}); ["/p2"];',0,1),
   ('ruleToc','nextTocUrl','<js>JSON.stringify(["/p2"])</js>',0,1),
   ('ruleToc','nextTocUrl','@js:["/p2","/p3"];',0,0),
  ]
  for i,(group,field,value,errors,warnings) in enumerate(cases):
   p=d/f'case-{i}.json';write(p,{'bookSourceUrl':'x','bookSourceName':'Case',group:{field:value}})
   q=run('--json',p);r=json.loads(q.stdout)[0]
   assert (r['errors'],r['warnings'])==(errors,warnings),(value,r)
   assert run('--strict',p).returncode==(1 if errors else 2 if warnings else 0),value
  for kind,url,name in [('book','bookSourceUrl','bookSourceName'),('rss','sourceUrl','sourceName')]:
   for field in (url,name):
    for bad in ([],{},['x'],{'x':1},42,True,None):
     p=d/'invalid-type.json';x={url:'x',name:'Name'};x[field]=bad;write(p,x)
     q=run('--json',p);assert q.returncode==1 and not q.stderr,(x,q.stdout,q.stderr)
     assert json.loads(q.stdout)[0]['errors']>=1
 print('PASS: validator v3 regression suite (14 pagination cases + 28 invalid-type cases)')
if __name__=='__main__':main()
