# Working on this repo

The plugin is `plugins/novadde/`; the marketplace manifest at the repo root points at it. They are
two manifests on purpose: pointed at one directory holding both, `claude plugin validate` reports
only the marketplace.

Codex installs the same plugin from its own three files: `.agents/plugins/marketplace.json`,
`plugins/novadde/.codex-plugin/plugin.json` and `plugins/novadde/.codex.mcp.json`. Codex keys --
`tools`, `http_headers_helper`, the timeouts, `disabled_tools` -- go in `.codex.mcp.json` only. A
`tools` table in `.mcp.json`, even an empty one, makes Claude Code drop the whole server without an
error while `claude plugin validate --strict` still passes it, so `.mcp.json` holds only the four
keys Claude reads. `tests/test_codex_package.py` holds the pair to three things: the two manifests
carry one version, the two MCP files one key helper, and `.mcp.json` no key outside those four.

- `plugins/novadde/agents/novadde.md` is **generated**. Edit the pieces under `prompt/` and run
  `plugins/novadde/scripts/build-agent.sh`; never edit the agent file by hand. The build takes the
  verbs the MCP brief names from the platform's public `tools/list` (no key; failing that, the last
  answer cached under `~/.cache/novadde`) and refuses when it has neither, so a rebuild waits for
  the platform. `build-agent.sh --check` needs no network: it rebuilds from `prompt/` and the verbs
  recorded in `prompt/.built-verbs`, compares byte for byte, and is what `check.sh` runs.
- `prompt/system-prompt.md` and `prompt/response-quality.md` are the deployment's own text, less the
  passages `scripts/lib/write_prompt.py` withholds (`WITHHELD`, recorded by digest so this repo
  never holds their text). They are not ours to reword: `scripts/sync-prompt.sh` re-pulls them from
  the deployment's console, whose internal address it takes from `NOVADDE_CONSOLE_URL`, and stops if
  a withheld passage has changed there. Read the diff before committing it.
- `plugins/novadde/skills/` is vendored from `geodesic-science-skills` by `scripts/sync-skills.sh`,
  which also rewrites the container script paths. Fix a science skill in that repo, then re-sync.
- `LICENSE` and `plugins/novadde/LICENSE` are one file in two places, because an install copies only
  the plugin. A vendored skill that is someone else's work is named in
  `plugins/novadde/THIRD-PARTY-NOTICES.md`, with its license. `tests/test_licensing.py` holds both.
- This repo is published, so nothing internal goes in it: no internal addresses or hostnames, and
  no references to the internal tracker. Its public copy is published from the internal repository,
  whose PUBLISHING.md says how.
- `plugins/novadde/scripts/check.sh` is what CI runs. Run it before pushing.
- Fetch the latest `main`, merge and push there; releases are cut with `claude plugin tag --push`.
