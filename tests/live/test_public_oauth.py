#!/usr/bin/env python3
"""Opt-in release gate: PUBLIC plugin -> real clients -> production OAuth.

Not collected by offline CI. No test GPU submissions. Run from an operator terminal:
 python3 tests/live/test_public_oauth.py --public-sha SHA --plugin-version 0.2.0 \
   --expected-account usr-ID --fixture-job job-ID --fixture-path output.pdb \
   --fixture-sha256 SHA256 --report /safe/path/public-oauth-report.json

Both clients must already have their own model-provider login. The platform OAuth
login is performed by the installed plugin, with a fresh private HOME, through
real browser consent. --browser-driver may name a program that opens the real
consent URL; it must not substitute endpoints or inject OAuth tokens.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PUBLIC = 'https://github.com/geodesicintelligence/novadde-plugin.git'
SELECTOR = 'novadde@novadde-plugin'
ISSUER = 'https://platform.geodesiclab.com'
RESOURCE = ISSUER + '/api/mcp'
READS = ['get_profile', 'get_usage', 'list_jobs', 'estimate_job', 'fetch_artifact', 'get_job', 'list_models', 'describe_model']
SPEND = ['submit_job','submit_pipeline_run','cancel_job','cancel_pipeline_run','stage_file']


class NotRun(Exception): pass
class Failed(Exception): pass


def run(args, env=None, cwd=None, timeout=240, input=None):
    try:
        return subprocess.run(args, env=env, cwd=cwd, input=input, text=True,
                              capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise NotRun('Client unavailable or timed out') from None


def checked(args, **kwargs):
    done = run(args, **kwargs)
    if done.returncode:
        # Never put tool transcripts, browser URLs or upstream errors in the report.
        raise Failed('Command did not succeed')
    return done.stdout


def unwrap(value):
    if isinstance(value, str):
        try: return unwrap(json.loads(value))
        except ValueError: return None
    if not isinstance(value, dict) or value.get('isError') or value.get('is_error'):
        return None
    if 'structuredContent' in value: return value['structuredContent']
    if 'content' in value and isinstance(value['content'], list):
        for block in value['content']:
            if isinstance(block, dict) and block.get('type') == 'text':
                try: return json.loads(block['text'])
                except (ValueError, KeyError): pass
    return value if any(k in value for k in ['id','jobs','models','credits','policy']) else None


def observed_calls(stdout, client):
    """Read actual client tool events; assistant prose never counts as evidence."""
    calls, ids = {}, {}
    for line in stdout.splitlines():
        try: event = json.loads(line)
        except ValueError: continue
        if client == 'codex':
            item = event.get('item') or {}
            if event.get('type') == 'item.completed' and item.get('type') == 'mcp_tool_call':
                name = item.get('tool') or ''
                if name in READS and 'model_platform' in (item.get('server') or ''):
                    calls.setdefault(name, []).append({'arguments':item.get('arguments') or {},
                                                       'result':unwrap(item.get('result')),
                                                       'failed':item.get('status') != 'completed' or bool(item.get('error'))})
        else:
            content = (event.get('message') or {}).get('content') or []
            if not isinstance(content, list): continue
            for block in content:
                if block.get('type') == 'tool_use' and 'model_platform' in block.get('name',''):
                    name = block['name'].rsplit('__',1)[-1]
                    ids[block['id']] = (name, block.get('input') or {})
                elif block.get('type') == 'tool_result' and block.get('tool_use_id') in ids:
                    name, arguments = ids[block['tool_use_id']]
                    result = block.get('content')
                    if isinstance(result,list): result = {'content':result}
                    calls.setdefault(name, []).append({'arguments':arguments,'result':unwrap(result),
                                                       'failed':bool(block.get('is_error'))})
    return calls


def client_call(client, env, cwd, requests, refused=False):
    prompt = ('Release verification. Use ONLY the installed novadde model_platform MCP server. '
              'Make these exact read-only calls once each. Do not use Bash, HTTP, another server, '
              'or any submission/cancellation/staging tool. Do not print authorization headers, '
              'tokens or returned artifact ticket headers. Do not read credentials. Calls: ' +
              json.dumps(requests) + '. Stop after the tool results. ' +
              ('Protected calls are expected to be refused; do not initiate login.' if refused else ''))
    if client == 'claude':
        prefix = 'mcp__plugin_novadde_model_platform__'
        args = ['claude','-p','--output-format','stream-json','--verbose','--no-session-persistence',
                '--allowedTools', ','.join(prefix+n for n in READS),
                '--disallowedTools', ','.join(prefix+n for n in SPEND), '--tools','', prompt]
    else:
        args = ['codex','-a','never','exec','--json','--ephemeral','--sandbox','read-only',
                '--skip-git-repo-check','--color','never', prompt]
    output = checked(args, env=env, cwd=cwd, timeout=300)
    calls = observed_calls(output, client)
    results = {}
    for request in requests:
        name = request['name']
        matched = [item for item in calls.get(name,[]) if item['arguments'] == request.get('arguments',{})]
        if not matched:
            raise Failed('Actual client tool event was not observed')
        record = matched[-1]
        if name == 'get_profile' and refused:
            if record['result'] is not None and not record['failed']:
                raise Failed('Revoked connection still authenticated')
            results[name] = None
        else:
            if record['failed'] or record['result'] is None:
                raise Failed('Installed client MCP call failed')
            results[name] = record['result']
    return results


def installed_root(base, host):
    field = '.claude-plugin' if host == 'claude' else '.codex-plugin'
    candidates = [p.parent.parent for p in base.rglob(field+'/plugin.json')
                  if json.loads(p.read_text()).get('name') == 'novadde' and 'cache' in p.parts]
    if len(candidates) != 1: raise Failed('Installed plugin location is ambiguous or missing')
    return candidates[0]


def verify_tree(expected, actual):
    for path in expected.rglob('*'):
        if path.is_file() and '.git' not in path.parts:
            installed = actual / path.relative_to(expected)
            if not installed.is_file() or installed.read_bytes() != path.read_bytes():
                raise Failed('Installed plugin does not match public release content')
    for path in actual.rglob('*'):
        if path.is_file() and path.relative_to(actual).as_posix() not in {
                p.relative_to(expected).as_posix() for p in expected.rglob('*') if p.is_file()}:
            if '__pycache__' not in path.parts:
                raise Failed('Unexpected content in installed plugin')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-sha', required=True)
    parser.add_argument('--plugin-version', required=True)
    parser.add_argument('--expected-account', required=True, help='opaque production account ID')
    parser.add_argument('--fixture-job')
    parser.add_argument('--fixture-path')
    parser.add_argument('--fixture-sha256')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--browser-driver', help='real-browser opener program; receives authorization URL')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.public_sha): parser.error('public SHA must be a full commit SHA')
    report = {'public_commit':args.public_sha,'plugin_version':args.plugin_version,
              'production_issuer':ISSUER,'client_versions':{},'assertions':{},'result':'not run'}
    assertions = report['assertions']
    steps = ['public_release','claude_install','codex_install','production_endpoints','no_api_keys',
             'browser_oauth','fixture','claude_oauth_calls','codex_oauth_calls','artifact_checksum',
             'shared_refresh','claude_after_refresh','codex_after_refresh','watcher_after_refresh',
             'watcher_completion_once','logout_revocation','claude_after_logout','codex_after_logout']
    for step in steps: assertions[step] = {'result':'not run'}
    current = 'public_release'
    revoked = False
    root = None
    env = None
    temporary = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix='novadde-public-oauth-')
        tmp = temporary.name
        os.chmod(tmp, 0o700)
        base = Path(tmp)
        public = base/'public'
        checked(['git','clone','--quiet',PUBLIC,str(public)])
        checked(['git','-C',str(public),'checkout','--quiet',args.public_sha])
        expected = public/'plugins/novadde'
        for host in ['claude','codex']:
            manifest = json.loads((expected/('.'+host+'-plugin/plugin.json')).read_text())
            if manifest['version'] != args.plugin_version: raise Failed('Public version mismatch')
        assertions[current] = {'result':'passed'}
        home = base/'home'; home.mkdir(mode=0o700)
        claude_home, codex_home = home/'.claude', home/'.codex'
        claude_home.mkdir(mode=0o700); codex_home.mkdir(mode=0o700)
        original_home = Path.home()
        original_codex = Path(os.environ.get('CODEX_HOME',str(original_home/'.codex')))
        original_claude = Path(os.environ.get('CLAUDE_CONFIG_DIR',str(original_home/'.claude')))
        for source, target in [(original_codex/'auth.json',codex_home/'auth.json'),
                               (original_claude/'.credentials.json',claude_home/'.credentials.json')]:
            if source.is_file(): shutil.copy2(source,target); target.chmod(0o600)
        env = {k:v for k,v in os.environ.items() if not (
            k.startswith(('MODEL_PLATFORM_','MP_KEY','NOVADDE_','CLAUDE_PLUGIN_'))
            or k in ['GEODESIC_API_KEY','PLATFORM_API_KEY','MP_API_KEY'])}
        env.update(HOME=str(home),CLAUDE_CONFIG_DIR=str(claude_home),CODEX_HOME=str(codex_home),
                   CLAUDE_PLUGIN_DATA=str(base/'watcher'), CLAUDE_PLUGIN_OPTION_READ_ONLY='true')
        if args.browser_driver:
            env['BROWSER'] = str(Path(args.browser_driver).resolve()) + ' %s'
        roots = {}
        for host in ['claude','codex']:
            current = host+'_install'
            if not shutil.which(host): raise NotRun('Required client is unavailable')
            report['client_versions'][host] = checked([host,'--version'],env=env).strip()
            checked([host,'plugin','marketplace','add','geodesicintelligence/novadde-plugin'],env=env,cwd=home)
            command = 'install' if host == 'claude' else 'add'
            checked([host,'plugin',command,SELECTOR],env=env,cwd=home)
            roots[host] = installed_root(claude_home if host == 'claude' else codex_home,host)
            verify_tree(expected, roots[host])
            assertions[current] = {'result':'passed'}
        root = roots['claude']
        current = 'production_endpoints'
        for host, name in [('claude','.mcp.json'),('codex','.codex.mcp.json')]:
            if json.loads((roots[host]/name).read_text())['mcpServers']['model_platform']['url'] != RESOURCE:
                raise Failed('Installed MCP endpoint is not production')
        assertions[current] = {'result':'passed'}
        current = 'no_api_keys'
        credential = home/'.config/geodesic/novadde-oauth.json'
        if (home/'.config/geodesic/model-platform.env').exists(): raise Failed('API-key file exists')
        if any(k.startswith('MODEL_PLATFORM_') or k in ['GEODESIC_API_KEY','PLATFORM_API_KEY','MP_API_KEY'] for k in env):
            raise Failed('Platform API-key environment survived isolation')
        assertions[current] = {'result':'passed'}
        current = 'browser_oauth'
        # Inherit terminal output for the operator to see the consent URL. Do not
        # capture it in a report, and do not inspect a browser's session storage.
        login = subprocess.run([str(root/'scripts/auth.sh'),'login'],env=env,cwd=home,timeout=330)
        if login.returncode or not credential.exists(): raise NotRun('Real browser login was not completed')
        value = json.loads(credential.read_text())
        if value.get('mode') != 'oauth' or value['account']['id'] != args.expected_account:
            raise Failed('OAuth connected the wrong production account')
        if value.get('issuer') != ISSUER or value.get('resource') != RESOURCE or credential.stat().st_mode & 0o777 != 0o600:
            raise Failed('OAuth credential binding or file permissions are wrong')
        assertions[current] = {'result':'passed'}
        current = 'fixture'
        if not all([args.fixture_job,args.fixture_path,args.fixture_sha256]):
            raise NotRun('An existing completed production fixture and checksum are required')
        def direct(name, arguments=None):
            return json.loads(checked([str(root/'scripts/auth.sh'),'call',name],env=env,cwd=home,input=json.dumps(arguments or {})))
        fixture = direct('get_job',{'job_id':args.fixture_job})
        if fixture.get('status') != 'completed': raise Failed('Fixture job is not completed')
        assertions[current] = {'result':'passed'}
        # Use the real completed fixture inputs, unchanged, for a no-spend estimate.
        model = fixture.get('model')
        detail = direct('describe_model',{'slug':model})
        example = detail.get('example') or {}
        estimate_args = {'model':model, 'params':example.get('params',{}), 'files':example.get('files',{})}
        requests = [{'name':'get_profile','arguments':{}},{'name':'get_usage','arguments':{}},
                    {'name':'list_jobs','arguments':{'limit':8}},
                    {'name':'estimate_job','arguments':estimate_args}]
        ready = {}
        for host in ['claude','codex']:
            current = host+'_oauth_calls'
            # Client model-provider authentication is independent of platform OAuth.
            status_args = [host,'auth','status'] if host=='claude' else [host,'login','status']
            status = run(status_args,env=env)
            if status.returncode or (host=='claude' and not json.loads(status.stdout).get('loggedIn')):
                assertions[current] = {'result':'not run','reason':'Client model-provider login is missing'}
                ready[host] = False
                continue
            try:
                results = client_call(host,env,home,requests)
                if results['get_profile']['id'] != args.expected_account: raise Failed('Client account mismatch')
            except (Failed,NotRun):
                assertions[current] = {'result':'failed','reason':'Actual client MCP calls did not succeed'}
                ready[host] = False
                continue
            ready[host] = True
            assertions[current] = {'result':'passed','tools':[r['name'] for r in requests]}
        current = 'artifact_checksum'
        if not ready.get('codex'): raise NotRun('Codex artifact tool is unavailable')
        artifact = client_call('codex',env,home,[{'name':'fetch_artifact','arguments':{'job_id':args.fixture_job,'path':args.fixture_path}}])['fetch_artifact']
        url = urllib.parse.urlsplit(artifact['url'])
        if url.scheme != 'https' or url.netloc != 'platform.geodesiclab.com': raise Failed('Artifact origin mismatch')
        header = artifact['header']
        if isinstance(header,str): key, val = header.split(':',1); header={key.strip():val.strip()}
        request = urllib.request.Request(artifact['url'],headers=header)
        digest = hashlib.sha256()
        with urllib.request.urlopen(request,timeout=30) as response:
            for block in iter(lambda:response.read(1024*1024),b''): digest.update(block)
        if digest.hexdigest() != args.fixture_sha256 or digest.hexdigest() != artifact['sha256']:
            raise Failed('Downloaded artifact checksum mismatch')
        assertions[current] = {'result':'passed','sha256':digest.hexdigest()}
        current = 'shared_refresh'
        before = json.loads(credential.read_text())
        after = {**before,'expires_at':0} # Change ONLY local expiry metadata.
        fd = os.open(str(credential),os.O_WRONLY|os.O_TRUNC)
        with os.fdopen(fd,'w') as file: json.dump(after,file)
        checked([str(root/'scripts/auth.sh'),'status'],env=env,cwd=home)
        refreshed = json.loads(credential.read_text())
        if before['access_token']==refreshed['access_token'] or before['refresh_token']==refreshed['refresh_token']:
            raise Failed('Forced early refresh did not rotate both tokens')
        assertions[current] = {'result':'passed'}
        for host in ['claude','codex']:
            current = host+'_after_refresh'
            if not ready.get(host):
                assertions[current] = {'result':'not run','reason':'Client login or initial connection is unavailable'}
                continue
            results=client_call(host,env,home,[{'name':'get_profile','arguments':{}},{'name':'get_usage','arguments':{}}])
            if results['get_profile']['id'] != args.expected_account: raise Failed('Account changed after refresh')
            assertions[current] = {'result':'passed'}
        current = 'watcher_after_refresh'
        partition = checked([str(root/'scripts/auth.sh'),'partition'],env=env,cwd=home).strip()
        state = Path(env['CLAUDE_PLUGIN_DATA'])/'connections'/partition/'watch-state.json'
        state.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        state.write_text(json.dumps({args.fixture_job:'running'})); state.chmod(0o600)
        output = checked([str(root/'scripts/watch-jobs.sh'),'--once'],env=env,cwd=home)
        assertions[current] = {'result':'passed'}
        current = 'watcher_completion_once'
        second = checked([str(root/'scripts/watch-jobs.sh'),'--once'],env=env,cwd=home)
        if output.count('[novadde-job]') != 1 or args.fixture_job not in output or '[novadde-job]' in second:
            raise Failed('Published watcher missed or duplicated the completion notice')
        assertions[current] = {'result':'passed'}
        current = 'logout_revocation'
        checked([str(root/'scripts/auth.sh'),'logout'],env=env,cwd=home)
        revoked = True
        # Verify the server refuses the ORIGINAL connection, not merely an empty local store.
        revoked_request = urllib.request.Request(RESOURCE,data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_profile','arguments':{}}}).encode(),headers={'Authorization':'Bearer '+refreshed['access_token'],'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
        try:
            with urllib.request.urlopen(revoked_request,timeout=10): pass
            raise Failed('Server accepted the revoked access token')
        except urllib.error.HTTPError as error:
            if error.code != 401: raise Failed('Revocation returned an unexpected response')
        assertions[current] = {'result':'passed'}
        for host in ['claude','codex']:
            current = host+'_after_logout'
            if not ready.get(host):
                assertions[current] = {'result':'not run','reason':'Client login or initial connection is unavailable'}
                continue
            client_call(host,env,home,[{'name':'get_profile','arguments':{}},{'name':'list_models','arguments':{}}],refused=True)
            assertions[current] = {'result':'passed'}
        states = [record['result'] for record in assertions.values()]
        report['result'] = 'failed' if 'failed' in states else ('not run' if 'not run' in states else 'passed')
    except NotRun:
        assertions[current] = {'result':'not run','reason':'Required login, fixture or client is unavailable'}
    except (Failed, ValueError, KeyError, OSError, subprocess.SubprocessError):
        assertions[current] = {'result':'failed','reason':'Release assertion did not succeed; inspect privately'}
        report['result'] = 'failed'
    finally:
        if not revoked and root is not None and env is not None:
            try:
                cleanup = run([str(root/'scripts/auth.sh'),'logout'],env=env,timeout=30)
                assertions['cleanup_revocation'] = {'result':'passed' if cleanup.returncode == 0 else 'failed'}
                if cleanup.returncode: report['result'] = 'failed'
            except Exception:
                assertions['cleanup_revocation'] = {'result':'failed'}
                report['result'] = 'failed'
        if temporary is not None:
            temporary.cleanup()
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n')
    print('Public production OAuth release test: '+report['result']+'. Sanitized report: '+str(args.report))
    return 0 if report['result']=='passed' else 2


if __name__ == '__main__': sys.exit(main())
