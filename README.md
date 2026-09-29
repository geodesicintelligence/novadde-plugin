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

For now the plugin works against the Model Platform's development deployment,
https://dev-platform.geodesiclab.org. Its accounts, API keys and credits are its own: a key minted
on platform.geodesiclab.com is refused there, so mint one on the development deployment as below.

The key lives in one file, `~/.config/geodesic/model-platform.env` (mode 600), and nowhere else: the
MCP connection, the hooks and the background job watcher all read it.

1. Open https://dev-platform.geodesiclab.org and choose **Continue with Google**. Your first sign-in
   creates the account.
2. Open **API Keys** at https://dev-platform.geodesiclab.org/keys and create a key labelled
   `novadde-plugin`. Leave the model list empty: a key restricted to some models is refused here.
   Copy the secret.
3. **In a terminal, not in any chat**, save it. The key is read hidden, never goes on a command
   line, and the file's other lines are kept; an older `MODEL_PLATFORM_API_KEY=` line, with or
   without `export`, is replaced.

   ```bash
   bash -c 'set -e; f="$HOME/.config/geodesic/model-platform.env"; read -rsp "Model Platform key (mp_...): " k; echo
   case "$k" in mp_*) ;; *) echo "That is not an mp_ key." >&2; exit 1;; esac
   mkdir -p "${f%/*}"; umask 077; touch "$f"; { grep -Ev "^[[:space:]]*(export[[:space:]]+)?MODEL_PLATFORM_API_KEY=" "$f" || true; printf "MODEL_PLATFORM_API_KEY=%s\n" "$k"; } > "$f.new"
   mv "$f.new" "$f"; chmod 600 "$f"; echo "Saved to $f. Start a new Claude Code or Codex session."'
   ```

4. Start a new session.

Never paste the key into a conversation. If a key leaks, delete it at
https://dev-platform.geodesiclab.org/keys and mint a new one; a key the platform refuses is replaced
the same way. `/novadde:setup` walks through these steps from inside a session, and

```
/novadde:status
```

says whether it worked. `/novadde:examples` offers the three worked requests from NovaDDE's own
home screen if you want somewhere to start.

Type the `novadde:` prefix. Bare `/setup` and `/examples` reach the same skills while nothing else
you have installed uses those names, but bare `/status` is always Claude Code's own status screen,
which knows nothing about the Model Platform.

**Upgrading from 0.1.0**, where the key was a plugin setting kept in your OS keychain: that copy is
no longer read. Save the key to the file once, as above. Until you do, a session says there is no
key in `~/.config/geodesic/model-platform.env` and asks you to run `/novadde:setup`.

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
| **The skills** | 24 science skills vendored from `geodesic-science-skills`: binder campaigns, antibody numbering and liabilities, ipSAE, MD, RDKit, literature, figures, write-up |
| **Job notifications** | In the interactive CLI, once the key is saved in `~/.config/geodesic/model-platform.env`, a background watcher polls your jobs and tells Claude when one finishes, so the agent ends its turn at `submit_job` instead of burning context polling. Where Claude Code runs no plugin monitors (Claude Desktop, `claude -p`, the Agent SDK, the GitHub Action, Bedrock, Vertex, Foundry, or with `DISABLE_TELEMETRY` or `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` set), and when the key is missing or the platform refuses it, the session brief says notifications are off, and the agent gives you the job's id and checks on it when you ask |

## On Codex

The same plugin, without the parts only Claude Code can run:

| | Claude Code | Codex |
|---|---|---|
| **The models** (the Model Platform's MCP tools) | yes | yes. `.codex.mcp.json` pre-approves the tools that only read; `submit_job`, `cancel_job`, `stage_file`, `submit_pipeline_run` and `cancel_pipeline_run` are left to ask for approval, because they spend credits or change a run, as is any tool the platform adds before the plugin sorts it |
| **The skills** | yes | yes, under the same `novadde:` names |
| **The prompt** (NovaDDE as the session's agent) | yes | no: the Codex manifest carries no agent or system prompt, so Codex keeps its own |
| **The session brief, the per-message reminder, Refuse job submission** | yes | no: they are hooks and settings, and the Codex manifest loads no hooks (`"hooks": {}`) on purpose, since Codex would otherwise load Claude's as untrusted Codex hooks |
| **Job notifications** | in the interactive CLI | no: ask the agent, which checks with `get_job` or `wait_for_job` |
| **`/novadde:setup`, `/novadde:status`** | run the plugin's scripts | the scripts cannot run there (`${CLAUDE_PLUGIN_ROOT}` is not substituted and the sandbox has no network), so the skills use the MCP tools instead: `list_jobs` shows whether the key works, and the credits come from `get_usage` where the platform serves it |

The key is the same file on both hosts, `~/.config/geodesic/model-platform.env`, read by the same
helper, so a key saved once works in either.

## Settings

Claude Code only. Set them in a session with `/plugin configure novadde@novadde-plugin`, or from a shell with
`claude plugin install novadde@novadde-plugin --config KEY=VALUE` (which works on an
already-installed plugin):

| Setting | Default | |
|---|---|---|
| Per-message reminder | empty | The deployment's `user_message_suffix`, appended to every message you send |
| Refuse job submission | off | Denies `submit_job` and `submit_pipeline_run`. The deployment ships this off too |

Neither the key nor the platform is a setting. The key is only ever read from
`~/.config/geodesic/model-platform.env`, and the platform is always
`https://dev-platform.geodesiclab.org`: a `MODEL_PLATFORM_URL` line in that file, as lab machines
have, is ignored.

Without a key you still get the catalog: `list_models`, `describe_model`, `get_model_readme`,
`list_pipelines`, `describe_pipeline`. Everything that submits or reads a run refuses.

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
