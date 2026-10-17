#!/usr/bin/env python3
"""lupi_async.py 离线测试（不联网、不计费）。所有 HTTP 均 mock。"""
import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lupi_async as L  # noqa: E402


def ns(**kw):
    base = dict(key_file=None, mode="generate", prompt="p", model="gpt-image-2.5",
                size="1024x1024", quality="auto", n=1, image=[], idempotency_key=None,
                timeout=30, ids="", id="", interval=1, download=False, output=None,
                out_dir=tempfile.mkdtemp())
    base.update(kw)
    return types.SimpleNamespace(**base)


class KeyResolution(unittest.TestCase):
    def test_env_used_when_no_file(self):
        old = os.environ.get("LUPI_API_KEY")
        os.environ["LUPI_API_KEY"] = "lupi_env"
        try:
            with mock.patch.object(L, "DEFAULT_KEY_FILE", "/nonexistent/x"):
                self.assertEqual(L.resolve_key(ns()), "lupi_env")
        finally:
            os.environ.pop("LUPI_API_KEY", None)
            if old is not None:
                os.environ["LUPI_API_KEY"] = old

    def test_explicit_key_file_wins(self):
        fd, p = tempfile.mkstemp()
        os.write(fd, b"lupi_file\n")
        os.close(fd)
        os.environ["LUPI_API_KEY"] = "lupi_env"
        try:
            self.assertEqual(L.resolve_key(ns(key_file=p)), "lupi_file")
        finally:
            os.environ.pop("LUPI_API_KEY", None)
            os.unlink(p)

    def test_missing_credential_exits(self):
        with mock.patch.object(L, "DEFAULT_KEY_FILE", "/nonexistent/x"), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LUPI_API_KEY", None)
            with self.assertRaises(SystemExit):
                L.resolve_key(ns())


class Multipart(unittest.TestCase):
    def test_fields_and_file(self):
        fd, p = tempfile.mkstemp(suffix=".png")
        os.write(fd, b"\x89PNG fake")
        os.close(fd)
        body, ctype = L.multipart({"model": "m", "async": "true"}, [("image", p)])
        self.assertIn("multipart/form-data; boundary=", ctype)
        b = body.decode("latin-1")
        self.assertIn('name="model"', b)
        self.assertIn("image/png", b)
        self.assertTrue(b.rstrip().endswith("--"))
        os.unlink(p)


class Submit(unittest.TestCase):
    def test_202_task_id_parsed(self):
        payload = json.dumps({"task_id": "api_gen_abc", "status": "queued"}).encode()
        with mock.patch.object(L, "http", return_value=(202, payload)):
            out = L.cmd_submit(ns(), "k")
        self.assertTrue(out["ok"])
        self.assertEqual(out["task_id"], "api_gen_abc")
        self.assertIn("api_gen_abc", out["poll_url"])
        self.assertTrue(out["idempotency_key"].startswith("bf-"))

    def test_401_error_surfaced(self):
        payload = json.dumps({"error": {"code": "invalid_api_key"}}).encode()
        with mock.patch.object(L, "http", return_value=(401, payload)):
            out = L.cmd_submit(ns(), "k")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["error"]["code"], "invalid_api_key")

    def test_edit_requires_image(self):
        with self.assertRaises(SystemExit):
            L.cmd_submit(ns(mode="edit", image=[]), "k")


class Poll(unittest.TestCase):
    def test_summarize_shapes_results(self):
        item = {"id": "api_edit_1", "status": "success", "terminal": True,
                "stage_label": "成功", "results": [{"url": "https://x/y.png",
                                                    "width": 1254, "height": 1254}]}
        s = L.summarize(item)
        self.assertEqual(s["images"][0]["width"], 1254)
        self.assertTrue(s["terminal"])

    def test_running_not_terminal(self):
        s = L.summarize({"id": "x", "status": "running", "terminal": False})
        self.assertFalse(s["terminal"])
        self.assertEqual(s["images"], [])

    def test_poll_multiple_ids(self):
        payload = {"items": [{"id": "a", "status": "running", "terminal": False},
                             {"id": "b", "status": "failed", "terminal": True,
                              "error_code": "upstream_error"}]}
        with mock.patch.object(L, "http", return_value=(200, json.dumps(payload).encode())):
            out = L.cmd_poll(ns(ids="a,b"), "k")
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["items"][1]["error_code"], "upstream_error")


class Download(unittest.TestCase):
    def test_rejects_non_image(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(L, "http", return_value=(200, b"<html>oops</html>")):
            out = L.download("https://x/y.png", os.path.join(d, "a.png"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "not_an_image")
        self.assertFalse(os.path.exists(os.path.join(d, "a.png")))

    def test_no_overwrite(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "a.png")
        with open(p, "wb") as f:
            f.write(b"existing")
        out = L.download("https://x/y.png", p)
        self.assertEqual(out["error"], "output_exists")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"existing")

    def test_downloads_valid_png(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (64, 32), "white").save(buf, "PNG")
        d = tempfile.mkdtemp()
        with mock.patch.object(L, "http", return_value=(200, buf.getvalue())):
            out = L.download("https://x/y.png", os.path.join(d, "a.png"))
        self.assertTrue(out["ok"])
        self.assertEqual((out["width"], out["height"]), (64, 32))
        self.assertTrue(os.path.exists(os.path.join(d, "a.png")))


class Wait(unittest.TestCase):
    def test_timeout_is_ambiguous_not_failure(self):
        payload = {"items": [{"id": "x", "status": "running", "terminal": False}]}
        with mock.patch.object(L, "http", return_value=(200, json.dumps(payload).encode())), \
             mock.patch.object(L.time, "sleep", return_value=None):
            out = L.cmd_wait(ns(id="x", timeout=0), "k")
        self.assertFalse(out["ok"])
        self.assertTrue(out["ambiguous"])
        self.assertTrue(out["timed_out"])

    def test_failed_terminal_is_reported(self):
        payload = {"items": [{"id": "x", "status": "failed", "terminal": True,
                              "error_code": "upstream_error", "public_error": "上游失败"}]}
        with mock.patch.object(L, "http", return_value=(200, json.dumps(payload).encode())):
            out = L.cmd_wait(ns(id="x", timeout=30), "k")
        self.assertFalse(out["ok"])
        self.assertEqual(out["task"]["error_code"], "upstream_error")


class Output(unittest.TestCase):
    def test_stdout_never_leaks_key(self):
        payload = json.dumps({"task_id": "api_gen_abc"}).encode()
        with mock.patch.object(L, "http", return_value=(202, payload)), \
             mock.patch.object(sys, "argv", ["lupi_async.py", "--key-file", "/tmp/none",
                                            "submit", "--prompt", "p"]), \
             mock.patch.object(L, "resolve_key", return_value="lupi_SECRET"), \
             redirect_stdout(io.StringIO()) as buf:
            L.main()
        self.assertNotIn("SECRET", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
