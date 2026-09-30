"""Status uses MCP, displays recent records, and sends no bearer on shell argv."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1] / 'plugins/novadde'
class Status(unittest.TestCase):
    def test_status_calls_shared_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)/'plugin'; shutil.copytree(ROOT, dest)
            stub = dest/'scripts/auth.sh'
            stub.write_text('''#!/bin/sh
case "$*" in
 status) echo 'Authentication: oauth';;
 'call get_usage') echo '{"policy":"unlimited","used":0,"remaining":null}';;
 'call list_jobs') echo '{"jobs":[{"id":"job-123","model":"molprobity","status":"completed","created_at":"2026-09-30T12:00:00Z"}]}';;
 *) exit 1;;
esac
''');stub.chmod(0o755)
            done = subprocess.run([str(dest/'scripts/status.sh')], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('job-123', done.stdout)
            self.assertNotIn('Bearer', (ROOT/'scripts/status.sh').read_text())
    def test_no_protected_rest_calls(self):
        for script in ['status.sh','session-brief.sh','setup-credential.sh','lib/watch_jobs.py']:
            value=(ROOT/'scripts'/script).read_text()
            self.assertNotIn('/api/jobs',value)
            self.assertNotIn('/api/submission-quota',value)
            self.assertNotIn('/api/auth/me',value)
if __name__ == '__main__': unittest.main()
