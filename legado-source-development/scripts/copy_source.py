#!/usr/bin/env python3
"""校验、Gson 探测并将纯 Legado JSON 写入 Android 剪贴板。"""
import argparse,json,subprocess,tempfile,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
SANDBOX=Path('/var/minis/shared/legado/sandbox')
def main():
 p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--array',action='store_true');a=p.parse_args()
 with tempfile.TemporaryDirectory() as d:
  clip=Path(d)/'source.json'
  q=subprocess.run(['python3',str(HERE/'prepare_clipboard.py'),a.source,'-o',str(clip)]+(['--array'] if a.array else []),text=True,capture_output=True)
  if q.returncode:raise RuntimeError(q.stdout+q.stderr)
  if not (SANDBOX/'GsonImportProbe.class').exists():subprocess.run(['javac','-cp',str(SANDBOX/'lib/*'),str(SANDBOX/'GsonImportProbe.java')],check=True)
  subprocess.run(['java','-cp',f'{SANDBOX}:{SANDBOX}/lib/*','GsonImportProbe',str(clip)],check=True,capture_output=True,text=True)
  text=clip.read_text()
  r=subprocess.run(['android-clipboard','set','--text',text,'--label','Legado JSON'],text=True,capture_output=True)
  if r.returncode:raise RuntimeError(r.stdout+r.stderr)
  meta=json.loads(q.stdout);print(json.dumps({'ok':True,'copied':True,**meta},ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));sys.exit(1)
