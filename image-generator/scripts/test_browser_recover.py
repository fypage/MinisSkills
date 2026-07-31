import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

P = Path(__file__).with_name("browser_recover.py")
spec = importlib.util.spec_from_file_location("browser_recover", P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class BrowserRecoverTests(unittest.TestCase):
    def test_parse_json_envelope(self):
        b64 = base64.b64encode(b"x" * 1200).decode()
        raw = json.dumps({"data": {"text": "data:image/png;base64," + b64}})
        self.assertEqual(m.data_url_from_output(raw), b64)

    def test_parse_offload(self):
        b64 = base64.b64encode(b"y" * 1200).decode()
        off = Path("/var/minis/offloads/test_browser_recover.json")
        off.write_text(json.dumps({"data": {"text": "data:image/png;base64," + b64}}))
        try:
            self.assertEqual(m.data_url_from_output("saved minis://offloads/" + off.name), b64)
        finally:
            off.unlink(missing_ok=True)

    def test_tab_id(self):
        self.assertEqual(m.tab_id_from_output("Opened new tab 12 at x. Use tab_id: 12"), "12")


if __name__ == "__main__":
    unittest.main()
