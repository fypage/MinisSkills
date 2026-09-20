#!/usr/bin/env python3
import json,subprocess,tempfile
from pathlib import Path
D=Path(__file__).resolve().parent;P=D/'prepare_clipboard.py'
def main():
 with tempfile.TemporaryDirectory() as d:
  d=Path(d);src=d/'x.json';out=d/'clip.json'
  src.write_text(json.dumps({'bookSourceUrl':'https://x.test','bookSourceName':'X'},ensure_ascii=False,indent=2),encoding='utf-8')
  p=subprocess.run(['python3',str(P),str(src),'-o',str(out)],text=True,capture_output=True);assert p.returncode==0,p.stdout
  s=out.read_text();assert s.startswith('{') and s.endswith('}') and '```' not in s and '\n' not in s
  assert json.loads(s)['bookSourceName']=='X'
 print('PASS: pure JSON transport regression')
if __name__=='__main__':main()
