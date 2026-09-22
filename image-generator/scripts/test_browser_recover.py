import base64
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

P = Path(__file__).with_name("browser_recover.py")
spec = importlib.util.spec_from_file_location("browser_recover", P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def png_bytes(size=(1, 1), color=(1, 2, 3, 255)):
    stream = io.BytesIO()
    Image.new("RGBA", size, color).save(stream, "PNG")
    return stream.getvalue()


def envelope(raw):
    b64 = base64.b64encode(raw).decode("ascii")
    return json.dumps({"status": "ok", "data": {"text": "data:image/png;base64," + b64}})


def opened(tab=0, url='minis://attachments/a.png'):
    return json.dumps({'ok': True, 'tool': 'minis-browser-use', 'action': 'new_tab',
                       'data': {'success': True, 'text': f'Opened new tab {tab} at {url}. Use tab_id: {tab} to target this tab.'}})


def completed(stdout="", code=0):
    return mock.Mock(stdout=stdout, returncode=code)


class ParseTests(unittest.TestCase):
    def test_parse_real_nested_json_envelope(self):
        image = png_bytes()
        raw = "diagnostic\n" + json.dumps({"data": {"result": {"text": "data:image/png;base64," + base64.b64encode(image).decode()}}})
        self.assertEqual(m.data_url_from_output(raw), (image, "png"))

    def test_real_cli_escaped_slashes_and_tab_footer(self):
        image = png_bytes((2, 2), (255, 0, 0, 255))
        text = 'data:image/png;base64,' + base64.b64encode(image).decode() + '\n  tab_id: 0'
        raw = json.dumps({'data': {'text': text, 'success': True}}).replace('/', r'\/')
        self.assertIn(r'\/', raw)
        self.assertEqual(m.data_url_from_output(raw), (image, 'png'))
        self.assertIsNone(m.tab_id_from_output(raw))

    def test_invalid_suffix_is_not_silently_truncated(self):
        for suffix in ('!', '_bad', '\n  tab_id: invalid', '\n  tab_id: 0\nextra'):
            with self.subTest(suffix=suffix):
                text = 'data:image/png;base64,' + base64.b64encode(png_bytes()).decode() + suffix
                self.assertIsNone(m.data_url_from_output(json.dumps({'data': {'text': text}})))

    def test_wrapped_base64_and_resource_limits(self):
        image = png_bytes()
        encoded = base64.b64encode(image).decode()
        text = 'data:image/png;base64,' + '\n'.join(encoded[i:i+20] for i in range(0, len(encoded), 20))
        self.assertEqual(m.data_url_from_output(text), (image, 'png'))
        with mock.patch.object(m, 'MAX_IMAGE_BYTES', 4):
            self.assertIsNone(m.data_url_from_output(text))
        with mock.patch.object(m, 'MAX_CLI_TEXT', 4):
            self.assertIsNone(m.data_url_from_output(text))
        with mock.patch.object(m, 'MAX_PIXELS', 1), self.assertRaises(ValueError):
            m.validate_image(png_bytes((2, 2)), 'png')

    def test_parse_bad_base64_rejected(self):
        self.assertIsNone(m.data_url_from_output('{"data":{"text":"data:image/png;base64,AAAA=AAA"}}'))

    def test_fake_png_rejected_by_pillow(self):
        fake = b"\x89PNG\r\n\x1a\n" + b"x" * 3000
        with self.assertRaises(ValueError):
            m.validate_image(fake, "png")

    def test_small_valid_png_is_accepted(self):
        image = png_bytes()
        self.assertLess(len(image), 2048)
        m.validate_image(image, "png")

    def test_tab_id_json_and_text(self):
        self.assertIsNone(m.tab_id_from_output('{"data":{"tab_id":12}}'))
        self.assertIsNone(m.tab_id_from_output("Opened new tab 19; use tab_id: 19"))
        self.assertEqual(m.tab_id_from_output(opened(19, 'about:blank')), '19')
        self.assertIsNone(m.tab_id_from_output('{"data":{"text":"done"}}'))

    def test_canvas_description_is_explicit(self):
        self.assertIn("not restoration of the original bytes", m.__doc__)


class PathTests(unittest.TestCase):
    def test_url_canonical_percent_encoding(self):
        self.assertEqual(m.validate_media_url("minis://attachments/子目录/测试 图.png"),
                         "minis://attachments/%E5%AD%90%E7%9B%AE%E5%BD%95/%E6%B5%8B%E8%AF%95%20%E5%9B%BE.png")
        self.assertEqual(m.validate_media_url("minis://attachments/a%20b.png"),
                         "minis://attachments/a%20b.png")

    def test_url_rejects_wrong_root_traversal_and_encoded_separator(self):
        bad = ["https://x/a.png", "minis://workspace/a.png",
               "minis://attachments/../x.png", "minis://attachments/%2e%2e/x.png",
               "minis://attachments/a%2Fb.png", "minis://attachments/a.png?q=1",
               "minis://attachments/%ZZ.png"]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.validate_media_url(value)

    def test_output_requires_new_file_below_attachments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(m, "ATTACHMENTS", root):
                target = root / "new.png"
                self.assertEqual(m.validate_output_path(str(target)), target)
                target.write_bytes(b"old")
                with self.assertRaises(FileExistsError):
                    m.validate_output_path(str(target))
                with self.assertRaises(ValueError):
                    m.validate_output_path(str(root))
                with self.assertRaises(ValueError):
                    m.validate_output_path(str(root.parent / "escape.png"))

    def test_output_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "link").symlink_to(outside)
            with mock.patch.object(m, "ATTACHMENTS", root):
                with self.assertRaises(ValueError):
                    m.validate_output_path(str(root / "link" / "x.png"))

    def test_offload_decodes_url_and_blocks_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = png_bytes()
            off = root / "有 空格.json"
            off.write_text(envelope(image), encoding="utf-8")
            with mock.patch.object(m, "OFFLOADS", root):
                got = m.data_url_from_output("saved minis://offloads/%E6%9C%89%20%E7%A9%BA%E6%A0%BC.json")
                self.assertEqual(got, (image, "png"))
                self.assertEqual(m.offload_candidates("minis://offloads/%2e%2e/secret"), [])

    def test_malformed_offload_does_not_abort_inline_image(self):
        raw = 'minis://offloads/%ZZ.json\n' + envelope(png_bytes())
        self.assertEqual(m.data_url_from_output(raw), (png_bytes(), 'png'))

    def test_offload_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            secret = Path(outside) / "secret.json"
            secret.write_text(envelope(png_bytes()), encoding="utf-8")
            (root / "link.json").symlink_to(secret)
            with mock.patch.object(m, "OFFLOADS", root):
                self.assertEqual(m.offload_candidates("minis://offloads/link.json"), [])


class RecoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.attach_patch = mock.patch.object(m, "ATTACHMENTS", self.root)
        self.attach_patch.start()

    def tearDown(self):
        self.attach_patch.stop()
        self.tmp.cleanup()

    def test_missing_tab_id_never_executes_or_closes_default(self):
        calls = []
        def fake_run(args, timeout=120):
            calls.append(args)
            return completed('{"status":"ok"}')
        with mock.patch.object(m, "run", fake_run):
            ok, message = m.recover("minis://attachments/a.png", str(self.root / "out.png"), 1)
        self.assertFalse(ok)
        self.assertIn("dedicated tab ID", message)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "new_tab")

    def test_success_uses_tab_and_accepts_tiny_png(self):
        image = png_bytes()
        calls = []
        responses = [completed(opened(7, 'minis://attachments/%E6%B5%8B%E8%AF%95%20%E5%9B%BE.png')), completed(envelope(image)), completed()]
        def fake_run(args, timeout=120):
            calls.append(args)
            return responses.pop(0)
        target = self.root / "result.png"
        with mock.patch.object(m, "run", fake_run):
            ok, message = m.recover("minis://attachments/测试 图.png", str(target), 1)
        self.assertTrue(ok)
        self.assertEqual(target.read_bytes(), image)
        self.assertIn("not original bytes", message)
        self.assertIn("--tab-id", calls[1]); self.assertIn("7", calls[1])
        self.assertEqual(calls[-1][1:3], ["close_tab", "--tab-id"])
        self.assertIn("%E6%B5%8B%E8%AF%95%20%E5%9B%BE.png", calls[0][-1])

    def test_existing_output_not_opened_or_overwritten(self):
        target = self.root / "result.png"
        target.write_bytes(b"keep")
        with mock.patch.object(m, "run") as runner:
            ok, _ = m.recover("minis://attachments/a.png", str(target), 1)
        self.assertFalse(ok); runner.assert_not_called()
        self.assertEqual(target.read_bytes(), b"keep")

    def test_fake_png_not_published(self):
        fake = b"\x89PNG\r\n\x1a\n" + b"x" * 3000
        responses = [completed(opened(3)), completed(envelope(fake)), completed()]
        with mock.patch.object(m, "run", side_effect=responses):
            ok, _ = m.recover("minis://attachments/a.png", str(self.root / "bad.png"), 1)
        self.assertFalse(ok)
        self.assertFalse((self.root / "bad.png").exists())

    def test_close_exception_does_not_hide_success(self):
        image = png_bytes()
        responses = iter([completed(opened(4)), completed(envelope(image))])
        def fake_run(args, timeout=120):
            if args[1] == "close_tab":
                raise RuntimeError("close broke")
            return next(responses)
        with mock.patch.object(m, "run", fake_run):
            ok, message = m.recover("minis://attachments/a.png", str(self.root / "ok.png"), 1)
        self.assertTrue(ok)
        self.assertIn("recovered", message)

    def test_close_interrupt_preserves_committed_success(self):
        responses = [completed(opened(0)), completed(envelope(png_bytes())), KeyboardInterrupt()]
        with mock.patch.object(m, 'run', side_effect=responses):
            ok, message = m.recover('minis://attachments/a.png', str(self.root / 'ok.png'), 1)
        self.assertTrue(ok)
        self.assertIn('close raised', message)

    def test_failed_open_with_known_id_is_not_closed(self):
        with mock.patch.object(m, 'run', return_value=completed(opened(0), 1)) as runner:
            ok, _ = m.recover('minis://attachments/a.png', str(self.root / 'out.png'), 1)
        self.assertFalse(ok)
        self.assertEqual(runner.call_count, 1)

    def test_keyboard_interrupt_closes_dedicated_tab(self):
        calls = []
        def runner(args, timeout=120):
            calls.append(args)
            if args[1] == 'new_tab':
                return completed(opened(0))
            if args[1] == 'execute_js':
                raise KeyboardInterrupt()
            raise RuntimeError('close also failed')
        with mock.patch.object(m, 'run', runner), self.assertRaises(KeyboardInterrupt):
            m.recover('minis://attachments/a.png', str(self.root / 'out.png'), 1)
        self.assertEqual(calls[-1][1:], ['close_tab', '--tab-id', '0'])

    def test_publish_interrupt_removes_temp_before_and_after_commit(self):
        for committed in (False, True):
            target = self.root / ('after.png' if committed else 'before.png')
            original_link = os.link
            def link(*args, **kwargs):
                original_link(*args, **kwargs)
                raise KeyboardInterrupt()
            hook = mock.patch.object(m.os, 'link', side_effect=link) if committed else mock.patch.object(m.os, 'fsync', side_effect=KeyboardInterrupt)
            with hook, self.assertRaises(KeyboardInterrupt):
                m.publish_exclusive(target, png_bytes())
            self.assertEqual(list(self.root.glob('.browser-recover-*.tmp')), [])
            self.assertEqual(target.exists(), committed)
            if committed:
                self.assertEqual(target.read_bytes(), png_bytes())

    def test_sigterm_subprocess_unwinds_browser_and_publish(self):
        for stage in ('execute', 'fsync'):
            code = '''
import importlib.util, os, signal, sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
spec = importlib.util.spec_from_file_location('recover', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = Path(sys.argv[2]); m.ATTACHMENTS = root
stage = sys.argv[3]
def runner(args, timeout=120):
    if args[1] == 'new_tab':
        return SimpleNamespace(returncode=0, stdout='{"ok":true,"tool":"minis-browser-use","action":"new_tab","data":{"success":true,"text":"Opened new tab 0 at minis://attachments/a.png. Use tab_id: 0 to target this tab."}}')
    if args[1] == 'close_tab':
        (root / ('closed-' + stage)).touch()
        return SimpleNamespace(returncode=0, stdout='')
    if stage == 'execute':
        os.kill(os.getpid(), signal.SIGTERM)
    return SimpleNamespace(returncode=0, stdout=sys.argv[4])
def interrupt(fd):
    os.kill(os.getpid(), signal.SIGTERM)
with mock.patch.object(m, 'run', runner), mock.patch.object(m.os, 'fsync', interrupt):
    m.recover('minis://attachments/a.png', str(root / (stage + '.png')), 1)
'''
            result = subprocess.run([sys.executable, '-B', '-c', code, str(P), str(self.root), stage, envelope(png_bytes())], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 143, result.stderr)
            self.assertTrue((self.root / ('closed-' + stage)).exists())
            self.assertFalse((self.root / (stage + '.png')).exists())
            self.assertEqual(list(self.root.glob('.browser-recover-*.tmp')), [])

    def test_signal_handler_restored(self):
        previous = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(SystemExit) as caught:
            with m.termination_cleanup():
                os.kill(os.getpid(), signal.SIGTERM)
        self.assertEqual(caught.exception.code, 143)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_atomic_publish_race_refuses_overwrite(self):
        target = self.root / "race.png"
        target.write_bytes(b"winner")
        with self.assertRaises(FileExistsError):
            m.publish_exclusive(target, png_bytes())
        self.assertEqual(target.read_bytes(), b"winner")
        self.assertEqual(list(self.root.glob(".browser-recover-*.tmp")), [])


@unittest.skipUnless(os.environ.get('BROWSER_RECOVER_LIVE_TEST') == '1', 'opt-in free blank-page Canvas CLI test')
class LiveCliTests(unittest.TestCase):
    def test_blank_canvas_real_cli_envelope(self):
        opened = m.run(['minis-browser-use', 'new_tab', '--url', 'about:blank'], 30)
        tab = m.tab_id_from_output(opened.stdout)
        self.assertIsNotNone(tab, 'no dedicated tab ID; never use default')
        try:
            self.assertEqual(opened.returncode, 0)
            result = m.run(['minis-browser-use', 'execute_js', '--tab-id', tab, '--script',
                            "var c=document.createElement('canvas');c.width=2;c.height=2;"
                            "c.getContext('2d').fillRect(0,0,2,2);return c.toDataURL('image/png');"], 30)
            self.assertEqual(result.returncode, 0)
            candidate = m.data_url_from_output(result.stdout)
            self.assertIsNotNone(candidate)
            m.validate_image(*candidate)
            with Image.open(io.BytesIO(candidate[0])) as image:
                self.assertEqual(image.size, (2, 2))
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'canvas.png'
                with mock.patch.object(m, 'ATTACHMENTS', Path(directory)):
                    m.publish_exclusive(target, candidate[0])
                self.assertEqual(target.read_bytes(), candidate[0])
                self.assertEqual(list(Path(directory).glob('.browser-recover-*.tmp')), [])
        finally:
            closed = m.run(['minis-browser-use', 'close_tab', '--tab-id', tab], 15)
            self.assertEqual(closed.returncode, 0, 'dedicated live-test tab close failed')


class HardenedTests(unittest.TestCase):
    def test_creation_rejects_error_unrelated_conflicting_and_duplicate_ids(self):
        good = json.loads(opened(3, 'about:blank'))
        cases = [json.dumps({'ok': False, 'error': {'tab_id': 2}}),
                 json.dumps({'data': {'tabs': [{'tab_id': 2}]}}),
                 opened(3, 'about:blank') + opened(4, 'about:blank'),
                 opened(3, 'about:blank').replace('tab_id: 3', 'tab_id: 4'),
                 opened(3, 'about:blank').replace('"ok": true', '"ok": false, "ok": true')]
        good['data']['tab_id'] = 5
        cases.append(json.dumps(good))
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(m.tab_id_from_output(text))

    def test_png_truncated_iend_crc_and_trailing_data(self):
        raw = png_bytes()
        for bad in [raw[:-1], raw[:-8], raw[:-12], raw + b'x', raw[:-1] + bytes([raw[-1] ^ 1])]:
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                m.validate_image(bad, 'png')

    def test_parent_replacement_cannot_redirect_publish(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory); parent = root / 'p'; parent.mkdir()
            original = os.link
            def swap(src, dst, **kwargs):
                parent.rename(root / 'pinned')
                parent.symlink_to(outside)
                return original(src, dst, **kwargs)
            with mock.patch.object(m, 'ATTACHMENTS', root), mock.patch.object(m.os, 'link', side_effect=swap):
                m.publish_exclusive(parent / 'image.png', png_bytes())
            self.assertFalse((Path(outside) / 'image.png').exists())
            self.assertEqual((root / 'pinned' / 'image.png').read_bytes(), png_bytes())
            self.assertEqual(list((root / 'pinned').glob('*.tmp')), [])

    def test_offload_swap_and_growth_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'data'; source.write_text('abc')
            with mock.patch.object(m, 'OFFLOADS', root):
                self.assertEqual(m._safe_offload(str(source)), source)
                source.unlink(); source.symlink_to('/etc/passwd')
                with self.assertRaises(OSError):
                    m.read_offload(source)
                source.unlink(); source.write_bytes(b'x' * 65)
                with mock.patch.object(m, 'MAX_OFFLOAD_BYTES', 64), self.assertRaises(ValueError):
                    m.read_offload(source)

    def test_stream_limit_and_timeout(self):
        with mock.patch.object(m, 'MAX_CLI_TEXT', 128), self.assertRaises(ValueError):
            m.run([sys.executable, '-c', 'import os; os.write(1,b"x"*4096)'], 30)
        with self.assertRaises(subprocess.TimeoutExpired):
            m.run([sys.executable, '-c', 'import time; time.sleep(10)'], 0.1)

    def test_canvas_checks_precede_allocation(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(m, 'ATTACHMENTS', Path(directory)):
            responses = [completed(opened()), completed(), completed()]
            with mock.patch.object(m, 'run', side_effect=responses) as runner:
                m.recover('minis://attachments/a.png', str(Path(directory) / 'out.png'), 1)
            script = runner.call_args_list[1].args[0][-1]
            self.assertIn('document.contentType', script)
            self.assertIn('location.href!==expected', script)
            self.assertIn('i.currentSrc||i.src', script)
            self.assertNotIn("querySelector('img')", script)
            self.assertLess(script.index('w>16384'), script.index("createElement('canvas')"))
            self.assertLess(script.index('w*h>'), script.index("createElement('canvas')"))


if __name__ == "__main__":
    unittest.main()
