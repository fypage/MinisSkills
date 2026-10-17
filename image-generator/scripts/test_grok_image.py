#!/usr/bin/env python3
"""grok_image.py 离线测试（不发网络请求）。"""
import base64
import io
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grok_image as g  # noqa: E402


def fake_png(w=64, h=32):
    head = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h)
    return head + b"\x08\x02\x00\x00\x00" + b"\x00" * 2048


def fake_jpeg(w=720, h=1280):
    sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", h, w) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + sof + b"\x00" * 2048


class KeyLoading(unittest.TestCase):
    def test_env_key_wins(self):
        with mock.patch.dict(os.environ, {"GROK2API_KEY": "g2a_env"}):
            self.assertEqual(g.load_key(), "g2a_env")

    def test_file_key(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("CLIENT_KEY (admin): g2a_file123\n")
            path = fh.name
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(g.load_key(path), "g2a_file123")
        os.unlink(path)

    def test_missing_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(g.GrokError):
                g.load_key("/nonexistent/keyring.txt")


class SizeParsing(unittest.TestCase):
    def test_png(self):
        self.assertEqual(g.image_size(fake_png(1254, 1254)), (1254, 1254, "PNG"))

    def test_jpeg(self):
        self.assertEqual(g.image_size(fake_jpeg(1152, 768)), (1152, 768, "JPEG"))

    def test_unknown(self):
        self.assertEqual(g.image_size(b"garbage" * 100)[2], "unknown")


class GenerationArgs(unittest.TestCase):
    def args(self, **kw):
        base = dict(model="grok-imagine-image-2.0", prompt="p", n=1, ratio=None,
                    size=None, resolution=None, quality=None, format="url")
        base.update(kw)
        return mock.Mock(**base)

    def test_native_types(self):
        body = g.build_generation(self.args(ratio="2:3", n=2))
        self.assertIsInstance(body["n"], int)
        self.assertEqual(body["aspect_ratio"], "2:3")

    def test_bad_ratio_rejected(self):
        with self.assertRaises(g.GrokError):
            g.build_generation(self.args(ratio="7:5"))

    def test_ratio_from_size(self):
        body = g.build_generation(self.args(size="1024x1536"))
        self.assertEqual(body["size"], "1024x1536")
        self.assertNotIn("aspect_ratio", body)


class Saving(unittest.TestCase):
    def test_unique_path_adds_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "x.jpg"), "wb").close()
            self.assertTrue(g.unique_path(d, "x", "jpg").endswith("x-1.jpg"))

    def test_b64_item_saved(self):
        blob = fake_png(96, 96)
        item = {"b64_json": base64.b64encode(blob).decode(), "mime_type": "image/png"}
        with tempfile.TemporaryDirectory() as d:
            out = g.save_items([item], "k", d, "t", 10)
        self.assertEqual(out[0]["width"], 96)
        self.assertEqual(out[0]["bytes"], len(blob))

    def test_empty_item_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(g.GrokError):
                g.save_items([{}], "k", d, "t", 10)


class Requests(unittest.TestCase):
    def test_http_error_surfaces_body(self):
        err = g.urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b'{"error":{"message":"nope"}}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(g.GrokError) as ctx:
                g.request("POST", "https://x/v1/images/generations", "k", {"a": 1}, 5)
        self.assertIn("400", str(ctx.exception))
        self.assertIn("nope", str(ctx.exception))

    def test_network_error_marks_uncertain(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            with self.assertRaises(g.GrokError) as ctx:
                g.request("POST", "https://x", "k", {"a": 1}, 5)
        self.assertIn("结果不确定", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
