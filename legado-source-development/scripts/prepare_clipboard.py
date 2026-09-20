#!/usr/bin/env python3
"""验证 Legado JSON 并生成无 Markdown 包装的紧凑剪贴板文本。"""
import argparse,hashlib,json,sys
from pathlib import Path

def no_dupes(pairs):
 d={}
 for k,v in pairs:
  if k in d: raise ValueError(f"重复 JSON 键: {k}")
  d[k]=v
 return d

def main():
 p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('-o','--output');p.add_argument('--array',action='store_true');a=p.parse_args()
 raw=Path(a.source).read_text('utf-8-sig');data=json.loads(raw,object_pairs_hook=no_dupes)
 if a.array and isinstance(data,dict):data=[data]
 text=json.dumps(data,ensure_ascii=False,separators=(',',':'))
 json.loads(text,object_pairs_hook=no_dupes)
 out=Path(a.output) if a.output else Path(a.source).with_suffix('.clipboard.json')
 out.write_text(text,encoding='utf-8')
 print(json.dumps({'ok':True,'output':str(out),'bytes':len(text.encode()),'sha256':hashlib.sha256(text.encode()).hexdigest(),'top':'array' if isinstance(data,list) else 'object'},ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));sys.exit(1)
