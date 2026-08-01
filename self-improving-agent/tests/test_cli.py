#!/usr/bin/env python3
import concurrent.futures, os, re, stat, subprocess, tempfile, unittest
from pathlib import Path

CLI='/var/minis/skills/self-improving-agent/scripts/self_improving.py'

class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.base=self.root/'custom'; self.shared=self.root/'shared'
        self.env=os.environ.copy(); self.env['SELF_IMPROVING_BASE']=str(self.shared); self.env['SELF_IMPROVING_PUBLIC']=str(self.shared/'public')
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
    def test_memory_promotion_preserves_public(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        self.cli('--base',self.base,'update',ident,'--promotion','memory','--note','已写记忆')
        self.assertIn('**提升**: public,memory',self.text())
        self.assertIn('**提升**: public,memory',(self.shared/'public'/'LEARNINGS.md').read_text())
    def test_review_deduplicates_public_copy(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        out=self.cli('--base',self.base,'review').stdout
        self.assertIn('异常重复 ID：0',out); self.assertIn('public=1',out)
    def test_review_rejects_same_id_in_wrong_file_type(self):
        ident=self.make(); wrong=self.base/'ERRORS.md'; wrong.write_text(wrong.read_text()+self.text()[self.text().index(f'## [{ident}]'):])
        self.assertIn('异常重复 ID：1',self.cli('--base',self.base,'review').stdout)
    def test_review_detects_copy_drift(self):
        ident=self.make(); self.cli('--base',self.base,'promote',ident)
        public=self.shared/'public'/'LEARNINGS.md'; public.write_text(public.read_text().replace('**状态**: pending','**状态**: resolved',1))
        self.assertIn('副本漂移：1',self.cli('--base',self.base,'review').stdout)
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
        self.cli('--base',self.base,'learning','另一条','详情','--category','ok\n## [LRN-20260101-AAAAAA] forged','--tags','x\n## [LRN-20260101-BBBBBB] forged')
        self.assertEqual(len(re.findall(r'^## \[LRN-',self.text(),re.M)),2)

if __name__=='__main__': unittest.main(verbosity=2)
