#!/usr/bin/env python3
"""Legado 书源/RSS 静态校验器。静态通过不等于真机可用。"""
import argparse,json,re,sys
from pathlib import Path

# 字段表依据：目标 APK `io.legato.kazusa` dex 内 Room Schema 串 + MD3 上游 *Rule.kt
# 复核日期 2026-10-16。详见 references/md3-compat.md
BOOK_REQUIRED=("bookSourceUrl","bookSourceName")
RSS_REQUIRED=("sourceUrl","sourceName")
BOOK_RULES={
"ruleSearch":{"checkKeyWord","bookList","name","author","intro","kind","lastChapter","updateTime","bookUrl","coverUrl","wordCount"},
"ruleExplore":{"bookList","name","author","intro","kind","lastChapter","updateTime","bookUrl","coverUrl","wordCount"},
# 注意：真名是 init，不是 bookInfoInit。见 KNOWN_BAD_FIELDS。
"ruleBookInfo":{"init","name","author","intro","kind","lastChapter","updateTime","coverUrl","tocUrl","wordCount","canReName","downloadUrls","relatedBooks"},
"ruleToc":{"preUpdateJs","chapterList","chapterName","chapterUrl","formatJs","isVolume","isVip","isPay","updateTime","nextTocUrl"},
"ruleContent":{"content","subContent","title","nextContentUrl","webJs","sourceRegex","replaceRegex","imageStyle","imageDecode","payAction","callBackJs"},
"ruleReview":{"reviewUrl","avatarRule","contentRule","postTimeRule","reviewQuoteUrl","voteUpUrl","voteDownUrl","postReviewUrl","postQuoteUrl","deleteUrl"}}
RSS_RULE_FIELDS={"ruleArticles","ruleNextPage","ruleTitle","rulePubDate","ruleDescription","ruleImage","ruleLink","ruleContent"}

# 高置信度错名 → 正确名。命中即报 error（不是 warning）：写错会静默失效。
KNOWN_BAD_FIELDS={
"ruleBookInfo.bookInfoInit":"ruleBookInfo.init（详情预处理；写 bookInfoInit 会静默失效，空值无副作用故极易被漏过）",
"ruleBookInfo.ruleBookInfoInit":"ruleBookInfo.init",
}
# 教程笔误：把“列表下一页规则”写成 ruleArticles。真名 ruleNextPage。
# 更糟的是同名覆盖——直接改写列表规则本身，分页彻底失效且无报错。
RSS_BAD_FIELDS={
"ruleArticles_as_nextpage":"ruleNextPage（“列表下一页规则”真名；用 ruleArticles 会覆盖列表规则）",
}

def add(out,level,where,msg): out.append({"level":level,"where":where,"message":msg})
def load(path):
 dup=[]
 def hook(pairs):
  d={}
  for k,v in pairs:
   if k in d: dup.append(k)
   d[k]=v
  return d
 text=Path(path).read_text("utf-8-sig")
 return json.loads(text,object_pairs_hook=hook),dup

def kind_of(x):
 if not isinstance(x,dict): return None
 if "bookSourceUrl" in x or "bookSourceName" in x: return "book"
 if "sourceUrl" in x or "sourceName" in x: return "rss"
 return None

def url_option(text):
 """返回可静态解析的 URL 尾部选项；支持嵌套对象。"""
 if not isinstance(text,str): return None,None
 starts=[m.start()+1 for m in re.finditer(r",\s*(?=\{(?!\{))",text)]
 for pos in starts:
  candidate=text[pos:].strip()
  try:
   obj=json.loads(candidate)
   if isinstance(obj,dict): return obj,None
  except json.JSONDecodeError as e:
   last=e
 return (None,last if starts else None)

def check_rule_text(value,where,out,target):
 if not isinstance(value,str):
  add(out,"error",where,f"规则值应为字符串，实际为 {type(value).__name__}"); return
 plain=re.sub(r"<js>[\s\S]*?</js>","",value)
 # 2026-10-26 修：`@js:` 规则里相邻的 `}}`（如 `if(...){...}}` 收尾）曾被当成
 # 「空占位符 `{{ }}`」，误报「不配对」，逼得规则要写成 `} }` 才能过校验。
 # 现对 @js:/<js> 规则整段剔除（JS 里不存在 Legado 的 {{ }} 模板占位符）。
 if value.lstrip().startswith("@js:") or "<js>" in value:
  plain=re.sub(r"[\s\S]*","",plain)
 if plain.count("{{")!=plain.count("}}"): add(out,"error",where,"{{ }} 标记不配对")
 if value.count("<js>")!=value.count("</js>"): add(out,"error",where,"<js></js> 标签不配对；@js: 形态不能追加 </js>")
 if target=="md3" and re.search(r"(?:@xpath:|@XPath:|//)[\s\S]*\bnormalize-space\s*\(",value):
  add(out,"error",where,"目标 MD3 真机已确认不支持 XPath normalize-space()")
 if re.search(r"(?:&&|\|\||%%)\s*@css:",value,re.I):
  add(out,"error",where,"CSS 组合规则只在整条规则开头写一次 @css:；分支前重复会进入 Jsoup 选择器并解析失败")
 # —— 以下 5 类静态铁律，思路借自 Narylr350/book-source-creator-skill 的
 # references/official-rule-pack.json（官方教程来源），2026-10-26 适配。
 # 均为纯字符串判定，不需要执行引擎。
 if re.search(r";\s*(?:post|get)\s*=",value,re.I):
  add(out,"error",where,"POST/GET 请求选项应写在 URL 后的 JSON 选项（method/body/headers），不支持 ;post= 或 ;get=")
 if re.search(r":\s*(?:has|visible|hidden)\s*\(",value) and not where.endswith(("nextContentUrl","nextTocUrl")):
  add(out,"error",where,"疑似 jQuery 扩展伪类（:has/:visible/:hidden）。注意目标 MD3 的 Jsoup 基于 CSS 引擎，:contains() 类文本匹配是否生效须真机核实；标准 CSS 更稳妥")
 # 这里只做保守文本检查，不解析或执行 JS；动态规则交由目标引擎验证。
 selector=plain.split("@js:",1)[0].split("##",1)[0].strip()
 # @css 多 action 链：Legado 按「最后一个 @」切分取值，`@css:sel@text@js:...`
 # 会把 @text 当成选择器的一部分导致 Jsoup 解析失败。改用 `##$##` 或单 action。
 if re.match(r"@css:",value.strip(),re.I) and value.count("@")>2 and "@js:" in value:
  add(out,"error",where,"@css 多 action 链（如 @css:sel@text@js:…）会被「最后一个 @」切分规则误解析；取值用单一 @action，后处理改用 ##$##<js> 或 @js:")
 if where.endswith("nextTocUrl"):
  # 覆盖 CSS 模式头、Default tag.select、id/class 和属性；不匹配
  # select option@value、.select@value 或 [data-label='select@value']。
  if re.search(r"(?:^|@css:|tag\.|[\s>+~,(]|&&|\|\||%%)select(?:[.#][\w-]+|\[(?:[^\]\"']|\"[^\"]*\"|'[^']*')*\])*\s*@value\s*$",selector,re.I):
   add(out,"warning",where,"疑似读取 select@value；常规下拉分页 URL 在 option@value，须核对原始响应是否确有 select 自定义 value 属性")
  if re.search(r"option\s*:not\(\s*\[\s*selected\s*\]\s*\)",selector,re.I):
   add(out,"warning",where,"可能同时选中前页和后页；须核对上下文或后处理是否已限制为有序后续页列表")
  if re.search(r"JSON\s*\.\s*stringify\s*\(",value):
   add(out,"warning",where,"nextTocUrl 出现 JSON.stringify：若最终返回的是列表，应直接返回数组/List；请求 body、日志或中间序列化不等于错误，须核对返回类型")
 if where.endswith("nextContentUrl") and re.search(r"下一章|下章",selector):
  if re.fullmatch(r"text\.(?:下一章|下章)@href",value.strip()):
   add(out,"error",where,"nextContentUrl 直接选择下一章；它只用于同一章节续页")
  else:
   add(out,"warning",where,"nextContentUrl 含章节导航文字；可能用于 :not/not()/过滤排除，不据此判错；须验证结果仅为同一章节续页")
 opt,err=url_option(value)
 if err and not any(x in value for x in ("<js>","@js:")):
  add(out,"error",where,f"URL 尾部选项疑似非法 JSON：{err.msg}")
 if opt is not None and "body" in opt and not isinstance(opt["body"],str):
  add(out,"warning",where,"静态请求 body 不是字符串")

def check_ua(h,where,out):
 """UA 完整性（借自上游 webview-behavior-matrix / legado-source-behavior）。

 截断的 UA（缺 Chrome/版本号或 Safari/ 尾段）会被反爬系统判为非标准客户端。
 上游实测结论：UA 必须保留 `(KHTML, like Gecko) Chrome/<ver> Safari/<ver>` 完整性。
 只对「能静态解析成 JSON」的 header 生效；含模板/JS 的留给真机。
 """
 if not isinstance(h,str) or not h.strip().startswith("{"): return
 if any(k in h for k in ("{{","<js>","@js:")): return
 try: obj=json.loads(h)
 except (json.JSONDecodeError,ValueError): return
 if not isinstance(obj,dict): return
 ua=next((v for k,v in obj.items() if isinstance(k,str) and k.lower()=="user-agent"),None)
 if ua is None: return
 if not isinstance(ua,str):
  add(out,"error",where,"User-Agent 应为字符串"); return
 u=ua.strip()
 if not u: add(out,"error",where,"User-Agent 为空字符串"); return
 has_gecko="like Gecko" in u or "KHTML" in u
 has_chrome=re.search(r"Chrome/\d+",u)
 has_safari=re.search(r"Safari/\d+",u)
 if has_gecko and not (has_chrome and has_safari):
  add(out,"warning",where,"UA 疑似截断（有 KHTML/Gecko 却缺 Chrome/版本号或 Safari/ 尾段）；反爬常据此判为非浏览器客户端")
 elif has_chrome and not has_safari:
  add(out,"warning",where,"UA 疑似截断（有 Chrome/版本号但缺 Safari/ 尾段）；完整的 Chrome UA 以 `Safari/<ver>` 结尾")
 elif not has_gecko and not has_chrome:
  add(out,"warning",where,"UA 不含 Chrome/Safari 标识，形似脚本客户端；部分站点会直接拒绝")

def check_book(x,label,out,target):
 for f in BOOK_REQUIRED:
  if not isinstance(x.get(f),str) or not x[f].strip(): add(out,"error",label,f"缺少非空字符串字段 {f}")
 t=x.get("bookSourceType",0)
 if isinstance(t,bool) or not isinstance(t,int): add(out,"error",label+".bookSourceType","应为整数 0..4")
 elif t not in range(5): add(out,"error",label+".bookSourceType","应为 0..4")
 for f in ("enabled","enabledExplore","enabledCookieJar","eventListener","customButton"):
  if f in x and x[f] is not None and not isinstance(x[f],bool): add(out,"error",label+"."+f,"应为布尔值")
 for f in ("weight","customOrder","lastUpdateTime","respondTime"):
  if f in x and (isinstance(x[f],bool) or not isinstance(x[f],(int,float))): add(out,"error",label+"."+f,"应为数值")
 h=x.get("header")
 if isinstance(h,str) and h.strip().startswith("{") and not any(k in h for k in ("{{","<js>","@js:")):
  try:
   if not isinstance(json.loads(h),dict): add(out,"error",label+".header","header 应为 JSON 对象字符串")
  except json.JSONDecodeError as e: add(out,"error",label+".header",f"header JSON 非法：{e.msg}")
 check_ua(h,label+".header",out)
 for rn,known in BOOK_RULES.items():
  rule=x.get(rn)
  if rule is None: continue
  if not isinstance(rule,dict): add(out,"error",label+"."+rn,"规则组应为对象"); continue
  for f,v in rule.items():
   where=f"{label}.{rn}.{f}"
   if f not in known: add(out,"warning",where,"未知字段；按目标源码核实")
   check_rule_text(v,where,out,target)
   if rn in ("ruleSearch","ruleExplore") and f=="bookList" and isinstance(v,str) and "###" in v: add(out,"error",where,"列表字段不应使用 OnlyOne")
   if rn=="ruleToc" and f=="chapterList" and isinstance(v,str) and "###" in v: add(out,"error",where,"目录列表不应使用 OnlyOne")
 if target=="md3" and isinstance(x.get("ruleBookInfo"),dict):
  bi=x["ruleBookInfo"]
  full=label+".ruleBookInfo."
  # ruleBookInfo.summary 不是阅读字段（真名 intro）。写错不报错、静默为空。
  if "summary" in bi: add(out,"error",full+"summary","字段错名：详情简介真名是 intro，summary 会被忽略且静默为空")
  for bad,why in KNOWN_BAD_FIELDS.items():
   f=bad.split(".",1)[1]
   if f in bi: add(out,"error",full+f,"错名，MD3 基线为 "+why)
 for f in ("searchUrl","exploreUrl","loginUrl"):
  if f in x: check_rule_text(x[f],label+"."+f,out,target)
 s=x.get("searchUrl")
 if isinstance(s,str) and s and "{{key" not in s: add(out,"warning",label+".searchUrl","未发现 {{key}}；固定入口需人工确认")

def check_rss(x,label,out,target):
 for f in RSS_REQUIRED:
  if not isinstance(x.get(f),str) or not x[f].strip(): add(out,"error",label,f"缺少非空字符串字段 {f}")
 for f in RSS_RULE_FIELDS:
  if f in x and x[f] is not None: check_rule_text(x[f],label+"."+f,out,target)
 if x.get("ruleArticles"):
  for f in ("ruleTitle","ruleLink"):
   if not isinstance(x.get(f),str) or not x[f].strip(): add(out,"error",label,f"自定义列表必须填写 {f}")
 # 教程把“列表下一页”写成 ruleArticles；若真的照抄，分页规则会覆盖列表规则本身
 if isinstance(x.get("ruleArticles"),str) and x["ruleArticles"].strip() and "{{page}}" in x["ruleArticles"]:
  add(out,"error",label+".ruleArticles","RSS 不支持 {{page}}；分页请用 ruleNextPage（教程笔误易致同名覆盖）")

def validate(path,target,forced):
 r={"file":str(path),"sources":0,"errors":0,"warnings":0,"issues":[]}
 try: data,dups=load(path)
 except Exception as e: add(r["issues"],"error",str(path),f"无法解析 JSON：{e}");r["errors"]=1;return r
 for k in sorted(set(dups)): add(r["issues"],"error",str(path),f"重复 JSON 键：{k}")
 items=data if isinstance(data,list) else [data] if isinstance(data,dict) else []
 if not items: add(r["issues"],"error",str(path),"顶层必须为非空对象或数组")
 r["sources"]=len(items); seen={}
 for i,x in enumerate(items):
  if not isinstance(x,dict): add(r["issues"],"error",f"source[{i}]","数组项必须为对象");continue
  k=forced if forced!="auto" else kind_of(x)
  label=next((v for v in (x.get("bookSourceName"),x.get("sourceName")) if isinstance(v,str) and v.strip()),f"source[{i}]")
  if k=="book": check_book(x,label,r["issues"],target); key=x.get("bookSourceUrl")
  elif k=="rss": check_rss(x,label,r["issues"],target); key=x.get("sourceUrl")
  else: add(r["issues"],"error",label,"无法识别为书源或 RSS");key=None
  if isinstance(key,str) and key:
   if key in seen: add(r["issues"],"error",label,f"唯一 URL 与第 {seen[key]+1} 项重复")
   seen[key]=i
 r["errors"]=sum(i["level"]=="error" for i in r["issues"]);r["warnings"]=sum(i["level"]=="warning" for i in r["issues"])
 return r

def main():
 p=argparse.ArgumentParser();p.add_argument("--strict",action="store_true");p.add_argument("--json",action="store_true",dest="jsonout");p.add_argument("--target",choices=("common","md3"),default="md3");p.add_argument("--kind",choices=("auto","book","rss"),default="auto");p.add_argument("files",nargs="+");a=p.parse_args()
 rs=[validate(f,a.target,a.kind) for f in a.files]
 if a.jsonout: print(json.dumps(rs,ensure_ascii=False,indent=2))
 else:
  for r in rs:
   print(f"\n=== {r['file']}（{r['sources']} 项）===")
   for i in r["issues"]: print(("  ✗ " if i["level"]=="error" else "  ⚠ ")+f"[{i['where']}] {i['message']}")
   print(f"  结果：{'FAIL' if r['errors'] else 'WARN' if r['warnings'] else 'PASS'}（错误 {r['errors']}，警告 {r['warnings']}）")
  print("\n注：静态校验不能证明网络、规则引擎或真机可用。")
 e=sum(r["errors"] for r in rs);w=sum(r["warnings"] for r in rs);return 1 if e else 2 if a.strict and w else 0
if __name__=="__main__":sys.exit(main())
