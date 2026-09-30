"""Completion notices deduplicate across reconnects, processes and account partitions."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
PLUGIN = Path(__file__).resolve().parents[1] / 'plugins/novadde'
sys.path.insert(0, str(PLUGIN / 'scripts/lib'))
import oauth_client as auth
import watch_jobs as watcher

class Watcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'HOME': self.tmp.name, 'NOVADDE_DATA': self.tmp.name + '/data'})
        self.env.start()
        self.account('usr-one')
    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()
    def account(self, ident):
        auth.atomic_write(auth.credential_path(), {**auth.BINDING, 'mode':'oauth', 'account': {'id':ident}, 'access_token':'secret'})
    def poll(self, jobs):
        out = io.StringIO()
        with patch.object(auth, 'access_token', return_value='secret'), patch.object(watcher, 'collect', return_value=jobs), contextlib.redirect_stdout(out):
            watcher.poll()
        return out.getvalue()
    def test_baseline_then_completion_exactly_once(self):
        job = {'id':'job-test123', 'status':'running', 'model':'molprobity'}
        self.assertEqual(self.poll([job]), '')
        job['status'] = 'completed'
        self.assertEqual(self.poll([job]).count('[novadde-job]'), 1)
        self.assertEqual(self.poll([job]), '')
        self.assertEqual(self.poll([job]), '')
    def test_terminal_history_is_silent(self):
        self.assertEqual(self.poll([{'id':'job-old', 'status':'completed'}]), '')
    def test_account_change_does_not_leak_notifications(self):
        self.poll([{'id':'job-old', 'status':'running'}])
        one = watcher.connection_dir()
        self.account('usr-two')
        self.assertNotEqual(one, watcher.connection_dir())
        self.assertEqual(self.poll([{'id':'job-old', 'status':'completed'}]), '')
    def test_reconnect_resumes_previous_state(self):
        self.poll([{'id':'job-old', 'status':'running'}])
        with patch.object(auth, 'access_token', side_effect=auth.AuthError('revoked')):
            with self.assertRaises(auth.AuthError): watcher.poll()
        self.account('usr-one')
        self.assertIn('finished: completed', self.poll([{'id':'job-old', 'status':'completed'}]))
    def test_pipeline_completion_once(self):
        self.poll([{'id':'run-old', 'status':'running'}])
        self.assertIn('get_pipeline_run', self.poll([{'id':'run-old', 'status':'partial'}]))
        self.assertEqual(self.poll([{'id':'run-old', 'status':'completed'}]), '')
    def test_bounded_listing_keeps_old_active_jobs(self):
        def call(name, arguments):
            if name == 'list_jobs': return {'jobs':[]}
            if name == 'list_pipeline_runs': return {'runs':[]}
            self.assertEqual(arguments, {'job_id':'job-old'})
            return {'id':'job-old', 'status':'completed'}
        with patch.object(auth, 'call', side_effect=call):
            self.assertEqual(watcher.collect({'job-old':'running'})[0]['status'], 'completed')

class Availability(unittest.TestCase):
    def brief(self, flags):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'plugin'; shutil.copytree(PLUGIN, root)
            script = root/'scripts/auth.sh'
            script.write_text('#!/bin/sh\nif [ "$1" = status ]; then echo "Authentication: oauth"; else echo "{}"; fi\n')
            script.chmod(0o755)
            cache = Path(tmp)/'data'; cache.mkdir(); (cache/'tools.txt').write_text('get_usage\n')
            env = {'HOME':tmp, 'PATH':os.environ['PATH'], 'CLAUDE_PLUGIN_DATA':str(cache), **flags}
            result = subprocess.run([str(root/'scripts/session-brief.sh')], input='{}', capture_output=True, text=True, env=env)
            return result.stdout
    def test_interactive_on(self):
        self.assertIn('Job notifications: ON', self.brief({}))
    def test_supported_hosts_and_flags(self):
        cases = [{'CLAUDE_CODE_ENTRYPOINT': value} for value in ['sdk-cli','sdk-ts','claude-desktop','local-agent','claude-code-github-action']]
        cases += [{name:'1'} for name in ['CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY','CLAUDE_CODE_USE_MANTLE']]
        cases += [{name:'0'} for name in ['DISABLE_TELEMETRY','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC']]
        for flags in cases:
            with self.subTest(flags=flags): self.assertIn('Job notifications: OFF', self.brief(flags))
    def test_false_provider_flag_does_not_disable(self):
        self.assertIn('Job notifications: ON', self.brief({'CLAUDE_CODE_USE_VERTEX':'false'}))

if __name__ == '__main__': unittest.main()
