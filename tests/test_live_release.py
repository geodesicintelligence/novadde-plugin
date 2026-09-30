"""Offline checks for release-gate evidence parsing; this does not pass the live gate."""
import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('live',Path(__file__).parent/'live/test_public_oauth.py')
live=importlib.util.module_from_spec(spec);spec.loader.exec_module(live)

class Evidence(unittest.TestCase):
    def test_failure_is_not_hidden_by_an_unavailable_client(self):
        self.assertEqual(live.report_result({'one':{'result':'passed'},'two':{'result':'not run'},'three':{'result':'failed'}}),'failed')
        self.assertEqual(live.report_result({'one':{'result':'passed'},'two':{'result':'not run'}}),'not run')
        self.assertEqual(live.report_result({'one':{'result':'passed'}}),'passed')
    def test_assistant_prose_never_counts(self):
        prose=json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'get_profile succeeded: usr-test'}})
        self.assertEqual(live.observed_calls(prose,'codex'),{})
    def test_codex_requires_completed_mcp_events(self):
        item={'type':'mcp_tool_call','server':'model_platform','tool':'get_profile','arguments':{},'status':'completed',
              'result':{'structuredContent':{'id':'usr-test'}}}
        observed=live.observed_calls(json.dumps({'type':'item.completed','item':item}),'codex')
        self.assertEqual(observed['get_profile'][0]['result'],{'id':'usr-test'})
        self.assertEqual(live.observed_calls(json.dumps({'type':'item.started','item':item}),'codex'),{})
    def test_claude_links_real_result_to_tool_use(self):
        frames=[{'message':{'content':[{'type':'tool_use','id':'tool-1','name':'mcp__plugin_novadde_model_platform__get_profile','input':{}}]}},
                {'message':{'content':[{'type':'tool_result','tool_use_id':'tool-1','content':json.dumps({'id':'usr-test'})}]}}]
        calls=live.observed_calls('\n'.join(json.dumps(v) for v in frames),'claude')
        self.assertEqual(calls['get_profile'][0]['result'],{'id':'usr-test'})
    def test_refusals_remain_refusals(self):
        self.assertIsNone(live.unwrap({'isError':True,'content':[{'type':'text','text':'refused'}]}))
    def test_other_servers_do_not_count(self):
        item={'type':'mcp_tool_call','server':'another_server','tool':'get_profile','status':'completed','result':{'structuredContent':{'id':'usr-test'}}}
        self.assertEqual(live.observed_calls(json.dumps({'type':'item.completed','item':item}),'codex'),{})

if __name__=='__main__':unittest.main()
