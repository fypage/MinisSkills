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
                out_dir=tempfile.mkdtemp(), limit=20,
                transport="direct", provider_model="噜皮生图/gpt-image-2")
    base.update(kw)
    return types.SimpleNamespace(**base)


def ctx(transport="direct", key="k"):
    return L.Ctx(transport, key, "噜皮生图/gpt-image-2")


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

    def test_auto_without_key_falls_back_to_provider(self):
        with mock.patch.object(L, "DEFAULT_KEY_FILE", "/nonexistent/x"), \
             mock.patch.object(L, "resolve_key", return_value=None):
            c = L.build_ctx(ns(transport="auto"))
        self.assertEqual(c.transport, "provider")
        self.assertIsNone(c.key)

    def test_direct_without_key_exits(self):
        with mock.patch.object(L, "DEFAULT_KEY_FILE", "/nonexistent/x"), \
             mock.patch.object(L, "resolve_key", return_value=None):
            with self.assertRaises(SystemExit):
                L.build_ctx(ns(transport="direct"))


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
        with mock.patch.object(L, "_direct", return_value=(202, payload)):
            out = L.cmd_submit(ns(), ctx())
        self.assertTrue(out["ok"])
        self.assertEqual(out["task_id"], "api_gen_abc")
        self.assertIn("api_gen_abc", out["poll_url"])
        self.assertTrue(out["idempotency_key"].startswith("bf-"))
        self.assertEqual(out["transport"], "direct")

    def test_idempotency_key_is_forwarded(self):
        payload = json.dumps({"task_id": "api_gen_abc"}).encode()
        seen = {}

        def fake(url, data, headers, timeout):
            seen.update(headers)
            return 202, payload
        with mock.patch.object(L, "_direct", side_effect=fake):
            L.cmd_submit(ns(idempotency_key="bf-fixed"), ctx())
        self.assertEqual(seen["Idempotency-Key"], "bf-fixed")

    def test_401_error_surfaced(self):
        payload = json.dumps({"error": {"code": "invalid_api_key"}}).encode()
        with mock.patch.object(L, "_direct", return_value=(401, payload)):
            out = L.cmd_submit(ns(), ctx())
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["error"]["code"], "invalid_api_key")

    def test_edit_without_image_is_structured_error(self):
        out = L.cmd_submit(ns(mode="edit", image=[]), ctx())
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "edit_requires_image")

    def test_edit_refused_on_provider_transport(self):
        out = L.cmd_submit(ns(mode="edit", image=["/tmp/a.png"]), ctx("provider"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "edit_needs_direct_transport")


class ProviderTransport(unittest.TestCase):
    def test_passthrough_payload_shape(self):
        captured = {}

        def fake_run(cmd, **kw):
            with open(cmd[cmd.index("--input") + 1]) as f:
                captured["payload"] = json.load(f)
            out = cmd[cmd.index("--output") + 1]
            with open(out, "wb") as f:
                f.write(json.dumps({"items": []}).encode())
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({"http_status": 200}),
                                         stderr="")
        with mock.patch.object(L.subprocess, "run", side_effect=fake_run):
            status, raw = L.call(ctx("provider"), "/api/image-tasks?ids=a", "GET")
        self.assertEqual(status, 200)
        pv = captured["payload"]["passthrough"]
        self.assertEqual(pv["endpoint"], "/api/image-tasks?ids=a")
        self.assertEqual(pv["method"], "GET")
        self.assertEqual(pv["body_mode"], "replace")

    def test_provider_generate_body_passed_through(self):
        captured = {}

        def fake_run(cmd, **kw):
            with open(cmd[cmd.index("--input") + 1]) as f:
                captured["payload"] = json.load(f)
            with open(cmd[cmd.index("--output") + 1], "wb") as f:
                f.write(json.dumps({"task_id": "api_gen_zzz", "status": "queued"}).encode())
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({"http_status": 202}),
                                         stderr="")
        with mock.patch.object(L.subprocess, "run", side_effect=fake_run):
            out = L.cmd_submit(ns(), ctx("provider"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["task_id"], "api_gen_zzz")
        self.assertEqual(captured["payload"]["passthrough"]["body"]["async"], "true")

    def test_cli_failure_is_transport_error(self):
        with mock.patch.object(L.subprocess, "run",
                               return_value=types.SimpleNamespace(returncode=2, stdout="",
                                                                  stderr="boom")):
            status, raw = L.call(ctx("provider"), "/v1/models", "GET")
        self.assertEqual(status, -1)
        self.assertIn("transport_error", json.loads(raw))


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
        with mock.patch.object(L, "_direct", return_value=(200, json.dumps(payload).encode())):
            out = L.cmd_poll(ns(ids="a,b"), ctx())
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["items"][1]["error_code"], "upstream_error")


class ListAndCancel(unittest.TestCase):
    def test_list_hits_collection_endpoint(self):
        seen = {}

        def fake(url, data, headers, timeout):
            seen["url"] = url
            return 200, json.dumps({"items": [{"id": "x", "status": "success"}]}).encode()
        with mock.patch.object(L, "_direct", side_effect=fake):
            out = L.cmd_list(ns(limit=5), ctx())
        self.assertIn("/api/image-tasks?limit=5", seen["url"])
        self.assertEqual(out["count"], 1)

    def test_cancel_posts_to_task_path(self):
        seen = {}

        def fake(url, data, headers, timeout):
            seen["url"], seen["data"] = url, data
            return 200, json.dumps({"id": "api_gen_1", "status": "cancelled"}).encode()
        with mock.patch.object(L, "_direct", side_effect=fake):
            out = L.cmd_cancel(ns(id="api_gen_1"), ctx())
        self.assertTrue(out["ok"])
        self.assertTrue(seen["url"].endswith("/api/image-tasks/api_gen_1/cancel"))
        self.assertEqual(json.loads(seen["data"]), {"reason": "user"})

    def test_cancel_reports_http_error(self):
        with mock.patch.object(L, "_direct", return_value=(405, b'{"error":"method"}')):
            out = L.cmd_cancel(ns(id="x"), ctx())
        self.assertFalse(out["ok"])
        self.assertEqual(out["http"], 405)


class Download(unittest.TestCase):
    def test_rejects_non_image(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(L, "_direct", return_value=(200, b"<html>oops</html>")):
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
        with mock.patch.object(L, "_direct", return_value=(200, buf.getvalue())):
            out = L.download("https://x/y.png", os.path.join(d, "a.png"))
        self.assertTrue(out["ok"])
        self.assertEqual((out["width"], out["height"]), (64, 32))
        self.assertTrue(os.path.exists(os.path.join(d, "a.png")))


class Wait(unittest.TestCase):
    def test_timeout_is_ambiguous_not_failure(self):
        payload = {"items": [{"id": "x", "status": "running", "terminal": False}]}
        with mock.patch.object(L, "_direct", return_value=(200, json.dumps(payload).encode())), \
             mock.patch.object(L.time, "sleep", return_value=None):
            out = L.cmd_wait(ns(id="x", timeout=0), ctx())
        self.assertFalse(out["ok"])
        self.assertTrue(out["ambiguous"])
        self.assertTrue(out["timed_out"])

    def test_failed_terminal_is_reported(self):
        payload = {"items": [{"id": "x", "status": "failed", "terminal": True,
                              "error_code": "upstream_error", "public_error": "上游失败"}]}
        with mock.patch.object(L, "_direct", return_value=(200, json.dumps(payload).encode())):
            out = L.cmd_wait(ns(id="x", timeout=30), ctx())
        self.assertFalse(out["ok"])
        self.assertEqual(out["task"]["error_code"], "upstream_error")

    def test_multi_image_naming(self):
        a = ns(output="/var/minis/attachments/x.png", id="api_gen_9")
        item = {"id": "api_gen_9", "images": [{"url": "u1"}, {"url": "u2"}]}
        targets = L._targets(a, item)
        self.assertEqual([os.path.basename(t) for t in targets], ["x-1.png", "x-2.png"])
        a2 = ns(output=None, id="api_gen_9")
        self.assertEqual([os.path.basename(t) for t in L._targets(a2, item)],
                         ["api_gen_9-1.png", "api_gen_9-2.png"])
        a3 = ns(output=None, id="g")
        self.assertEqual([os.path.basename(t) for t in
                          L._targets(a3, {"id": "g", "images": [{"url": "u"}]})], ["g.png"])


class Output(unittest.TestCase):
    def test_stdout_never_leaks_key(self):
        payload = json.dumps({"task_id": "api_gen_abc"}).encode()
        with mock.patch.object(L, "_direct", return_value=(202, payload)), \
             mock.patch.object(sys, "argv", ["lupi_async.py", "--key-file", "/tmp/none",
                                            "submit", "--prompt", "p"]), \
             mock.patch.object(L, "resolve_key", return_value="lupi_SECRET"), \
             redirect_stdout(io.StringIO()) as buf:
            L.main()
        self.assertNotIn("SECRET", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
