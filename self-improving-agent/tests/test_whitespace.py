#!/usr/bin/env python3
"""Whitespace regression matrix; independent TestCase, no inherited CLI tests."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

CLI = os.environ.get('SIA_TEST_CLI', '/var/minis/skills/self-improving-agent/scripts/self_improving.py')
SPACES = ('', ' ', '   ', '\t', ' \t  \t')
IDENT = 'LRN-20260101-ABCDEF'


class WhitespaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        for key in ('BASE', 'PUBLIC', 'LEGACY', 'WORKSPACE'):
            self.env['SELF_IMPROVING_' + key] = str(self.root / key.lower())
        self.base = self.root / 'base'
        self.base.mkdir()
        self.path = self.base / 'LEARNINGS.md'
        with patch.dict(os.environ, self.env):
            spec = importlib.util.spec_from_file_location('sia_whitespace', CLI)
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)

    def cli(self, *args, check=True):
        return subprocess.run(['python3', CLI, *args], env=self.env,
                              text=True, capture_output=True, check=check)

    def seed(self, ws, state='pending', promotion='memory', extra=''):
        block = (f'## [{IDENT}] best_practice\n\n**优先级**:{ws}high\n'
                 f'**状态**:{ws}{state}\n')
        if promotion is not None:
            block += f'**提升**:{ws}{promotion}\n'
        block += '\n### 摘要\n隔离测试\n' + extra + '\n---\n'
        self.path.write_text('# Learnings\n' + block)
        public = self.root / 'public' / 'LEARNINGS.md'
        if public.exists():
            public.write_text('# Learnings\n')
        return block

    def values(self, field):
        label = '- ' + field if field in ('复发次数', '最近出现') else '**' + field + '**'
        return re.findall(r'^' + re.escape(label) + r':[ \t]*(.*)$', self.path.read_text(), re.M)

    def valid(self):
        block = self.mod.block_for(self.path.read_text(), IDENT)
        self.assertIsNone(self.mod.validate_entry(IDENT, block, 'LEARNINGS.md'))

    def test_validate_and_read_all_spacing(self):
        for ws in SPACES:
            with self.subTest(ws=repr(ws)):
                block = self.seed(ws, extra=f'- 复发次数:{ws}12\n- 最近出现:{ws}old\n')
                self.valid()
                self.assertEqual(self.mod.promotion_of(block), 'memory')

    def test_resolve_really_changes_status(self):
        for ws in SPACES:
            with self.subTest(ws=repr(ws)):
                self.seed(ws)
                self.cli('resolve', IDENT, '已验证')
                self.assertEqual(self.values('状态'), ['resolved'])
                self.assertEqual(self.values('提升'), ['memory'])
                self.valid()

    def test_update_priority_status_and_promotion(self):
        for ws in SPACES:
            with self.subTest(ws=repr(ws)):
                self.seed(ws)
                self.cli('update', IDENT, '--status', 'in_progress', '--priority', 'critical', '--promotion', 'public')
                self.assertEqual(self.values('状态'), ['in_progress'])
                self.assertEqual(self.values('优先级'), ['critical'])
                self.assertEqual(self.values('提升'), ['public,memory'])
                self.valid()

    def test_promote_preserves_memory_and_is_idempotent(self):
        for ws in SPACES:
            with self.subTest(ws=repr(ws)):
                self.seed(ws, state='resolved')
                self.cli('promote', IDENT)
                before = self.path.read_bytes()
                self.cli('promote', IDENT)
                self.assertEqual(before, self.path.read_bytes())
                self.assertEqual(self.values('提升'), ['public,memory'])
                self.assertEqual(self.values('状态'), ['resolved'])
                public = (self.root / 'public' / 'LEARNINGS.md').read_text()
                self.assertEqual(self.mod.block_for(public, IDENT), self.mod.block_for(self.path.read_text(), IDENT))
                self.valid()

    def test_legacy_conversion_all_spacing(self):
        for ws in SPACES:
            for state, expected in (('promoted_memory', 'memory'), ('promoted_public', 'public')):
                for command in ('update', 'promote'):
                    with self.subTest(ws=repr(ws), state=state, command=command):
                        self.seed(ws, state=state, promotion=None)
                        args = ('--priority', 'critical') if command == 'update' else ()
                        self.cli(command, IDENT, *args)
                        self.assertEqual(self.values('状态'), ['pending'])
                        wanted = 'public,memory' if command == 'promote' and expected == 'memory' else expected
                        self.assertEqual(self.values('提升'), [wanted])
                        self.valid()

    def test_recur_count_and_last_seen_no_duplicates(self):
        for ws in SPACES:
            for count, last in ((True, True), (True, False), (False, True), (False, False)):
                with self.subTest(ws=repr(ws), count=count, last=last):
                    extra = (f'- 复发次数:{ws}12\n' if count else '') + (f'- 最近出现:{ws}old\n' if last else '')
                    self.seed(ws, extra=extra)
                    self.cli('recur', IDENT)
                    self.cli('recur', IDENT)
                    self.assertEqual(self.values('复发次数'), ['14' if count else '3'])
                    seen = self.values('最近出现')
                    self.assertEqual(len(seen), 1)
                    self.assertRegex(seen[0], r'^\d{4}-\d{2}-\d{2}T')
                    self.valid()

    def test_review_current_and_legacy_spacing(self):
        for ws in SPACES:
            for state, promotion in (('resolved', 'memory'), ('promoted_memory', None), ('promoted_public', None)):
                with self.subTest(ws=repr(ws), state=state):
                    self.seed(ws, state=state, promotion=promotion)
                    out = self.cli('review').stdout
                    self.assertIn(('resolved' if state == 'resolved' else 'pending') + '=1', out)
                    self.assertIn(('public' if state == 'promoted_public' else 'memory') + '=1', out)
                    self.assertIn('结构损坏：0', out)

    def test_invalid_tails_still_rejected_without_writes(self):
        for ws in SPACES:
            for field, value in (('优先级', 'high'), ('状态', 'pending'), ('提升', 'memory'), ('复发次数', '12')):
                for tail in (' trailing', ' ', '\t'):
                    with self.subTest(ws=repr(ws), field=field, tail=repr(tail)):
                        self.seed(ws, extra=f'- 复发次数:{ws}12\n')
                        text = self.path.read_text().replace(':' + ws + value + '\n', ':' + ws + value + tail + '\n')
                        self.path.write_text(text)
                        block = self.mod.block_for(text, IDENT)
                        self.assertIsNotNone(self.mod.validate_entry(IDENT, block, 'LEARNINGS.md'))
                        self.assertNotEqual(self.cli('resolve', IDENT, check=False).returncode, 0)
                        self.assertEqual(self.path.read_text(), text)

    def test_blank_values_cannot_consume_next_line(self):
        for ws in SPACES:
            for field in ('优先级', '状态', '提升', '复发次数', '最近出现'):
                with self.subTest(ws=repr(ws), field=field):
                    self.seed(ws, extra=f'- 复发次数:{ws}12\n- 最近出现:{ws}old\n')
                    label = '- ' + field if field in ('复发次数', '最近出现') else '**' + field + '**'
                    text = re.sub(r'^' + re.escape(label) + r':[^\n]*$', lambda _: label + ':' + ws + '\nhigh', self.path.read_text(), flags=re.M)
                    self.path.write_text(text)
                    block = self.mod.block_for(text, IDENT)
                    self.assertIsNotNone(self.mod.validate_entry(IDENT, block, 'LEARNINGS.md'))
                    self.assertNotEqual(self.cli('recur', IDENT, check=False).returncode, 0)
                    self.assertEqual(self.path.read_text(), text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
