"""Offline checks for release-gate evidence parsing; this does not pass the live gate."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('live',Path(__file__).parent/'live/test_public_oauth.py')
live=importlib.util.module_from_spec(spec);spec.loader.exec_module(live)

class Evidence(unittest.TestCase):
    def test_claude_prompt_is_separate_from_variadic_tool_options(self):
        frames=[{'message':{'content':[{'type':'tool_use','id':'tool-1','name':'mcp__plugin_novadde_model_platform__get_profile','input':{}}]}},
                {'message':{'content':[{'type':'tool_result','tool_use_id':'tool-1','content':json.dumps({'id':'usr-test'})}]}}]
        with patch.object(live,'run',return_value=subprocess.CompletedProcess([],0,'\n'.join(json.dumps(v) for v in frames),'')) as command:
            live.client_call('claude',{},Path('/tmp'),[{'name':'get_profile','arguments':{}}])
        args=command.call_args.args[0]
        self.assertEqual(args[-4:-1],['--tools','','--'])
        self.assertIn('get_profile({})',args[-1])
        self.assertIn('do not wrap it in name or arguments',args[-1])
    def test_completed_tool_evidence_survives_later_cli_summary_error(self):
        item={'type':'mcp_tool_call','server':'model_platform','tool':'get_profile','arguments':{},'status':'completed',
              'result':{'structuredContent':{'id':'usr-test'}}}
        output=json.dumps({'type':'item.completed','item':item})
        with patch.object(live,'run',return_value=subprocess.CompletedProcess([],1,output,'')):
            self.assertEqual(live.client_call('codex',{},Path('/tmp'),[{'name':'get_profile','arguments':{}}]),{'get_profile':{'id':'usr-test'}})
            with self.assertRaises(live.Failed):
                live.client_call('codex',{},Path('/tmp'),[{'name':'get_profile','arguments':{}},{'name':'get_usage','arguments':{}}])
    def test_failed_command_without_tool_evidence_cannot_pass(self):
        with patch.object(live,'run',return_value=subprocess.CompletedProcess([],1,'','')):
            with self.assertRaises(live.Failed):
                live.client_call('claude',{},Path('/tmp'),[{'name':'get_profile','arguments':{}}],refused=True)
    def test_parameterless_tool_uses_result_evidence_despite_unused_wrapper(self):
        item={'type':'mcp_tool_call','server':'model_platform','tool':'get_profile','arguments':{'arguments':{}},'status':'completed',
              'result':{'structuredContent':{'id':'usr-test'}}}
        output=json.dumps({'type':'item.completed','item':item})
        with patch.object(live,'run',return_value=subprocess.CompletedProcess([],0,output,'')):
            self.assertEqual(live.client_call('codex',{},Path('/tmp'),[{'name':'get_profile','arguments':{}}]),{'get_profile':{'id':'usr-test'}})
    def test_parameterized_tool_still_requires_exact_arguments(self):
        item={'type':'mcp_tool_call','server':'model_platform','tool':'list_jobs','arguments':{'arguments':{'limit':8}},'status':'completed',
              'result':{'structuredContent':{'jobs':[]}}}
        output=json.dumps({'type':'item.completed','item':item})
        with patch.object(live,'run',return_value=subprocess.CompletedProcess([],0,output,'')):
            with self.assertRaises(live.Failed):
                live.client_call('codex',{},Path('/tmp'),[{'name':'list_jobs','arguments':{'limit':8}}])
    def test_completed_codex_tool_error_is_a_refusal(self):
        item={'type':'mcp_tool_call','server':'model_platform','tool':'get_profile','arguments':{},'status':'completed',
              'result':{'isError':True,'content':[{'type':'text','text':'Authentication required'}]}}
        output=json.dumps({'type':'item.completed','item':item})
        with patch.object(live,'run',return_value=subprocess.CompletedProcess([],0,output,'')):
            self.assertEqual(live.client_call('codex',{},Path('/tmp'),[{'name':'get_profile','arguments':{}}],refused=True),{'get_profile':None})
    def test_unparsed_success_cannot_count_as_authentication_refusal(self):
        item={'type':'mcp_tool_call','server':'model_platform','tool':'get_profile','arguments':{},'status':'completed',
              'result':{'content':[{'type':'text','text':'unparsed response'}]}}
        output=json.dumps({'type':'item.completed','item':item})
        with patch.object(live,'run',return_value=subprocess.CompletedProcess([],0,output,'')):
            with self.assertRaises(live.Failed):
                live.client_call('codex',{},Path('/tmp'),[{'name':'get_profile','arguments':{}}],refused=True)
    def test_logout_refusal_and_public_read_use_independent_client_calls(self):
        refused=[{'message':{'content':[{'type':'tool_use','id':'tool-1','name':'mcp__plugin_novadde_model_platform__get_profile','input':{}}]}},
                 {'message':{'content':[{'type':'tool_result','tool_use_id':'tool-1','is_error':True,'content':'Authentication required'}]}}]
        public=[{'message':{'content':[{'type':'tool_use','id':'tool-2','name':'mcp__plugin_novadde_model_platform__list_models','input':{}}]}},
                {'message':{'content':[{'type':'tool_result','tool_use_id':'tool-2','content':json.dumps({'models':[]})}]}}]
        outputs=[subprocess.CompletedProcess([],1,'\n'.join(json.dumps(v) for v in refused),''),
                 subprocess.CompletedProcess([],0,'\n'.join(json.dumps(v) for v in public),'')]
        with patch.object(live,'run',side_effect=outputs) as command:
            results=live.client_call('claude',{},Path('/tmp'),[{'name':'get_profile','arguments':{}},{'name':'list_models','arguments':{}}],refused=True)
        self.assertEqual(command.call_count,2)
        self.assertEqual(results,{'get_profile':None,'list_models':{'models':[]}})
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
