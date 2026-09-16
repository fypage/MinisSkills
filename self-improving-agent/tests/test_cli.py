#!/usr/bin/env python3
import concurrent.futures, importlib.util, os, re, stat, subprocess, tempfile, unittest
from pathlib import Path

CLI='/var/minis/skills/self-improving-agent/scripts/self_improving.py'

class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.base=self.root/'custom'; self.shared=self.root/'shared'
        self.env=os.environ.copy(); self.env['SELF_IMPROVING_BASE']=str(self.shared); self.env['SELF_IMPROVING_PUBLIC']=str(self.shared/'public'); self.env['SELF_IMPROVING_LEGACY']=str(self.root/'legacy'); self.env['SELF_IMPROVING_WORKSPACE']=str(self.root/'workspace')
    def tearDown(self): self.tmp.cleanup()
    def cli(self,*args,check=True):
        return subprocess.run(['python3',CLI,*map(str,args)],text=True,capture_output=True,check=check,env=self.env)
    def make(self,summary='测试摘要'):
        out=self.cli('--base',self.base,'learning',summary,'测试详情','--action','执行动作').stdout
        return re.search(r'(LRN-\d{8}-[A-F0-9]{6})',out).group(1)
    def text(self,name='LEARNINGS.md'): return (self.base/name).read_text()
    def test_init_record_and_permissions(self):
        ident=self.make(); self.assertIn(ident,self.text()); self.assertIn('执行动作',self.text())
        self.assertEqual(stat.S_IMODE((self.base/'LEARNINGS.md').stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(self.base.stat().st_mode),0o700)
    def test_existing_base_permissions_are_preserved(self):
        base=self.root/'existing'; base.mkdir(); base.chmod(0o755)
        self.cli('--base',base,'init'); self.assertEqual(stat.S_IMODE(base.stat().st_mode),0o755)
    def test_symlink_lock_is_rejected(self):
        base=self.root/'linked'; base.mkdir(); target=self.root/'target'; target.write_text('keep')
        (base/'.lock').symlink_to(target)
        out=self.cli('--base',base,'init',check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('符号链接锁文件',out.stderr); self.assertEqual(target.read_text(),'keep')
    def test_symlink_log_is_rejected(self):
        base=self.root/'loglink'; base.mkdir(); target=self.root/'outside'; target.write_text('secret'); (base/'LEARNINGS.md').symlink_to(target)
        out=self.cli('--base',base,'init',check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('符号链接日志文件',out.stderr); self.assertEqual(target.read_text(),'secret')
    def test_post_init_symlink_swap_is_rejected(self):
        ident=self.make(); path=self.base/'LEARNINGS.md'; backup=self.root/'original'; path.rename(backup); target=self.root/'outside2'; target.write_text(backup.read_text()); path.symlink_to(target)
        out=self.cli('--base',self.base,'resolve',ident,check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('符号链接日志文件',out.stderr); self.assertNotIn('**状态**: resolved',target.read_text())
    def test_custom_base_search(self):
        ident=self.make(); self.assertIn(str(self.base/'LEARNINGS.md'),self.cli('--base',self.base,'search',ident).stdout)
    def test_exact_id_not_reference(self):
        fake='LRN-20260101-ABCDEF'; self.make('引用 '+fake)
        out=self.cli('--base',self.base,'resolve',fake,check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('未找到条目',out.stderr)
    def test_resolve_and_empty_update_rejected(self):
        ident=self.make(); self.cli('--base',self.base,'resolve',ident,'验证通过')
        self.assertIn('**状态**: resolved',self.text()); self.assertIn('验证通过',self.text())
        self.assertNotEqual(self.cli('--base',self.base,'update',ident,check=False).returncode,0)
    def test_recur(self):
        ident=self.make(); self.cli('--base',self.base,'recur',ident); self.cli('--base',self.base,'recur',ident)
        self.assertIn('- 复发次数: 3',self.text())
    def test_promote_rejects_corrupt_public_copy(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        public=self.shared/'public'/'LEARNINGS.md'; public.write_text(public.read_text().replace('**状态**: pending','**状态**: bad',1))
        source_before=self.text(); out=self.cli('--base',self.base,'promote',ident,check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('公共副本结构损坏',out.stderr); self.assertEqual(self.text(),source_before)
    def test_promote_consistent_and_idempotent(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident); self.cli('--base',self.base,'promote',ident)
        public=(self.shared/'public'/'LEARNINGS.md').read_text()
        self.assertEqual(public.count(f'## [{ident}]'),1)
        self.assertIn('**状态**: pending',public); self.assertIn('**提升**: public',public)
        self.assertIn('**状态**: pending',self.text()); self.assertIn('**提升**: public',self.text())
        self.assertEqual(self.text().count('### 提升记录'),1)
    def test_concurrent_unique_and_intact(self):
        def one(i): return self.make(f'并发-{i}')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: ids=list(pool.map(one,range(24)))
        text=self.text(); self.assertEqual(len(set(ids)),24)
        self.assertEqual(text.count('## [LRN-'),24); self.assertEqual(text.count('\n---\n'),24)
    def test_resolve_after_promote_syncs_both_copies(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident); self.cli('--base',self.base,'resolve',ident,'完成')
        public=(self.shared/'public'/'LEARNINGS.md').read_text()
        self.assertIn('**状态**: resolved',self.text()); self.assertIn('**状态**: resolved',public)
        self.assertIn('**提升**: public',self.text()); self.assertIn('**提升**: public',public)
    def test_recur_after_promote_syncs_both_copies(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident); self.cli('--base',self.base,'recur',ident)
        public=(self.shared/'public'/'LEARNINGS.md').read_text()
        self.assertIn('- 复发次数: 2',self.text()); self.assertIn('- 复发次数: 2',public)
    def test_validate_entry_rejects_corrupt_migration_data(self):
        spec=importlib.util.spec_from_file_location('sia_validate',CLI); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        block='## [LRN-20260101-ABCDEF] x\n\n**优先级**: high\n'
        self.assertEqual(mod.validate_entry('LRN-20260101-ABCDEF',block,'LEARNINGS.md'),'缺少必要字段 状态')
        self.assertEqual(mod.validate_entry('LRN-20260101-ABCDEF',block+'**状态**: pending\n','ERRORS.md'),'ID 与文件类型不匹配')
    def test_memory_promotion_preserves_public(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        self.cli('--base',self.base,'update',ident,'--promotion','memory','--note','已写记忆')
        self.assertIn('**提升**: public,memory',self.text())
        self.assertIn('**提升**: public,memory',(self.shared/'public'/'LEARNINGS.md').read_text())
    def test_review_deduplicates_public_copy(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        out=self.cli('--base',self.base,'review').stdout
        self.assertIn('异常重复 ID：0',out); self.assertIn('public=1',out)
    def test_review_rejects_duplicate_id_in_same_file(self):
        ident=self.make(); path=self.base/'LEARNINGS.md'; block=path.read_text()[path.read_text().index(f'## [{ident}]'):]
        path.write_text(path.read_text()+block)
        self.assertIn('异常重复 ID：1',self.cli('--base',self.base,'review').stdout)
        out=self.cli('--base',self.base,'resolve',ident,check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('不唯一',out.stderr)
    def test_review_reports_malformed_fields_and_wrong_type(self):
        ident=self.make(); path=self.base/'LEARNINGS.md'; path.write_text(path.read_text().replace('**状态**: pending','**状态**: impossible',1))
        self.assertIn('结构损坏：1',self.cli('--base',self.base,'review').stdout)
        path.write_text(path.read_text().replace('**状态**: impossible','**状态**: pending',1))
        wrong=self.base/'ERRORS.md'; wrong.write_text(wrong.read_text()+self.text()[self.text().index(f'## [{ident}]'):])
        self.assertIn('结构损坏：1',self.cli('--base',self.base,'review').stdout)
    def test_review_reports_duplicate_control_field(self):
        self.make(); path=self.base/'LEARNINGS.md'; path.write_text(path.read_text().replace('**状态**: pending','**状态**: pending\n**状态**: resolved',1))
        self.assertIn('结构损坏：1',self.cli('--base',self.base,'review').stdout)
    def test_review_reports_invalid_utf8(self):
        self.make(); (self.base/'ERRORS.md').write_bytes(b'# Errors\n\xff')
        self.assertIn('损坏文件：1',self.cli('--base',self.base,'review').stdout)
    def test_skill_flag_is_read_only_rejected(self):
        out=self.cli('--skill','learning','x','y',check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('只读',out.stderr)
    def test_multiple_authoritative_sources_rejected(self):
        ident=self.make(); other=self.shared; self.cli('init')
        block=self.text()[self.text().index(f'## [{ident}]'):]; path=other/'LEARNINGS.md'; path.write_text(path.read_text()+block)
        self.cli('--base',self.base,'resolve',ident)
        self.assertIn('**状态**: resolved',self.text())
        self.assertIn('**状态**: pending',path.read_text())
    def test_legacy_only_entry_requires_migration(self):
        ident=self.make()
        legacy=self.root/'legacy'/'LEARNINGS.md'; legacy.parent.mkdir(); legacy.write_text(self.text())
        with tempfile.TemporaryDirectory() as empty:
            env=self.env|{'SELF_IMPROVING_BASE':str(Path(empty)/'shared'),'SELF_IMPROVING_PUBLIC':str(Path(empty)/'shared/public')}
            out=subprocess.run(['python3',CLI,'resolve',ident],text=True,capture_output=True,env=env)
        self.assertNotEqual(out.returncode,0); self.assertIn('先执行 migrate',out.stderr)
    def test_update_rejects_missing_required_field(self):
        ident=self.make(); path=self.base/'LEARNINGS.md'; path.write_text(path.read_text().replace('**状态**: pending\n','',1))
        out=self.cli('--base',self.base,'resolve',ident,check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('缺少必要字段 状态',out.stderr)
    def test_review_rejects_same_id_in_wrong_file_type(self):
        ident=self.make(); wrong=self.base/'ERRORS.md'; wrong.write_text(wrong.read_text()+self.text()[self.text().index(f'## [{ident}]'):])
        self.assertIn('异常重复 ID：1',self.cli('--base',self.base,'review').stdout)
    def test_review_detects_copy_drift(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        public=self.shared/'public'/'LEARNINGS.md'; public.write_text(public.read_text().replace('**状态**: pending','**状态**: resolved',1))
        self.assertIn('副本漂移：1',self.cli('--base',self.base,'review').stdout)
    def test_transaction_rolls_back_first_write_on_second_failure(self):
        a=self.root/'a'; b=self.root/'b'; a.write_text('old-a'); b.write_text('old-b')
        spec=importlib.util.spec_from_file_location('sia',CLI); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        real=mod.atomic_write; calls=[]
        def fail_second(path,text):
            calls.append(path)
            if len(calls)==2: raise OSError('injected')
            return real(path,text)
        mod.atomic_write=fail_second
        with self.assertRaises(OSError): mod.transactional_write([(a,'old-a','new-a'),(b,'old-b','new-b')])
        self.assertEqual(a.read_text(),'old-a'); self.assertEqual(b.read_text(),'old-b')
    def test_update_rejects_duplicate_public_copy(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        public=self.shared/'public'/'LEARNINGS.md'; block=public.read_text()[public.read_text().index(f'## [{ident}]'):]; public.write_text(public.read_text()+block)
        source_before=self.text(); out=self.cli('--base',self.base,'resolve',ident,check=False)
        self.assertNotEqual(out.returncode,0); self.assertIn('公共副本条目不唯一',out.stderr); self.assertEqual(self.text(),source_before)
    def test_transaction_reports_incomplete_rollback_on_external_change(self):
        a=self.root/'ca'; b=self.root/'cb'; a.write_text('old-a'); b.write_text('old-b')
        spec=importlib.util.spec_from_file_location('sia_conflict',CLI); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        real=mod.atomic_write; calls=[]
        def conflict(path,text):
            calls.append(path)
            if len(calls)==2:
                a.write_text('external')
                raise OSError('injected')
            return real(path,text)
        mod.atomic_write=conflict
        with self.assertRaisesRegex(RuntimeError,'回滚不完整'): mod.transactional_write([(a,'old-a','new-a'),(b,'old-b','new-b')])
        self.assertEqual(a.read_text(),'external')
    def test_update_heals_existing_copy_drift(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        public=self.shared/'public'/'LEARNINGS.md'; public.write_text(public.read_text().replace('测试详情','漂移详情',1))
        self.cli('--base',self.base,'update',ident,'--priority','high')
        self.assertIn('测试详情',public.read_text()); self.assertNotIn('漂移详情',public.read_text())
    def test_concurrent_promote_resolve_converges(self):
        for _ in range(8):
            ident=self.make()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda cmd: self.cli('--base',self.base,*cmd), [('promote',ident),('resolve',ident,'完成')]))
            source=self.text(); public=(self.shared/'public'/'LEARNINGS.md').read_text()
            def state(text): return re.search(rf'(?ms)^## \[{ident}\].*?^\*\*状态\*\*: (\S+)',text).group(1)
            self.assertEqual(state(source),state(public))
    def test_content_cannot_inject_entry_heading(self):
        self.make('正常摘要\n## [LRN-20260101-ABCDEF] forged')
        self.assertEqual(len(re.findall(r'^## \[LRN-',self.text(),re.M)),1)
        detail='详情\n**状态**: resolved\n- 复发次数: 99\n### 提升记录\n---'
        self.cli('--base',self.base,'learning','另一条',detail,'--category','ok\n## [LRN-20260101-AAAAAA] forged','--tags','x\n## [LRN-20260101-BBBBBB] forged')
        text=self.text(); self.assertEqual(len(re.findall(r'^## \[LRN-',text,re.M)),2)
        self.assertEqual(len(re.findall(r'^\*\*状态\*\*:',text,re.M)),2); self.assertNotIn('\n- 复发次数: 99',text)


    def module(self):
        from unittest.mock import patch
        with patch.dict(os.environ,self.env):
            spec=importlib.util.spec_from_file_location('sia_isolated',CLI)
            mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        return mod
    def legacy_fixture(self):
        ident=self.make(); legacy=self.root/'legacy'; legacy.mkdir()
        (legacy/'LEARNINGS.md').write_text(self.text())
        return ident,legacy
    def test_promote_keeps_combined_memory(self):
        ident=self.make(); self.cli('--base',self.base,'update',ident,'--promotion','public,memory')
        self.cli('--base',self.base,'promote',ident); before=self.text()
        self.cli('--base',self.base,'promote',ident)
        self.assertIn('**提升**: public,memory',self.text()); self.assertEqual(before,self.text())
    def test_legacy_memory_survives_promote_and_update(self):
        for command in [('promote',),('update','--priority','critical')]:
            ident=self.make(); path=self.base/'LEARNINGS.md'
            text=path.read_text(); mod=self.module()
            block=mod.block_for(text,ident)
            old=block.replace('**状态**: pending','**状态**: promoted_memory').replace('**提升**: none\n','')
            path.write_text(text.replace(block,old))
            self.cli('--base',self.base,command[0],ident,*command[1:])
            final=mod.block_for(self.text(),ident)
            self.assertIn('memory',mod.promotion_of(final)); self.assertIn('**状态**: pending',final)
    def test_public_recur_writes_once(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        self.cli('--public','recur',ident)
        public=self.shared/'public'/'LEARNINGS.md'
        self.assertIn('- 复发次数: 2',public.read_text())
        self.cli('--public','update',ident,'--priority','critical')
        self.assertIn('**优先级**: critical',public.read_text())
    def test_explicit_missing_id_never_changes_other_base(self):
        ident=self.make(); before=self.text()
        result=self.cli('--base',self.root/'other','resolve',ident,check=False)
        self.assertNotEqual(result.returncode,0); self.assertEqual(before,self.text())
    def test_migrate_custom_and_idempotent_no_legacy_lock(self):
        ident,legacy=self.legacy_fixture(); dest=self.root/'migration'
        self.cli('--base',dest,'migrate'); before=(dest/'LEARNINGS.md').read_bytes()
        result=self.cli('--base',dest,'migrate')
        self.assertIn('新增 0 条',result.stdout); self.assertEqual(before,(dest/'LEARNINGS.md').read_bytes())
        self.assertFalse((legacy/'.lock').exists()); self.assertFalse((self.shared/'LEARNINGS.md').exists())
    def test_migrate_conflict_preserves_all_data(self):
        ident,legacy=self.legacy_fixture(); path=legacy/'LEARNINGS.md'
        path.write_text(path.read_text().replace('测试详情','冲突详情'))
        before=self.text(); old=path.read_bytes()
        result=self.cli('--base',self.base,'migrate',check=False)
        self.assertNotEqual(result.returncode,0); self.assertIn('内容冲突',result.stderr)
        self.assertEqual(before,self.text()); self.assertEqual(old,path.read_bytes())
    def test_legacy_base_cannot_be_written(self):
        result=self.cli('--base',self.root/'legacy','learning','x',check=False)
        self.assertNotEqual(result.returncode,0); self.assertFalse((self.root/'legacy').exists())
    def test_no_newline_eof_update(self):
        ident=self.make(); path=self.base/'LEARNINGS.md'; path.write_text(self.text().rstrip())
        self.cli('--base',self.base,'resolve',ident)
        self.assertIn('**状态**: resolved',self.text()); self.assertEqual(self.text().count('## ['),1)
    def test_search_exit_codes_and_empty(self):
        ident=self.make(); self.assertEqual(self.cli('--base',self.base,'search',ident).returncode,0)
        self.assertEqual(self.cli('--base',self.base,'search','not-present-xyz',check=False).returncode,1)
        self.assertNotEqual(self.cli('search','  ',check=False).returncode,0)
    def test_noop_update_succeeds(self):
        ident=self.make(); before=self.text()
        self.cli('--base',self.base,'update',ident,'--status','pending'); self.assertEqual(before,self.text())
    def test_error_fence_and_path_injection(self):
        path=self.root/'odd\n**状态**: resolved\n## [LRN-20260101-AAAAAA]'
        self.cli('--base',path,'error','x','```\n## [ERR-20260101-AAAAAA] forged')
        text=(path/'ERRORS.md').read_text()
        self.assertIn('````text\n',text); self.assertEqual(len(re.findall(r'^## \[',text,re.M)),1)
        self.assertEqual(len(re.findall(r'^\*\*状态\*\*:',text,re.M)),1)
    def test_invalid_field_tails_and_recurrence_rejected(self):
        mod=self.module(); ident=self.make(); block=mod.block_for(self.text(),ident)
        for broken in [block.replace('**状态**: pending','**状态**: pending trailing'),block+'- 复发次数: invalid\n',block+'- 最近出现: x\n- 最近出现: y\n']:
            self.assertIsNotNone(mod.validate_entry(ident,broken,'LEARNINGS.md'))
    def test_recur_repairs_missing_last_seen(self):
        ident=self.make(); path=self.base/'LEARNINGS.md'; path.write_text(self.text()+'- 复发次数: 2\n')
        self.cli('--base',self.base,'recur',ident)
        self.assertIn('- 复发次数: 3',self.text()); self.assertIn('- 最近出现:',self.text())
    def test_corrupt_public_update_and_recur_rejected(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        path=self.shared/'public'/'LEARNINGS.md'; path.write_text(path.read_text().replace('**状态**: pending','**状态**: invalid'))
        before=self.text()
        for cmd in [('resolve',ident),('recur',ident)]:
            self.assertNotEqual(self.cli('--base',self.base,*cmd,check=False).returncode,0)
            self.assertEqual(before,self.text())
    def test_transaction_rolls_back_post_replace_failure(self):
        mod=self.module(); a=self.root/'a'; b=self.root/'b'; a.write_text('a'); b.write_text('b')
        real=mod.atomic_write; calls=[]
        def fail(path,text):
            calls.append(path); real(path,text)
            if len(calls)==2: raise OSError('directory fsync failed after replace')
        mod.atomic_write=fail
        with self.assertRaises(OSError): mod.transactional_write([(a,'a','A'),(b,'b','B')])
        self.assertEqual(a.read_text(),'a'); self.assertEqual(b.read_text(),'b')
        self.assertFalse(list(self.root.glob('.*.tmp')))
    def test_sigterm_transaction_rolls_back(self):
        import signal
        mod=self.module(); a=self.root/'term-a'; b=self.root/'term-b'; a.write_text('a'); b.write_text('b')
        real=mod.atomic_write; calls=[]
        def fail(path,text):
            calls.append(path); real(path,text)
            if len(calls)==2: os.kill(os.getpid(),signal.SIGTERM)
        previous=signal.signal(signal.SIGTERM,mod._terminate)
        mod.atomic_write=fail
        try:
            with self.assertRaises(KeyboardInterrupt): mod.transactional_write([(a,'a','A'),(b,'b','B')])
        finally: signal.signal(signal.SIGTERM,previous)
        self.assertEqual(a.read_text(),'a'); self.assertEqual(b.read_text(),'b')

    def test_transaction_interrupt_rolls_back(self):
        mod=self.module(); a=self.root/'a'; b=self.root/'b'; a.write_text('a'); b.write_text('b')
        real=mod.atomic_write; calls=[]
        def fail(path,text):
            calls.append(path)
            if len(calls)==2: raise KeyboardInterrupt()
            real(path,text)
        mod.atomic_write=fail
        with self.assertRaises(KeyboardInterrupt): mod.transactional_write([(a,'a','A'),(b,'b','B')])
        self.assertEqual(a.read_text(),'a'); self.assertEqual(b.read_text(),'b')
    def test_atomic_replace_failure_preserves_original(self):
        from unittest.mock import patch
        mod=self.module(); path=self.root/'original'; path.write_text('old')
        with patch.object(mod.os,'replace',side_effect=OSError('injected')):
            with self.assertRaises(OSError): mod.atomic_write(path,'new')
        self.assertEqual(path.read_text(),'old'); self.assertFalse(list(self.root.glob('.*.tmp')))
    def test_concurrent_recur_no_lost_increments(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _:self.cli('--base',self.base,'recur',ident),range(20)))
        self.assertIn('- 复发次数: 21',self.text())
        mod=self.module(); public=(self.shared/'public'/'LEARNINGS.md').read_text()
        self.assertEqual(mod.block_for(self.text(),ident),mod.block_for(public,ident))

if __name__=='__main__': unittest.main(verbosity=2)
