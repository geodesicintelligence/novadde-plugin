"""OAuth safety: shared storage, concurrent refreshes, crash recovery and no implicit keys."""
import contextlib
import importlib.util
import io
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'plugins/novadde'
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import oauth_client as auth


def expired():
    return {**auth.BINDING, 'mode': 'oauth', 'account': {'id': 'usr-test', 'email': 'test@example.com'},
            'access_token': 'mpat_old', 'refresh_token': 'mprt_old', 'expires_at': 0, 'scope': auth.SCOPES}


def tokens():
    return {'token_type': 'Bearer', 'access_token': 'mpat_new', 'refresh_token': 'mprt_new',
            'expires_in': 3600, 'scope': auth.SCOPES}


def refresh_child(queue):
    try:
        queue.put(auth.access_token())
    except Exception:
        queue.put('failed')


class OAuthStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = patch.dict(os.environ, {'HOME': self.tmp.name})
        self.home.start()
    def tearDown(self):
        self.home.stop()
        self.tmp.cleanup()
    def save(self, value=None):
        auth.atomic_write(auth.credential_path(), expired() if value is None else value)
    def test_keys_require_explicit_selection(self):
        auth.directory().mkdir(parents=True)
        (auth.directory() / 'model-platform.env').write_text('MODEL_PLATFORM_API_KEY=mp_secret')
        self.assertIsNone(auth.access_token())
    def test_environment_is_not_a_credential(self):
        with patch.dict(os.environ, {'MODEL_PLATFORM_API_KEY': 'mp_secret'}):
            self.assertIsNone(auth.access_token())
    def test_refresh_rotates_and_mode_is_private(self):
        self.save()
        with patch.object(auth, 'request', return_value=tokens()), patch.object(auth, 'rpc', return_value={'id': 'usr-test'}):
            self.assertEqual(auth.access_token(), 'mpat_new')
        self.assertEqual(auth.load()['refresh_token'], 'mprt_new')
        self.assertEqual(auth.credential_path().stat().st_mode & 0o777, 0o600)
    def test_network_loss_during_refresh_never_reuses_token(self):
        self.save()
        with patch.object(auth, 'request', side_effect=auth.NetworkError('Offline')) as send:
            for _ in range(3):
                with self.assertRaises(auth.AuthError):
                    auth.access_token()
            self.assertEqual(send.call_count, 1)
        self.assertTrue(auth.load()['needs_login'])
    def test_rejected_refresh_requires_login(self):
        self.save()
        with patch.object(auth, 'request', side_effect=auth.Rejected('Refused')):
            with self.assertRaises(auth.AuthError):
                auth.access_token()
        self.assertTrue(auth.load()['needs_login'])
    def test_crash_marker_requires_login_without_a_network_call(self):
        self.save({**expired(), 'needs_login': True})
        with patch.object(auth, 'request') as request:
            with self.assertRaises(auth.AuthError):
                auth.access_token()
            request.assert_not_called()
    def test_atomic_write_interruption_preserves_previous_file(self):
        self.save()
        with patch.object(auth.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.save({'mode': 'logged_out'})
        self.assertEqual(auth.load()['access_token'], 'mpat_old')
    def test_concurrent_processes_refresh_once(self):
        self.save()
        ctx = multiprocessing.get_context('fork')
        count = ctx.Value('i', 0)
        def exchange(*args, **kwargs):
            with count.get_lock():
                count.value += 1
            time.sleep(.05)
            return tokens()
        with patch.object(auth, 'request', side_effect=exchange), patch.object(auth, 'rpc', return_value={'id': 'usr-test'}):
            queue = ctx.Queue()
            processes = [ctx.Process(target=refresh_child, args=(queue,)) for _ in range(6)]
            for proc in processes: proc.start()
            for proc in processes: proc.join(3)
            self.assertEqual([queue.get(timeout=1) for _ in processes], ['mpat_new'] * 6)
        self.assertEqual(count.value, 1)
    def test_bindings_are_all_required(self):
        for field in auth.BINDING:
            self.save({**expired(), field: 'https://another.example'})
            with self.assertRaises(auth.AuthError): auth.access_token()
    def test_refresh_cannot_change_account(self):
        self.save()
        with patch.object(auth, 'request', return_value=tokens()), patch.object(auth, 'rpc', return_value={'id': 'usr-other'}):
            with self.assertRaises(auth.AuthError): auth.access_token()
        self.assertTrue(auth.load()['needs_login'])
    def test_logout_revokes_and_never_selects_key(self):
        self.save()
        with patch.object(auth, 'request', return_value={}) as revoke, contextlib.redirect_stdout(io.StringIO()):
            auth.logout()
        self.assertTrue(revoke.call_args.kwargs['form'])
        self.assertIsNone(auth.access_token())
        self.assertEqual(auth.load(), {'mode': 'logged_out'})
    def test_failed_logout_blocks_further_calls(self):
        self.save()
        with patch.object(auth, 'request', side_effect=auth.NetworkError('offline')):
            with self.assertRaises(auth.AuthError): auth.logout()
        self.assertTrue(auth.load()['needs_login'])
    def test_status_contains_no_secret(self):
        self.save({**expired(), 'expires_at': time.time() + 3600})
        output = io.StringIO()
        with patch.object(sys, 'argv', ['auth', 'status']), patch.object(auth, 'rpc', return_value={'id': 'usr-test'}), contextlib.redirect_stdout(output):
            self.assertEqual(auth.main(), 0)
        self.assertNotIn('mpat_', output.getvalue())
        self.assertNotIn('mprt_', output.getvalue())
    def test_transient_validation_does_not_consume_refresh(self):
        self.save({**expired(), 'expires_at': time.time() + 3600})
        with patch.object(auth, 'rpc', side_effect=auth.NetworkError('Offline')), patch.object(auth, 'request') as send:
            with self.assertRaises(auth.NetworkError): auth.access_token(validate=True)
            send.assert_not_called()
        self.assertNotIn('needs_login', auth.load())
    def test_mcp_application_error_does_not_refresh(self):
        self.save({**expired(), 'expires_at': time.time() + 3600})
        with patch.object(auth, 'rpc', side_effect=auth.AuthError('Invalid model')), patch.object(auth, 'request') as send:
            with self.assertRaises(auth.AuthError): auth.call('estimate_job')
            send.assert_not_called()
    def test_timed_out_login_preserves_connection(self):
        self.save()
        with self.assertRaises(auth.AuthError), contextlib.redirect_stdout(io.StringIO()):
            auth.login(timeout=0, no_browser=True)
        self.assertEqual(auth.load(), expired())
    def test_callback_rejects_state_and_issuer_before_exchange(self):
        import threading
        import urllib.parse
        import urllib.request
        import urllib.error
        self.save()
        def browser(url):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            callback = query['redirect_uri'][0]
            for fields in [dict(state='wrong',iss=auth.ISSUER,code='secret'),
                           dict(state=query['state'][0],iss='https://wrong.example',code='secret')]:
                try: urllib.request.urlopen(callback+'?'+urllib.parse.urlencode(fields),timeout=2)
                except urllib.error.HTTPError as error: self.assertEqual(error.code,400)
            final = dict(state=query['state'][0],iss=auth.ISSUER,error='access_denied')
            urllib.request.urlopen(callback+'?'+urllib.parse.urlencode(final),timeout=2).close()
            return True
        with patch.object(auth.webbrowser,'open',side_effect=browser), patch.object(auth,'request') as exchange, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(auth.AuthError): auth.login(timeout=5)
            exchange.assert_not_called()
        self.assertEqual(auth.load(),expired())
    def test_blocking_browser_launcher_does_not_block_callback(self):
        import urllib.parse
        import urllib.request
        captured = {}
        def browser(url):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            callback = query['redirect_uri'][0]
            fields = dict(state=query['state'][0],iss=auth.ISSUER,code='test-code')
            captured['challenge'] = query['code_challenge'][0]
            urllib.request.urlopen(callback+'?'+urllib.parse.urlencode(fields),timeout=2).close()
            return True
        def exchange(url,data,form=False):
            import base64,hashlib
            actual=base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).rstrip(b'=')
            self.assertEqual(actual.decode(),captured['challenge'])
            self.assertTrue(form)
            return tokens()
        with patch.object(auth.webbrowser,'open',side_effect=browser), patch.object(auth,'request',side_effect=exchange), patch.object(auth,'rpc',return_value={'id':'usr-test'}), contextlib.redirect_stdout(io.StringIO()):
            auth.login(timeout=5)
        self.assertEqual(auth.load()['mode'],'oauth')
    def test_http_errors_do_not_echo_upstream_secrets(self):
        import urllib.error
        error = urllib.error.HTTPError('https://example?code=secret', 401, 'mpat_secret', {}, io.BytesIO(b'mprt_secret'))
        with patch('urllib.request.OpenerDirector.open', side_effect=error):
            with self.assertRaises(auth.Rejected) as raised: auth.request(auth.RESOURCE)
        self.assertNotIn('secret', str(raised.exception))


if __name__ == '__main__': unittest.main()
