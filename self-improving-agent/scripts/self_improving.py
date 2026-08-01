#!/usr/bin/env python3
import argparse, fcntl, hashlib, os, re, secrets, sys, tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SKILL = Path('/var/minis/skills/self-improving-agent')
DEFAULT = Path(os.environ.get('SELF_IMPROVING_BASE', '/var/minis/shared/self-improving-agent')).resolve()
PUBLIC = Path(os.environ.get('SELF_IMPROVING_PUBLIC', str(DEFAULT / 'public'))).resolve()
LEGACY = SKILL / 'data'
FILES = {'learning':'LEARNINGS.md','error':'ERRORS.md','feature':'FEATURE_REQUESTS.md'}
HEADERS = {'LEARNINGS.md':'# Learnings\n','ERRORS.md':'# Errors\n','FEATURE_REQUESTS.md':'# Feature Requests\n'}
VALID_STATES = {'pending','in_progress','resolved','wont_fix'}
VALID_PROMOTIONS = {'none','public','memory','public,memory'}
ENTRY_RE = re.compile(r'(?ms)^## \[([^]\n]+)\].*?(?=^## \[|\Z)')
ID_RE = re.compile(r'^(LRN|ERR|FEAT)-\d{8}-[A-Z0-9]{3,16}$')


def now(): return datetime.now().astimezone().isoformat(timespec='seconds')
def today(): return datetime.now().astimezone().strftime('%Y%m%d')

def secure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    try: os.chmod(path, 0o700)
    except PermissionError: pass

@contextmanager
def lock(base):
    with multi_lock(base): yield

@contextmanager
def multi_lock(*bases):
    files=[]
    try:
        for base in sorted({Path(x).resolve() for x in bases},key=str):
            secure_dir(base); p=base/'.lock'
            f=open(p,'a+',encoding='utf-8'); os.chmod(p,0o600); fcntl.flock(f,fcntl.LOCK_EX); files.append(f)
        yield
    finally:
        for f in reversed(files): fcntl.flock(f,fcntl.LOCK_UN); f.close()

def atomic_write(path,text):
    secure_dir(path.parent)
    fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp,0o600); os.replace(tmp,path)
        dfd=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def init_base(base):
    secure_dir(base)
    with lock(base):
        for name,head in HEADERS.items():
            p=base/name
            if not p.exists(): atomic_write(p,head)
            else:
                try: os.chmod(p,0o600)
                except PermissionError: pass

def entries(text): return [(m.group(1),m.group(0).rstrip()+'\n') for m in ENTRY_RE.finditer(text)]
def block_for(text,ident):
    for found,block in entries(text):
        if found==ident: return block
    return None

def unique_block(path,ident):
    try: text=path.read_text(encoding='utf-8',errors='strict')
    except UnicodeError: sys.exit(f'日志不是有效 UTF-8：{path}')
    found=[b for i,b in entries(text) if i==ident]
    if len(found)!=1: sys.exit(f'条目不唯一或已损坏：{ident} → {path}')
    block=found[0]
    for field in ('优先级','状态'):
        if not re.search(rf'(?m)^\*\*{field}\*\*: \S+',block): sys.exit(f'条目缺少必要字段 {field}：{ident} → {path}')
    return block

def replace_block(path,ident,transform):
    text=path.read_text(encoding='utf-8',errors='strict'); matches=[b for i,b in entries(text) if i==ident]
    if len(matches)!=1: return False
    old=matches[0]; new=transform(old).rstrip()+'\n'
    if new==old: return False
    atomic_write(path,text.replace(old,new,1)); return True

def roots(args):
    result=[]
    for raw in [args.base,DEFAULT,PUBLIC,LEGACY,LEGACY/'public']:
        p=Path(raw)
        if p not in result: result.append(p)
    workspace=Path('/var/minis/workspace')
    if workspace.exists():
        for p in workspace.rglob('.learnings'):
            if p.is_dir() and p not in result: result.append(p)
    return result

def markdown_files(args):
    out=[]
    for root in roots(args):
        if root.is_dir():
            for name in HEADERS:
                p=root/name
                if p.is_file() and p not in out: out.append(p)
    return out

def locations(args,ident):
    if not ID_RE.fullmatch(ident): return []
    out=[]
    for p in markdown_files(args):
        if block_for(p.read_text(encoding='utf-8',errors='replace'),ident) is not None: out.append(p)
    return out

def find_entry(args,ident,prefer_non_public=True):
    found=locations(args,ident)
    if prefer_non_public:
        writable=[p for p in found if p.parent not in (PUBLIC,LEGACY,LEGACY/'public')]
        if len(writable)>1: sys.exit(f'条目存在多个权威源，拒绝任选：{ident}')
        if writable: return writable[0]
        if any(p.parent==LEGACY for p in found): sys.exit(f'条目仅存在于旧只读区，请先执行 migrate：{ident}')
    return found[0] if found else None

def authoritative_locations(args,ident):
    primary=find_entry(args,ident)
    if not primary: return []
    out=[primary]
    public=PUBLIC/primary.name
    if public.is_file() and block_for(public.read_text(encoding='utf-8',errors='replace'),ident) is not None and public not in out: out.append(public)
    return out

def new_id(prefix,paths):
    known={ident for p in paths if p.is_file() for ident,_ in entries(p.read_text(encoding='utf-8',errors='replace'))}
    while True:
        ident=f'{prefix}-{today()}-{secrets.token_hex(3).upper()}'
        if ident not in known: return ident

def safe_text(value):
    value=str(value)
    return re.sub(r'(?m)^(## \[)',r'\\\1',value)

def metadata(args):
    lines=[f'- 来源: {safe_text(args.source)}',f'- 作用域: {args.mode}',f'- 基础路径: {args.base}']
    if args.project: lines.append(f'- 项目路径: {args.project}')
    lines += [f'- 关联文件: {safe_text(getattr(args,"related_file",None) or "(无)")}',f'- 标签: {safe_text(getattr(args,"tags",None) or "(无)")}']
    return '\n'.join(lines)

def append_entry(path,body):
    text=path.read_text(encoding='utf-8',errors='replace')
    if text and not text.endswith('\n'): text+='\n'
    atomic_write(path,text+body)

def record(args,kind):
    init_base(args.base); path=args.base/FILES[kind]
    with lock(args.base):
        ident=new_id({'learning':'LRN','error':'ERR','feature':'FEAT'}[kind],markdown_files(args)+[path]); ts=now(); detail=safe_text(args.details or '（未提供）'); summary=safe_text(args.summary); action=safe_text(args.action or '（待补充）')
        domain=safe_text(args.domain).replace('\n',' '); category=safe_text(args.category).replace('\n',' ')
        common=f"**记录时间**: {ts}\n**优先级**: {args.priority}\n**状态**: pending\n**提升**: none\n**领域**: {domain}\n"
        if kind=='learning': body=f"## [{ident}] {category}\n\n{common}\n### 摘要\n{summary}\n\n### 详情\n{detail}\n\n### 建议动作\n{action}\n\n### 元数据\n{metadata(args)}\n\n---\n"
        elif kind=='error': body=f"## [{ident}] {category}\n\n{common}\n### 摘要\n{summary}\n\n### Error\n```text\n{detail}\n```\n\n### Context\n{safe_text(args.context or '（未提供）')}\n\n### 建议修复\n{action}\n\n### 元数据\n- 可复现: {args.reproducible}\n{metadata(args)}\n\n---\n"
        else: body=f"## [{ident}] {category}\n\n{common}\n### 需求能力\n{summary}\n\n### 用户背景\n{detail}\n\n### 复杂度评估\n{args.complexity}\n\n### 建议实现\n{action}\n\n### 元数据\n- 频次: {args.frequency}\n{metadata(args)}\n\n---\n"
        append_entry(path,body)
    print(f'已记录：{ident} → {path}')

def add_note(block,heading,note):
    stamp=f"\n### {heading}\n- **时间**: {now()}\n- **说明**: {note}\n"
    return block.rstrip().removesuffix('---').rstrip()+stamp+'\n---\n'

def promotion_of(block):
    m=re.search(r'(?m)^\*\*提升\*\*: (\S+)',block)
    if m: return m.group(1)
    state=re.search(r'(?m)^\*\*状态\*\*: (\S+)',block)
    return {'promoted_public':'public','promoted_memory':'memory'}.get(state.group(1),'none') if state else 'none'

def set_promotion(block,value):
    if re.search(r'(?m)^\*\*提升\*\*:',block): return re.sub(r'(?m)^\*\*提升\*\*: \S+',f'**提升**: {value}',block,1)
    return re.sub(r'(?m)^(\*\*状态\*\*: \S+)$',rf'\1\n**提升**: {value}',block,1)

def merge_promotion(current,requested):
    if requested=='none': return 'none'
    parts=set(current.split(','))|set(requested.split(',')); parts.discard('none')
    return ','.join(x for x in ('public','memory') if x in parts) or 'none'

def update(args):
    src=find_entry(args,args.id)
    if not src: sys.exit(f'未找到条目：{args.id}')
    if not any((args.status,args.promotion,args.priority,args.note)): sys.exit('update 至少需要 --status、--promotion、--priority 或 --note')
    def apply(block):
        legacy=re.search(r'(?m)^\*\*状态\*\*: (promoted_public|promoted_memory)',block)
        if legacy: block=re.sub(r'(?m)^\*\*状态\*\*: \S+','**状态**: pending',block,1)
        if args.status: block=re.sub(r'(?m)^\*\*状态\*\*: \S+',f'**状态**: {args.status}',block,1)
        if args.promotion: block=set_promotion(block,merge_promotion(promotion_of(block),args.promotion))
        if args.priority: block=re.sub(r'(?m)^\*\*优先级\*\*: \S+',f'**优先级**: {args.priority}',block,1)
        return add_note(block,'更新记录',safe_text(args.note)) if args.note else block
    changed=[]
    with multi_lock(src.parent,PUBLIC):
        source=unique_block(src,args.id); final=apply(source)
        if replace_block(src,args.id,lambda _: final): changed.append(src)
        public=PUBLIC/src.name
        if public.is_file() and block_for(public.read_text(encoding='utf-8',errors='replace'),args.id) is not None:
            if replace_block(public,args.id,lambda _: final): changed.append(public)
    if not changed: sys.exit(f'未找到条目：{args.id}')
    print(f'已更新：{args.id} → '+', '.join(map(str,changed)))

def promote(args):
    src=find_entry(args,args.id)
    if not src: sys.exit(f'未找到条目：{args.id}')
    init_base(PUBLIC); target=PUBLIC/src.name
    def marked(block):
        legacy=re.search(r'(?m)^\*\*状态\*\*: (promoted_public|promoted_memory)',block)
        if legacy: block=re.sub(r'(?m)^\*\*状态\*\*: \S+','**状态**: pending',block,1)
        current=promotion_of(block)
        value='public,memory' if current=='memory' else 'public'
        block=set_promotion(block,value)
        if '### 提升记录' in block: return block
        return add_note(block,'提升记录',f'已提升到 {target}')
    with multi_lock(src.parent,PUBLIC):
        source_block=unique_block(src,args.id)
        final_block=marked(source_block)
        if src.parent!=PUBLIC: replace_block(src,args.id,lambda _: final_block)
        text=target.read_text(encoding='utf-8',errors='replace'); old=block_for(text,args.id)
        if old is None: append_entry(target,final_block)
        else: atomic_write(target,text.replace(old,final_block,1))
    print(f'已提升：{args.id} → {target}')

def recur(args):
    src=find_entry(args,args.id)
    if not src: sys.exit(f'未找到条目：{args.id}')
    def apply(block):
        m=re.search(r'(?m)^- 复发次数: (\d+)',block); count=int(m.group(1))+1 if m else 2
        if m: block=block[:m.start()]+f'- 复发次数: {count}'+block[m.end():]
        else: block=block.rstrip().removesuffix('---').rstrip()+f'\n- 复发次数: {count}\n- 最近出现: {now()}\n\n---\n'
        return re.sub(r'(?m)^- 最近出现: .*',f'- 最近出现: {now()}',block)
    changed=[]
    with multi_lock(src.parent,PUBLIC):
        source=unique_block(src,args.id); final=apply(source)
        if replace_block(src,args.id,lambda _: final): changed.append(src)
        public=PUBLIC/src.name
        if public.is_file() and block_for(public.read_text(encoding='utf-8',errors='replace'),args.id) is not None:
            if replace_block(public,args.id,lambda _: final): changed.append(public)
    print(f'已记录复发：{args.id} → '+', '.join(map(str,changed)))

def search(args):
    found=0
    for p in markdown_files(args):
        for n,line in enumerate(p.read_text(encoding='utf-8',errors='replace').splitlines(),1):
            if args.keyword.casefold() in line.casefold(): print(f'{p}:{n}:{line}'); found+=1
    return 0 if found else 1

def signature(block):
    normalized=re.sub(r'(?m)^- \*\*时间\*\*: .*$',r'- **时间**: <timestamp>',block)
    return hashlib.sha256(normalized.encode()).hexdigest()

def review(args):
    counts={s:0 for s in VALID_STATES}; promotions={s:0 for s in VALID_PROMOTIONS}; incomplete=[]; duplicate={}; copies={}; seen=set(); invalid=[]
    for p in markdown_files(args):
        try: text=p.read_text(encoding='utf-8',errors='strict')
        except UnicodeError: invalid.append(str(p)); continue
        for ident,block in entries(text):
            duplicate.setdefault(ident,[]).append(str(p)); copies.setdefault(ident,[]).append((p,signature(block)))
            if ident in seen: continue
            seen.add(ident); m=re.search(r'(?m)^\*\*状态\*\*: (\S+)',block)
            if m:
                state=m.group(1)
                if state in ('promoted_public','promoted_memory'): state='pending'
                counts[state]=counts.get(state,0)+1
            promotion=promotion_of(block); promotions[promotion]=promotions.get(promotion,0)+1
            if '（待补充）' in block or '（未提供）' in block: incomplete.append(ident)
    expected=[]
    for ident,paths in duplicate.items():
        unique={Path(p) for p in paths}
        repeated_in_file=len(paths)!=len(unique)
        names={p.name for p in unique}
        active=[p for p in unique if not str(p).startswith(str(LEGACY)) and p.parent!=PUBLIC]
        public=[p for p in unique if p.parent in (PUBLIC,LEGACY/'public')]
        legacy=[p for p in unique if p.parent==LEGACY]
        same_type=len(names)==1
        allowed=not repeated_in_file and same_type and len(active)<=1 and len(public)<=1 and len(legacy)<=1
        if repeated_in_file or (len(unique)>1 and not allowed): expected.append(ident)
    drift=[]
    for ident,items in copies.items():
        active=[sig for p,sig in items if not str(p).startswith(str(LEGACY))]
        if len(active)>1 and len(set(active))>1: drift.append(ident)
    print('状态统计：'+'，'.join(f'{k}={v}' for k,v in counts.items() if v))
    print('提升统计：'+'，'.join(f'{k}={v}' for k,v in promotions.items() if v))
    print(f'信息不完整：{len(incomplete)} 条；异常重复 ID：{len(expected)} 条；副本漂移：{len(drift)} 条；损坏文件：{len(invalid)} 个')
    if args.verbose:
        if invalid: print('损坏文件: '+' '.join(sorted(invalid)))
        if incomplete: print('信息不完整: '+' '.join(sorted(incomplete)))
        if expected: print('异常重复: '+' '.join(sorted(expected)))
        if drift: print('副本漂移: '+' '.join(sorted(drift)))

def migrate(args):
    init_base(DEFAULT); copied=0
    with lock(DEFAULT):
        for name in HEADERS:
            src=LEGACY/name; dst=DEFAULT/name
            if not src.is_file(): continue
            dtext=dst.read_text(encoding='utf-8',errors='replace'); known={i for i,_ in entries(dtext)}
            for ident,block in entries(src.read_text(encoding='utf-8',errors='replace')):
                if ident not in known: dtext+=block; known.add(ident); copied+=1
            atomic_write(dst,dtext)
    print(f'迁移完成：新增 {copied} 条；旧目录保留兼容')

def parser():
    p=argparse.ArgumentParser(description='Self Improving Agent v3.2.1')
    g=p.add_mutually_exclusive_group(); g.add_argument('--base',type=Path); g.add_argument('--project',type=Path); g.add_argument('--public',action='store_true'); g.add_argument('--skill',action='store_true'); g.add_argument('--workspace',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--source',default='conversation'); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('init'); sub.add_parser('status'); sub.add_parser('migrate')
    for kind in FILES:
        q=sub.add_parser(kind); q.add_argument('summary'); q.add_argument('details',nargs='?'); q.add_argument('--category',default={'learning':'best_practice','error':'command','feature':'capability'}[kind]); q.add_argument('--priority',choices=['low','medium','high','critical'],default='high' if kind=='error' else 'medium'); q.add_argument('--domain',default='infra' if kind=='error' else 'docs'); q.add_argument('--action'); q.add_argument('--related-file'); q.add_argument('--tags')
        if kind=='error': q.add_argument('--context'); q.add_argument('--reproducible',choices=['yes','no','unknown'],default='unknown')
        if kind=='feature': q.add_argument('--complexity',choices=['simple','medium','complex'],default='medium'); q.add_argument('--frequency',choices=['first_time','recurring'],default='first_time')
    q=sub.add_parser('search'); q.add_argument('keyword'); q=sub.add_parser('promote'); q.add_argument('id')
    q=sub.add_parser('update'); q.add_argument('id'); q.add_argument('--status',choices=sorted(VALID_STATES)); q.add_argument('--promotion',choices=sorted(VALID_PROMOTIONS)); q.add_argument('--priority',choices=['low','medium','high','critical']); q.add_argument('--note')
    q=sub.add_parser('resolve'); q.add_argument('id'); q.add_argument('note',nargs='?',default='问题已解决')
    q=sub.add_parser('recur'); q.add_argument('id'); q=sub.add_parser('review'); q.add_argument('--verbose',action='store_true')
    return p

def main():
    a=parser().parse_args()
    if a.project: a.project=a.project.resolve(); a.base=a.project/'.learnings'; a.mode='project'
    elif a.public or a.workspace: a.base=PUBLIC; a.mode='public'
    elif a.skill: sys.exit('--skill 已弃用：旧 data 区只读；默认使用 shared，迁移请执行 migrate')
    elif a.base: a.base=a.base.resolve(); a.mode='custom'
    else: a.base=DEFAULT; a.mode='shared'
    if a.cmd=='init': init_base(a.base); print(f'已初始化：{a.base}')
    elif a.cmd=='status': init_base(a.base); print(f'模式: {a.mode}\n基础路径: {a.base}\n公共区: {PUBLIC}\n旧数据区: {LEGACY}')
    elif a.cmd in FILES: record(a,a.cmd)
    elif a.cmd=='search': sys.exit(search(a))
    elif a.cmd=='promote': promote(a)
    elif a.cmd=='update': update(a)
    elif a.cmd=='resolve': a.status='resolved'; a.promotion=None; a.priority=None; update(a)
    elif a.cmd=='recur': recur(a)
    elif a.cmd=='review': review(a)
    elif a.cmd=='migrate': migrate(a)

if __name__=='__main__': main()
