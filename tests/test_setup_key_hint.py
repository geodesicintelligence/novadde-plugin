"""Root-independent helpers do not emit environment API keys or open a browser."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1] / 'plugins/novadde'
class HeaderOutput(unittest.TestCase):
    def test_no_implicit_legacy_credential(self):
        with tempfile.TemporaryDirectory() as home:
            directory = Path(home)/'.config/geodesic'
            directory.mkdir(parents=True)
            (directory/'model-platform.env').write_text('MODEL_PLATFORM_API_KEY=mp_secret')
            for name, key in [('.mcp.json', 'headersHelper'), ('.codex.mcp.json', 'http_headers_helper')]:
                helper = json.loads((ROOT/name).read_text())['mcpServers']['model_platform'][key]
                done = subprocess.run(['sh', '-c', helper], cwd=home, env={'HOME': home, 'PATH': os.environ['PATH'], 'MODEL_PLATFORM_API_KEY': 'mp_other'}, capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(json.loads(done.stdout), {})
                self.assertNotIn('mp_secret', done.stdout + done.stderr)
if __name__ == '__main__': unittest.main()
