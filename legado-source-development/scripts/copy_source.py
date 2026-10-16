#!/usr/bin/env python3
"""校验、Gson 探测并将纯 Legado JSON 写入 Android 剪贴板。"""
import argparse,json,subprocess,tempfile,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
SANDBOX=Path('/var/minis/shared/legado/sandbox')
def import_probe(clip):
 """Gson 导入探针。JVM 不可用时降级为 Python JSON 解析，并明确标注降级。"""
 import importlib.util
 spec=importlib.util.spec_from_file_location('jp',str(HERE/'jvm_probe.py'))
 jp=importlib.util.module_from_spec(spec);spec.loader.exec_module(jp)
 st=jp.probe()
 if not st.get('available'):
  json.loads(clip.read_text(encoding='utf-8'))
  return {'ok':True,'engine':'python-json','degraded':True,'reason':st.get('reason'),
          'note':'同版本 Gson 探针不可用（%s），已降级为 Python JSON 严格解析'%st.get('reason')}
 try:
  if not (SANDBOX/'GsonImportProbe.class').exists():
   subprocess.run(['javac','-cp',str(SANDBOX/'lib/*'),str(SANDBOX/'GsonImportProbe.java')],check=True)
  subprocess.run(['java','-cp',f'{SANDBOX}:{SANDBOX}/lib/*','GsonImportProbe',str(clip)],check=True,capture_output=True,text=True)
  return {'ok':True,'engine':'gson-2.14.0'}
 except Exception as e:
  return {'ok':False,'engine':'gson-2.14.0','error':str(e)}


def main():
 p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--array',action='store_true');a=p.parse_args()
 with tempfile.TemporaryDirectory() as d:
  clip=Path(d)/'source.json'
  q=subprocess.run(['python3',str(HERE/'prepare_clipboard.py'),a.source,'-o',str(clip)]+(['--array'] if a.array else []),text=True,capture_output=True)
  if q.returncode:raise RuntimeError(q.stdout+q.stderr)
  probe=import_probe(clip)
  if not probe['ok']:raise RuntimeError('导入探针失败: '+json.dumps(probe,ensure_ascii=False))
  text=clip.read_text()
  r=subprocess.run(['android-clipboard','set','--text',text,'--label','Legado JSON'],text=True,capture_output=True)
  if r.returncode:raise RuntimeError(r.stdout+r.stderr)
  meta=json.loads(q.stdout);print(json.dumps({'ok':True,'copied':True,'import_probe':probe,**meta},ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));sys.exit(1)
