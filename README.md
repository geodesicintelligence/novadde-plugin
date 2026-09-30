# NovaDDE for Claude Code and Codex

NovaDDE is Geodesic Intelligence's AI co-scientist for drug discovery. On
[agent.geodesiclab.com](https://agent.geodesiclab.com) it is Claude Code, running over ACP inside a
per-user container, with a system prompt the deployment replaces, the lab's GPU models attached over
MCP, the lab's science skills on disk, and a sweep that wakes the conversation when a job finishes.

This plugin is that agent, in your terminal, against the same platform. Claude Code gets all of it;
Codex gets the models and the skills, for reasons [On Codex](#on-codex) gives.

## Install

In Claude Code:

```bash
claude plugin marketplace add geodesicintelligence/novadde-plugin
claude plugin install novadde@novadde-plugin
```

In Codex:

```bash
codex plugin marketplace add geodesicintelligence/novadde-plugin
codex plugin add novadde@novadde-plugin
```

Both install from this repository, as the same plugin id: Codex reads its own marketplace and
manifest (`.agents/plugins/marketplace.json`, `plugins/novadde/.codex-plugin/plugin.json`) and
Claude Code reads its own (`.claude-plugin/`).

## Connect it to the Model Platform

Version **0.2.0** connects to https://platform.geodesiclab.com using OAuth by default.
Run `/novadde:setup` (Codex: `$novadde:setup`) to get the absolute path of the installed
plugin's authentication command. In your own terminal, run:

```bash
/path/to/installed/novadde/scripts/auth.sh login
/path/to/installed/novadde/scripts/auth.sh status
```

Login opens the production sign-in and consent page. Approve **Novadde Plugin** for
`jobs:read` and `jobs:write`, then reconnect MCP or start a new session. The temporary
callback listener binds only to `127.0.0.1`. A declined or timed-out login preserves an
existing connection. Hooks and background refreshes never open a browser.

The MCP connection, hooks and Claude watcher share `~/.config/geodesic/novadde-oauth.json`
(mode 600). Tokens are bound to production, the MCP resource, the client and your account.
Refreshes are serialized across processes. If a refresh was revoked, expired or interrupted,
run `auth.sh login` again. OAuth failures never switch to an API key or another account.
Never paste credentials into a conversation or put them on command arguments.

To revoke the connection and clear it locally:

```bash
/path/to/installed/novadde/scripts/auth.sh logout
```

Reconnect the clients afterwards. Public catalog reads remain available without login.
If logout cannot reach production, it disables the local connection and reports failure;
retry logout or revoke **Novadde Plugin** from https://platform.geodesiclab.com/keys.

**Migration from 0.1.x:** development accounts, keys and credits are separate from production.
Install/update 0.2.0, then log into the intended production account. Existing key files and
keychain settings are not selected automatically. Disconnect any host-native OAuth connection
for this MCP server so all components use the plugin's shared login. Both hosts keep the plugin
identity `novadde@novadde-plugin` and server identity `model_platform`.

**Explicit legacy API-key mode:** save a production key in the existing local
`~/.config/geodesic/model-platform.env` file (mode 600), then run the installed command
`auth.sh legacy-api-key`. It verifies and binds the selected account. Environment API keys
are ignored, and there is no automatic fallback. To return to OAuth, run `auth.sh login`.

`/novadde:status` reports your account, allowance and recent jobs; `/novadde:examples` offers
worked requests. Use the `novadde:` prefix: bare `/status` is Claude Code's own status screen.

## What enabling it does

**It takes over the session.** The plugin activates its own agent as the main thread, and that
agent's prompt replaces Claude Code's own — which is exactly what the deployment does, where the
operator's prompt runs in `replace` mode. While the plugin is enabled, every session in every
project is NovaDDE. Disable it (`/plugin`, or `claude plugin disable novadde@novadde-plugin`) to get
plain Claude Code back.

What you get:

| | |
|---|---|
| **The prompt** | The deployment's operator prompt, less two passages (below), plus its workspace and MCP briefs and its response-quality rule, in the order it assembles them |
| **The models** | The Model Platform's MCP endpoint: the catalog, jobs, pipelines, artifacts and staging — 13 containerised models on the lab's GPUs |
| **The skills** | 31 science skills vendored from `geodesic-science-skills`: binder campaigns, antibody numbering and liabilities, ipSAE, MD, RDKit, literature, figures, write-up |
| **Job notifications** | In the interactive CLI, after the shared production OAuth login, a background watcher polls your jobs and tells Claude when one finishes, so the agent ends its turn at `submit_job` instead of burning context polling. Where Claude Code runs no plugin monitors (Claude Desktop, `claude -p`, the Agent SDK, the GitHub Action, Bedrock, Vertex, Foundry, or with `DISABLE_TELEMETRY` or `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` set), and when the shared connection is missing or refused, the session brief says notifications are off, and the agent gives you the job's id and checks on it when you ask |

## On Codex

The same plugin, without the parts only Claude Code can run:

| | Claude Code | Codex |
|---|---|---|
| **The models** (the Model Platform's MCP tools) | yes | yes. `.codex.mcp.json` pre-approves the tools that only read; `submit_job`, `cancel_job`, `stage_file`, `submit_pipeline_run` and `cancel_pipeline_run` are left to ask for approval, because they spend credits or change a run, as is any tool the platform adds before the plugin sorts it |
| **The skills** | yes | yes, under the same `novadde:` names |
| **The prompt** (NovaDDE as the session's agent) | yes | no: the Codex manifest carries no agent or system prompt, so Codex keeps its own |
| **The session brief, the per-message reminder, Refuse job submission** | yes | no: they are hooks and settings, and the Codex manifest loads no hooks (`"hooks": {}`) on purpose, since Codex would otherwise load Claude's as untrusted Codex hooks |
| **Job notifications** | in the interactive CLI | no: ask the agent, which checks with `get_job` or `wait_for_job` |
| **`/novadde:setup`, `/novadde:status`** | run the plugin's scripts | resolve the installed script path or use `get_profile`, `get_usage` and `list_jobs` through MCP |

Both hosts share the OAuth store and the same generated authentication helper. One login
connects both clients and the watcher.

## Settings

Claude Code only. Set them in a session with `/plugin configure novadde@novadde-plugin`, or from a shell with
`claude plugin install novadde@novadde-plugin --config KEY=VALUE` (which works on an
already-installed plugin):

| Setting | Default | |
|---|---|---|
| Per-message reminder | empty | The deployment's `user_message_suffix`, appended to every message you send |
| Refuse job submission | off | Denies `submit_job` and `submit_pipeline_run`. The deployment ships this off too |

The platform is always `https://platform.geodesiclab.com`. URL overrides in legacy key
files are ignored. OAuth is selected by default; legacy API keys require explicit selection.

Without login you still get `list_models`, `describe_model`, `get_model_readme`,
`list_pipelines` and `describe_pipeline`. Protected account and job tools refuse access.

## Where this differs from the deployment

Stated rather than papered over.

- **The prompt leaves out two passages** that stay with the deployment: principle 0, and the
  second paragraph of the introduction. The rest is verbatim, so it routes design work through the
  three Design Studios at app.geodesiclab.com and mentions a Files panel and a Job Dashboard. Here
  there are the MCP pipelines (`list_pipelines`, `submit_pipeline_run`) and your working directory
  instead. The agent will occasionally point at something a terminal does not have.
- **Your model and account are your own.** The deployment pins a model per conversation and injects
  its own credential; this uses whatever your Claude Code is already running.
- **The bio tools are not installed.** The deployment's image carries ANARCI, BLAST+, HMMER, MAFFT,
  MUSCLE, MMseqs2, TM-align, DSSP and NumPy on `PATH`, and several skills assume them. Install what
  you need; the skills say which.
- **It costs context.** The prompt is 23 KB and 27 skill descriptions ride in every request on top
  of it. `claude plugin details novadde` shows the bill.
- **One skill is left behind:** the science repo's `test` (since renamed `internal-test`), which
  checks that its own `install.sh` symlinked skills into `~/.claude/skills/`. A plugin ships them
  elsewhere, so the check would fail by construction.

## Development

```bash
claude --plugin-dir ./plugins/novadde        # load it without installing
plugins/novadde/scripts/check.sh             # what CI runs
plugins/novadde/scripts/build-agent.sh       # regenerate agents/novadde.md from prompt/
plugins/novadde/scripts/sync-prompt.sh       # re-pull the operator prompt (needs NOVADDE_CONSOLE_URL)
plugins/novadde/scripts/sync-skills.sh       # re-vendor the science skills
```

See `CLAUDE.md` for what is generated and what is hand-written.

## License

Copyright (c) 2026 Geodesic Intelligence. You may install the plugin and use it with Geodesic
Intelligence's services; [LICENSE](LICENSE) has the terms. Thirteen of the vendored skills are
other people's work and keep their own licenses, MIT and Apache-2.0, which
[THIRD-PARTY-NOTICES.md](plugins/novadde/THIRD-PARTY-NOTICES.md) reproduces.

## Release verification

`tests/live/test_public_oauth.py` is an opt-in production OAuth test, separate from offline CI.
It requires the expected public commit/version, both authenticated client executables, real
browser approval in a dedicated account, and an existing completed job and artifact checksum.
It installs the public marketplace package and checks actual client tool events, refresh,
watcher deduplication and revocation. Missing prerequisites never count as a passing release.
See `python3 tests/live/test_public_oauth.py --help` for the operator command.
