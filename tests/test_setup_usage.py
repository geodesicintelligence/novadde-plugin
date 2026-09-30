"""The installed command is usable without host variables and refuses secret argv."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1] / 'plugins/novadde/scripts'
class Setup(unittest.TestCase):
    def test_help(self):
        done = subprocess.run([str(ROOT/'auth.sh'), '--help'], capture_output=True, text=True)
        for word in ['login', 'logout', 'status', 'legacy-api-key']:
            self.assertIn(word, done.stdout)
    def test_key_argument_rejected(self):
        with tempfile.TemporaryDirectory() as home:
            done = subprocess.run([str(ROOT/'setup-credential.sh'), '--key'], env={**os.environ, 'HOME': home}, capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0)
    def test_default_status_needs_login(self):
        with tempfile.TemporaryDirectory() as home:
            done = subprocess.run([str(ROOT/'setup-credential.sh'), '--check'], env={**os.environ, 'HOME': home}, capture_output=True, text=True)
            self.assertEqual(done.returncode, 3)
            self.assertIn('production', done.stdout.replace('platform.geodesiclab.com', 'production'))
    def test_invalid_legacy_arguments_do_not_echo_secrets(self):
        fake_secret = 'mp_test_0123456789abcdef'
        done = subprocess.run([str(ROOT/'setup-credential.sh'), '--key', fake_secret], capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn(fake_secret, done.stdout + done.stderr)
if __name__ == '__main__': unittest.main()
