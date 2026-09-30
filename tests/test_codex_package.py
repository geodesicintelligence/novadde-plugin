"""Both hosts get the identical generated auth implementation and stable identities."""
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/novadde'
sys.path.insert(0, str(PLUGIN / 'scripts/lib'))
from build_headers import helper

class Packages(unittest.TestCase):
    def test_version_and_identity(self):
        for host in ['claude', 'codex']:
            value = json.loads((PLUGIN / ('.' + host + '-plugin/plugin.json')).read_text())
            self.assertEqual(value['name'], 'novadde')
            self.assertEqual(value['version'], '0.2.1')
        codex = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(codex['hooks'], {})
    def test_helpers_and_endpoints(self):
        expected = helper(PLUGIN)
        for name, field in [('.mcp.json', 'headersHelper'), ('.codex.mcp.json', 'http_headers_helper')]:
            server = json.loads((PLUGIN / name).read_text())['mcpServers']['model_platform']
            self.assertEqual(server['url'], 'https://platform.geodesiclab.com/api/mcp')
            self.assertEqual(server[field], expected)
            self.assertNotIn('PLUGIN_ROOT', expected)
            if name == '.mcp.json': self.assertEqual(set(server), {'type', 'url', 'headersHelper'})
            else:
                self.assertEqual(server['tools']['get_usage']['approval_mode'], 'approve')
                self.assertNotIn('submit_job', server['tools'])
    def test_marketplace_names_match(self):
        for file in ['.agents/plugins/marketplace.json', '.claude-plugin/marketplace.json']:
            self.assertEqual(json.loads((ROOT / file).read_text())['name'], 'novadde-plugin')

if __name__ == '__main__': unittest.main()
