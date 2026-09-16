import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("openminis_image.py")
spec = importlib.util.spec_from_file_location("openminis_image", MODULE_PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class WrapperTests(unittest.TestCase):
    def test_parse_multiple_json_objects(self):
        text = 'noise\n{"media_files": []}\nmore\n{"provider":"智画创","path":"x"}\n'
        self.assertEqual(m.parse_json_from_output(text)["provider"], "智画创")
        self.assertEqual(len(m.parse_json_objects(text)), 2)

    def test_magic_mime_detection(self):
        cases = [(b"\x89PNG\r\n\x1a\nrest", "image/png"), (b"\xff\xd8\xffrest", "image/jpeg"), (b"RIFF1234WEBPrest", "image/webp"), (b"GIF89arest", "image/gif")]
        with tempfile.TemporaryDirectory() as td:
            for idx, (raw, expected) in enumerate(cases):
                path = Path(td) / f"wrong{idx}.bin"
                path.write_bytes(raw)
                self.assertEqual(m.detect_image_mime(path), expected)

    def test_aspect_normalization(self):
        self.assertEqual(m.aspect_from_dims((1254, 1254)), "1:1")
        self.assertEqual(m.aspect_from_dims((1024, 1792)), "4:7")
        self.assertEqual(m.approximate_aspect((1024, 1792)), "约 9:16")

    def test_unknown_extension_cannot_fake_image_mime(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fake.png"
            path.write_text("<html>provider error</html>")
            self.assertIsNone(m.detect_image_mime(path))

    def test_output_rejects_outside_attachments(self):
        with self.assertRaises(SystemExit):
            m.validate_output_path("/tmp/out.png")

    def test_provider_neutral_model_selection(self):
        listing = {
            "models": [
                {"model_id": "gpt-image-2", "instance_label": "first"},
                {"model_id": "gpt-image-2", "instance_label": "second"},
            ]
        }
        class Result:
            returncode = 0
            stdout = json.dumps(listing)
        with patch.object(m.subprocess, "run", return_value=Result()):
            self.assertEqual(m.select_model(), ("gpt-image-2", "first"))

    def test_explicit_provider_is_respected(self):
        listing = {
            "models": [
                {"model_id": "gpt-image-2", "instance_label": "first"},
                {"model_id": "other-image", "instance_label": "chosen"},
            ]
        }
        class Result:
            returncode = 0
            stdout = json.dumps(listing)
        with patch.object(m.subprocess, "run", return_value=Result()):
            self.assertEqual(m.select_model(provider="chosen"), ("other-image", "chosen"))

    def test_missing_explicit_provider_stops(self):
        class Result:
            returncode = 0
            stdout = json.dumps({"models": [{"model_id": "x", "instance_label": "first"}]})
        with patch.object(m.subprocess, "run", return_value=Result()):
            with self.assertRaises(SystemExit):
                m.select_model(provider="missing")

    def test_request_file_is_removed_after_model_returns(self):
        class Result:
            returncode = 1
            stdout = "definitive pre-submit test failure"
        with tempfile.TemporaryDirectory() as td:
            old_workspace = m.WORKSPACE
            try:
                m.WORKSPACE = Path(td)
                self.addCleanup(setattr, m, "ATTACHMENTS", m.ATTACHMENTS)
                m.ATTACHMENTS = Path(td)
                with patch.object(m.subprocess, "run", return_value=Result()):
                    with self.assertRaises(SystemExit):
                        m.run_model_use({"prompt": "private prompt"}, Path(td) / "out.png", "test", "model")
                self.assertEqual(list(Path(td).glob("image_model_use_*.json")), [])
                journal = json.loads(next(Path(td).glob("image_job_*.json")).read_text())
                self.assertTrue(journal["request_file_removed"])
                self.assertNotIn("private prompt", json.dumps(journal))
            finally:
                m.WORKSPACE = old_workspace


class SafetyTests(unittest.TestCase):
    def setUp(self):
        import io
        from types import SimpleNamespace
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'work'
        self.attach = self.root / 'attachments'
        self.attach.mkdir()
        for name, value in [('WORKSPACE', self.work), ('ATTACHMENTS', self.attach)]:
            patcher = patch.object(m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for name, value in [('stdout', self.stdout), ('stderr', self.stderr)]:
            patcher = patch.object(m.sys, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        m.select_model.provider_type = 'OpenAI'
        self.args = SimpleNamespace(size='1200x675', quality='auto', n=1,
            response_format='url', resolution='', extra_body=None,
            model='x', provider='p', prompt='PRIVATE', timeout=10,
            output=str(self.attach / 'out.png'), ref_max_side=32, ref_quality=85)

    def image(self, path, color='red'):
        m.Image.new('RGB', (16, 12), color).save(path, 'PNG')
        return path

    def result(self, code=0, text='{}'):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=code, stdout=text)

    def run_job(self, effect, n=1):
        with patch.object(m.subprocess, 'run', side_effect=effect) as call:
            try:
                return m.run_model_use({'n': n, 'prompt': 'PRIVATE'}, self.attach / 'out.png', 'p', 'x', prompt_text='PRIVATE')
            finally:
                self.assertEqual(call.call_count, 1)
                self.assertFalse(list(self.work.glob('image_model_use_*')))
                for log in self.work.glob('image_job_*'):
                    rec = json.loads(log.read_text())
                    self.assertEqual(Path(rec['stage_path']).exists(), rec['stage_retained'])
                for log in self.work.glob('image_job_*'):
                    self.assertNotIn('PRIVATE', log.read_text())
                    self.assertTrue(json.loads(log.read_text())['request_file_removed'])
                self.assertNotIn('PRIVATE', self.stdout.getvalue() + self.stderr.getvalue())

    def journal(self):
        return json.loads(next(self.work.glob('image_job_*')).read_text())

    def test_timeout_mixed_streams(self):
        for stdout, stderr in [(b'PRIVATE', None), (b'PRIVATE', 'secret'), ('PRIVATE', b'secret')]:
            with self.subTest(stdout=type(stdout).__name__, stderr=type(stderr).__name__):
                with self.assertRaises(SystemExit) as exc:
                    self.run_job(m.subprocess.TimeoutExpired('cmd', 1, output=stdout, stderr=stderr))
                self.assertEqual(exc.exception.code, 3)
        self.assertEqual(len(list(self.work.glob('image_job_*'))), 3)

    def test_nonzero_errors_ambiguous(self):
        for error in ['HTTP 502', '524', '503', 'connection reset', 'timeout', 'unknown failure']:
            with self.subTest(error=error), self.assertRaises(SystemExit) as exc:
                self.run_job(lambda *a, **k: self.result(1, error + ' PRIVATE'))
            self.assertEqual(exc.exception.code, 3)

    def test_zero_json_error_ambiguous(self):
        with self.assertRaises(SystemExit) as exc:
            self.run_job(lambda *a, **k: self.result(text='{"error":"PRIVATE"}'))
        self.assertEqual(exc.exception.code, 3)

    def test_start_failure_cleanup(self):
        with self.assertRaises(SystemExit):
            self.run_job(FileNotFoundError('PRIVATE'))
        self.assertEqual(self.journal()['status'], 'failed_pre_submit')

    def test_interrupt_cleanup(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_job(KeyboardInterrupt())
        self.assertEqual(self.journal()['status'], 'ambiguous')

    def test_unknown_exception_cleanup(self):
        with self.assertRaises(RuntimeError):
            self.run_job(RuntimeError('test'))
        self.assertEqual(self.journal()['status'], 'ambiguous')

    def test_no_output_non_json_terminal(self):
        with self.assertRaises(SystemExit):
            self.run_job(lambda *a, **k: self.result(text='PRIVATE'))
        self.assertEqual(self.journal()['status'], 'ambiguous')

    def test_success_non_json_and_request_permissions(self):
        def cli(cmd, **kwargs):
            req = Path(cmd[cmd.index('--input') + 1])
            self.assertEqual(req.stat().st_mode & 0o777, 0o644)
            self.image(Path(cmd[-1]))
            return self.result(text='PRIVATE')
        result = self.run_job(cli)
        self.assertEqual(result['actual_n'], 1)
        self.assertTrue(result['warnings'])

    def test_multimedia_dedup_invalid_missing(self):
        def cli(cmd, **kwargs):
            stage = Path(cmd[-1]).parent
            self.image(stage / 'result.png')
            self.image(stage / 'second.png', 'blue')
            (stage / 'bad.png').write_bytes(b'not image')
            return self.result(text=json.dumps({'media_files': [
                {'path': str(stage / 'result.png')}, {'url': m.minis_url(stage / 'second.png')},
                'second.png', 'bad.png', 'missing.png']}))
        result = self.run_job(cli, n=3)
        self.assertEqual(result['actual_n'], 2)
        self.assertEqual(len(result['images']), 2)
        self.assertTrue(result['warnings'])

    def test_old_media_not_accepted(self):
        old = self.image(self.attach / 'old.png')
        before = old.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_job(lambda *a, **k: self.result(text=json.dumps({'media_files': [str(old)]})))
        self.assertEqual(old.read_bytes(), before)

    def test_existing_destination_rejected_before_run(self):
        old = self.image(self.attach / 'out.png')
        before = old.read_bytes()
        with patch.object(m.subprocess, 'run') as call, self.assertRaises(SystemExit):
            m.run_model_use({}, old, 'p', 'x')
        call.assert_not_called()
        self.assertEqual(old.read_bytes(), before)

    def test_directory_and_symlink_rejected(self):
        (self.attach / 'link.png').symlink_to(self.attach / 'missing.png')
        for path in [self.attach, self.attach / 'link.png', self.root / 'outside.png']:
            with self.subTest(path=str(path)), self.assertRaises(SystemExit):
                m.validate_output_path(path)

    def test_encoded_nested_url(self):
        self.assertEqual(m.minis_url(self.attach / '子目录' / '测试 图.png'),
            'minis://attachments/%E5%AD%90%E7%9B%AE%E5%BD%95/%E6%B5%8B%E8%AF%95%20%E5%9B%BE.png')

    def test_truncated_image_rejected(self):
        path = self.image(self.attach / 'truncated.png')
        path.write_bytes(path.read_bytes()[:50])
        self.assertIsNone(m.image_dimensions(path))

    def test_dependency_gate(self):
        with patch.object(m, 'Image', None), patch.object(m.subprocess, 'run') as call:
            with self.assertRaises(SystemExit):
                m.generate(self.args)
        call.assert_not_called()

    def test_extra_core_fields_rejected(self):
        for key in ['n', 'model', 'prompt', 'messages', 'images', 'generation_config', 'passthrough', 'endpoint', 'size', 'tools', 'extra_body']:
            self.args.extra_body = json.dumps({key: 100})
            with self.subTest(key=key), self.assertRaises(SystemExit):
                m.build_common(self.args, 'x')

    def test_extra_nested_correctly(self):
        self.args.extra_body = '{"seed": 42}'
        self.assertEqual(m.build_common(self.args, 'x')['extra_body'], {'seed': 42})

    def test_gemini_config(self):
        m.select_model.provider_type = 'Gemini'
        self.args.resolution = '2K'
        result = m.build_common(self.args, 'x')
        self.assertEqual(result, {'generation_config': {'number_of_images': 1, 'aspect_ratio': '16:9', 'image_size': '2K'}})
        self.args.n = 5
        with self.assertRaises(SystemExit):
            m.build_common(self.args, 'x')

    def test_openai_ratio_rejected(self):
        self.args.size = '16:9'
        with self.assertRaises(SystemExit):
            m.build_common(self.args, 'x')

    def test_special_parameters(self):
        self.assertIn('messages', m.special_payload(self.args))
        for key, value in [('quality', 'hd'), ('resolution', '4K'), ('n', 2), ('extra_body', '{}'), ('response_format', 'b64_json')]:
            old = getattr(self.args, key)
            setattr(self.args, key, value)
            with self.subTest(key=key), self.assertRaises(SystemExit):
                m.special_payload(self.args)
            setattr(self.args, key, old)

    def test_explicit_model_disambiguation(self):
        listing = {'models': [{'model_id': 'x', 'entry_id': 'id1', 'display_name': 'first', 'instance_label': 'p'},
                              {'model_id': 'x', 'entry_id': 'id2', 'display_name': 'second', 'instance_label': 'q'}]}
        with patch.object(m.subprocess, 'run', return_value=self.result(text=json.dumps(listing))):
            with self.assertRaises(SystemExit):
                m.select_model('x')
            for selector in ['id2', 'second', 'q/x']:
                self.assertEqual(m.select_model(selector), ('id2', 'q'))
            self.assertEqual(m.select_model('x', 'p'), ('id1', 'p'))

    def test_edit_cleanup_and_openai_uri(self):
        ref = self.image(self.attach / 'reference.png')
        self.args.image = [str(ref)]
        def run(payload, *a):
            self.assertTrue(payload['images'][0].startswith('data:image/jpeg;base64,'))
            raise SystemExit(3)
        with patch.object(m, 'select_model', return_value=('x', 'p')), patch.object(m, 'run_model_use', side_effect=run):
            with self.assertRaises(SystemExit):
                m.edit(self.args)
        self.assertFalse(list(self.work.glob('i2i_ref_*')))
        self.assertTrue(ref.exists())

    def test_edit_partial_preparation_cleanup(self):
        ref = self.image(self.attach / 'reference.png')
        self.args.image = [str(ref), str(self.attach / 'missing.png')]
        with patch.object(m, 'select_model', return_value=('x', 'p')), self.assertRaises(SystemExit):
            m.edit(self.args)
        self.assertFalse(list(self.work.glob('i2i_ref_*')))
        self.assertTrue(ref.exists())


class RetentionTests(SafetyTests):
    def test_failure_keeps_images(self):
        for mode in ['nonzero', 'json', 'timeout']:
            def cli(cmd, **kwargs):
                self.image(Path(cmd[-1]))
                if mode == 'timeout':
                    raise m.subprocess.TimeoutExpired('cmd', 1)
                return self.result(1 if mode == 'nonzero' else 0, '{"error":"PRIVATE"}')
            with self.subTest(mode=mode), self.assertRaises(SystemExit):
                self.run_job(cli)
        for log in self.work.glob('image_job_*'):
            rec = json.loads(log.read_text())
            self.assertEqual(rec['status'], 'ambiguous')
            self.assertTrue(m.image_dimensions(rec['verified_media'][0]['path']))

    def test_copy_failure_has_no_formal_fragment(self):
        def cli(cmd, **kwargs):
            self.image(Path(cmd[-1]))
            return self.result()
        def broken(src, dst):
            dst.write(b'partial')
            raise OSError('PRIVATE')
        with patch.object(m.shutil, 'copyfileobj', side_effect=broken), self.assertRaises(OSError):
            self.run_job(cli)
        self.assertFalse((self.attach / 'out.png').exists())
        self.assertFalse(list(self.attach.glob('.image_publish_*')))
        self.assertTrue(m.image_dimensions(self.journal()['verified_media'][0]['path']))

    def test_second_publish_failure_logs_first(self):
        def cli(cmd, **kwargs):
            self.image(Path(cmd[-1]))
            self.image(Path(cmd[-1]).parent / 'second.png', 'blue')
            return self.result()
        real_link = m.os.link
        count = 0
        def link(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('mock failure')
            real_link(src, dst)
        with patch.object(m.os, 'link', side_effect=link), self.assertRaises(OSError):
            self.run_job(cli, n=2)
        rec = self.journal()
        self.assertEqual(len(rec['images']), 1)
        self.assertEqual(len(rec['verified_media']), 2)
        self.assertTrue(m.image_dimensions(rec['images'][0]['path']))

    def test_publish_race_does_not_overwrite(self):
        def cli(cmd, **kwargs):
            self.image(Path(cmd[-1]))
            return self.result()
        real_link = m.os.link
        def link(src, dst):
            Path(dst).write_bytes(b'existing')
            real_link(src, dst)
        with patch.object(m.os, 'link', side_effect=link), self.assertRaises(FileExistsError):
            self.run_job(cli)
        self.assertEqual((self.attach / 'out.png').read_bytes(), b'existing')

    def test_recovery_candidates_strict(self):
        good = 'minis://attachments/a%20b.png'
        bad = ['https://remote/?key=PRIVATE', 'minis://attachments/../a',
               'minis://attachments/%2e%2e/a', 'minis://attachments/a?key=PRIVATE',
               'minis://attachments/a#PRIVATE', 'minis://attachments/%252e%252e/a',
               'minis://attachments/a%00b', 'minis://attachments/a%zz']
        got = m.recovery_candidates([good, *bad])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]['minis_url'], good)
        self.assertFalse(got[0]['verified'])
        with self.assertRaises(SystemExit):
            self.run_job(lambda *a, **k: self.result(1, json.dumps({'media': [good, *bad]})))
        self.assertEqual(self.journal()['recovery_candidates'], got)

    def test_size_quality_local_validation(self):
        for size in ['nonsense', '', '-1x2', '0x1', '1x0', '1.5x2', '1X2', ' 1x2']:
            self.args.size = size
            with self.subTest(size=size), self.assertRaises(SystemExit):
                m.build_common(self.args, 'x')
        for size in ['auto', '1x2', '1200x675']:
            self.args.size = size
            self.assertEqual(m.build_common(self.args, 'x')['size'], size)
        self.args.quality = 'INVALID'
        with self.assertRaises(SystemExit):
            m.build_common(self.args, 'x')

    def test_stage_cleanup_failure_reported(self):
        def cli(cmd, **kwargs):
            self.assertEqual(Path(cmd[-1]).parent.stat().st_mode & 0o777, 0o777)
            self.image(Path(cmd[-1]))
            return self.result()
        with patch.object(m.shutil, 'rmtree', side_effect=OSError('PRIVATE')):
            result = self.run_job(cli)
        self.assertEqual(result['cleanup_status'], 'failed')
        self.assertEqual(self.journal()['cleanup_errors'][0]['operation'], 'remove_stage')

    def test_exact_ratio_not_common_approximation(self):
        self.assertEqual(m.aspect_from_dims((960, 1672)), '120:209')
        self.assertEqual(m.approximate_aspect((960, 1672)), '约 9:16')


class SignalProcessTests(unittest.TestCase):
    def test_real_sigterm_direct_generate_edit(self):
        import subprocess
        import sys
        for mode in ['run', 'generate', 'edit']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                # Real child interpreter and real SIGTERM, but no model CLI/network.
                code = '''import importlib.util, pathlib, os, signal, sys
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location('wrapper', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = pathlib.Path(sys.argv[2]); m.WORKSPACE = r/'work'; m.ATTACHMENTS = r/'attachments'; m.ATTACHMENTS.mkdir()
historical = m.ATTACHMENTS/'.image_job_history'; historical.mkdir(); (historical/'keep').write_text('keep')
def cli(cmd, **kwargs):
    m.Image.new('RGB', (9, 7)).save(cmd[-1], 'PNG')
    os.kill(os.getpid(), signal.SIGTERM)
m.subprocess.run = cli
m.select_model = lambda *a: ('x', 'p')
a = SimpleNamespace(model='x', provider='p', n=1, size='auto', quality='auto', response_format='url', resolution='', extra_body=None, prompt='PRIVATE', output=str(m.ATTACHMENTS/'out.png'), timeout=5, ref_max_side=32, ref_quality=85)
ref = m.ATTACHMENTS/'ref.png'; m.Image.new('RGB', (10,10)).save(ref); a.image=[str(ref)]
try:
    if sys.argv[3] == 'run': m.run_model_use({'prompt':'PRIVATE'}, a.output, 'p', 'x')
    else: getattr(m, sys.argv[3])(a)
except m.TaskTerminated:
    sys.exit(143)
'''
                p = subprocess.run([sys.executable, '-c', code, str(MODULE_PATH), td, mode], capture_output=True, text=True, timeout=10)
                self.assertEqual(p.returncode, 143, p.stderr)
                root = Path(td)
                rec = json.loads(next((root/'work').glob('image_job_*')).read_text())
                self.assertEqual(rec['status'], 'ambiguous')
                self.assertFalse(rec['remote_cancelled'])
                self.assertTrue(rec['request_file_removed'])
                self.assertTrue(m.image_dimensions(rec['verified_media'][0]['path']))
                self.assertFalse(list((root/'work').glob('i2i_ref_*')))
                self.assertTrue((root/'attachments/ref.png').exists())
                self.assertTrue((root/'attachments/.image_job_history/keep').exists())
                self.assertNotIn('PRIVATE', p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
