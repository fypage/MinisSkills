"""Offline diagnostics regression: model invocation is always mocked."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_openminis_image import m


class DiagnosticsTests(unittest.TestCase):
    def test_nested_json_error(self):
        found, got = m.safe_error_diagnostics([{'response': {'body': json.dumps({
            'error': {'code': 'invalid_api_key', 'type': 'authentication_error'},
            'statusCode': 401})}}], 'model_call')
        self.assertTrue(found)
        self.assertEqual(got, {'stage': 'model_call', 'http_status': 401,
                              'error_code': 'invalid_api_key',
                              'error_type': 'authentication_error'})

    def test_no_status_inference(self):
        for value in ['HTTP 502', {'code': 502}, {'code': '524'},
                      {'type': 'rate_limit_error'}, {'status': True},
                      {'status': 999}, {'status': '502 secret'},
                      {'message': 'HTTP 401 invalid_api_key'}]:
            with self.subTest(value=value):
                _, got = m.safe_error_diagnostics([{'error': value}], 'model_call')
                self.assertIsNone(got['http_status'])

    def test_strict_allowlist(self):
        for secret in ['PRIVATE_PROMPT', 'sk-secret-token', 'https://host/?token=SECRET',
                       'invalid_api_key PRIVATE', 'authentication_error\nSECRET']:
            _, got = m.safe_error_diagnostics([{'error': {
                'code': secret, 'type': secret, 'message': secret,
                'http_status': secret, 'stage': secret}}], secret)
            self.assertEqual(got, {'stage': 'unknown', 'http_status': None,
                                  'error_code': 'unknown', 'error_type': 'unknown'})

    def test_dont_parse_request_or_prompt(self):
        fake = {'status': 401, 'error': {'code': 'invalid_api_key'}}
        found, got = m.safe_error_diagnostics([{'request': fake, 'prompt': fake,
            'messages': [fake], 'message': 'prefix ' + json.dumps(fake)}], 'model_call')
        self.assertFalse(found)
        self.assertIsNone(got['http_status'])
        self.assertEqual(got['error_code'], 'unknown')

    def test_conflicting_status_withheld(self):
        _, got = m.safe_error_diagnostics([{'status': 502,
            'error': {'status': 401}}], 'model_call')
        self.assertIsNone(got['http_status'])

    def test_bounded_envelope(self):
        value = {'error': 'PRIVATE'}
        for _ in range(100):
            value = {'response': value}
        self.assertEqual(m.safe_error_diagnostics([value], 'model_call')[1]['error_code'], 'unknown')

    def run_mock_failure(self, raw='', effect=None, returncode=1, make_image=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            attach, work = root / 'attachments', root / 'work'
            attach.mkdir()
            out, err = io.StringIO(), io.StringIO()
            def cli(cmd, **kwargs):
                if make_image:
                    m.Image.new('RGB', (8, 6)).save(cmd[-1], 'PNG')
                if effect is not None:
                    raise effect
                return SimpleNamespace(returncode=returncode, stdout=raw)
            with patch.object(m, 'WORKSPACE', work), patch.object(m, 'ATTACHMENTS', attach), \
                 patch.object(m.sys, 'stdout', out), patch.object(m.sys, 'stderr', err), \
                 patch.object(m.subprocess, 'run', side_effect=cli) as call:
                with self.assertRaises(SystemExit):
                    m.run_model_use({'prompt': 'PRIVATE_PROMPT'}, attach / 'out.png',
                                    'mock', 'mock', prompt_text='PRIVATE_PROMPT')
                self.assertEqual(call.call_count, 1)
            logs = list(work.glob('image_job_*.json'))
            self.assertEqual(len(logs), 1)
            text = logs[0].read_text()
            for secret in ['PRIVATE_PROMPT', 'sk-secret-token', 'token=SECRET']:
                self.assertNotIn(secret, text + out.getvalue() + err.getvalue())
            record = json.loads(text)
            self.assertTrue(record['request_file_removed'])
            self.assertFalse(list(work.glob('image_model_use_*.json')))
            if make_image:
                self.assertTrue(record['stage_retained'])
                self.assertEqual(len(record['verified_media']), 1)
                self.assertTrue(Path(record['verified_media'][0]['path']).exists())
                self.assertFalse((attach / 'out.png').exists())
            return record

    def test_mock_nested_error_sensitive_echo_and_media_retention(self):
        raw = json.dumps({'response': {'body': json.dumps({'status_code': 403,
            'error': {'code': 'permission_denied', 'type': 'PRIVATE_PROMPT',
                      'message': 'PRIVATE_PROMPT sk-secret-token https://host/?token=SECRET'}})}})
        got = self.run_mock_failure(raw, returncode=0, make_image=True)
        self.assertEqual(got['status'], 'ambiguous')
        self.assertEqual(got['reason'], 'cli_or_provider_error')
        self.assertEqual(got['diagnostics'], {'stage': 'model_call', 'http_status': 403,
            'error_code': 'permission_denied', 'error_type': 'unknown'})

    def test_mock_unknown_stays_unknown(self):
        got = self.run_mock_failure('HTTP 502 PRIVATE_PROMPT sk-secret-token ?token=SECRET')
        self.assertEqual(got['diagnostics']['http_status'], None)
        self.assertEqual(got['diagnostics']['error_code'], 'unknown')
        self.assertEqual(got['status'], 'ambiguous')

    def test_mock_timeout_nested_bytes(self):
        raw = json.dumps({'error': {'message': 'PRIVATE_PROMPT sk-secret-token ?token=SECRET',
                                  'type': 'server_error'}, 'http_status': 524}).encode()
        got = self.run_mock_failure(effect=m.subprocess.TimeoutExpired('mock', 1, output=raw))
        self.assertEqual(got['reason'], 'timeout')
        self.assertEqual(got['diagnostics']['http_status'], 524)
        self.assertEqual(got['diagnostics']['error_type'], 'server_error')

    def test_mock_start_failure_safe(self):
        got = self.run_mock_failure(effect=FileNotFoundError('PRIVATE_PROMPT sk-secret-token'))
        self.assertEqual(got['status'], 'failed_pre_submit')
        self.assertEqual(got['diagnostics']['stage'], 'process_start')
        self.assertIsNone(got['diagnostics']['http_status'])

    def test_mock_validation_phase(self):
        got = self.run_mock_failure('{}', returncode=0)
        self.assertEqual(got['diagnostics']['stage'], 'media_validation')


if __name__ == '__main__':
    unittest.main()
