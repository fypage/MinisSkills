import importlib.util
import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(m.aspect_from_dims((1024, 1792)), "9:16")

    def test_output_rejects_outside_attachments(self):
        with self.assertRaises(SystemExit):
            m.validate_output_path("/tmp/out.png")


if __name__ == "__main__":
    unittest.main()
