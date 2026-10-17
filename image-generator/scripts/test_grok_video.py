"""grok_video.py 的离线测试：不发网络请求。"""
import argparse
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import grok_image as gi  # noqa: E402
import grok_video as gv  # noqa: E402


def args(**kw):
    base = dict(prompt="a cat", model="grok-imagine-video", duration=8,
                ratio="16:9", resolution="720p", name=None, out=None,
                image_url=None, ref_image=[], ref_audio=[],
                image_file=None, video_url=None)
    base.update(kw)
    return argparse.Namespace(**base)


class BuildCreateTest(unittest.TestCase):
    def test_minimal(self):
        body = gv.build_create(args())
        self.assertEqual(body["model"], "grok-imagine-video")
        self.assertEqual(body["duration"], 8)
        self.assertEqual(body["aspect_ratio"], "16:9")
        self.assertEqual(body["resolution"], "720p")
        self.assertNotIn("image", body)

    def test_image_and_refs_are_mutually_exclusive(self):
        body = gv.build_create(args(image_url="https://x/a.jpg", ref_image=["https://x/b.jpg"]))
        self.assertIn("image", body)
        self.assertNotIn("reference_images", body)

    def test_refs_and_audio(self):
        body = gv.build_create(args(ref_image=["https://x/1.jpg", "https://x/2.jpg"],
                                    ref_audio=["voice_1"]))
        self.assertEqual(len(body["reference_images"]), 2)
        self.assertEqual(body["reference_audios"], [{"voice_id": "voice_1"}])
        self.assertNotIn("image", body)


class ValidateTest(unittest.TestCase):
    def test_duration_range(self):
        for bad in (0, 16, -1):
            with self.assertRaises(SystemExit):
                gv.validate({"prompt": "x", "duration": bad})

    def test_bad_ratio(self):
        with self.assertRaises(SystemExit):
            gv.validate({"prompt": "x", "aspect_ratio": "21:9"})

    def test_missing_prompt(self):
        with self.assertRaises(SystemExit):
            gv.validate({"model": "grok-imagine-video"})

    def test_ref_images_cap(self):
        with self.assertRaises(SystemExit):
            gv.validate({"prompt": "x", "reference_images": ["u"] * 9})

    def test_ok(self):
        gv.validate({"prompt": "x", "duration": 10, "aspect_ratio": "9:16",
                     "resolution": "720p"})


if __name__ == "__main__":
    unittest.main()
