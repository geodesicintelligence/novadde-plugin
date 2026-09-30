---
name: setup
description: Connect the installed Novadde plugin to the production Model Platform through shared OAuth, verify its account, reconnect, or select legacy API-key mode explicitly.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/setup-credential.sh --check)
---

# Connect Novadde to production

Production is https://platform.geodesiclab.com. OAuth is the default for MCP, hooks
and the supported interactive Claude watcher.

1. Resolve this installed skill's directory, then the plugin root two levels above
   it. In Claude `${CLAUDE_PLUGIN_ROOT}` is the root. In Codex use the absolute path
   of this SKILL.md supplied by the host; do not depend on Claude environment variables.
2. Run the bundled `scripts/auth.sh status` from that absolute root. Show the account
   it reports, without reading or printing the credential store.
3. If login is needed, give the user the concrete command
   `"/absolute/installed/plugin/scripts/auth.sh" login` to run in their own terminal.
   The browser signs into production and asks approval for **Novadde Plugin**. Do not
   initiate browser login from a background hook or request secrets in this conversation.
4. After approval, run status again and ask the user to reconnect MCP or start a new
   session. Call `get_profile`, `get_usage` and `list_jobs` through MCP to verify the
   connection and relay the account and allowance exactly.

The private store is `~/.config/geodesic/novadde-oauth.json`, mode 600. OAuth failure,
revocation, or an uncertain refresh exchange requires login again; it never selects an
API key or another account. Declining or timing out leaves an existing connection unchanged.
To revoke access use the installed `auth.sh logout`, then reconnect clients. Public
catalog reads remain usable without credentials.

For a requested legacy connection only, have the user save a production API key in
`~/.config/geodesic/model-platform.env` locally with mode 600, then give the installed
`auth.sh legacy-api-key` command. Never put the secret on argv or ask for it in chat.
Existing 0.1.x development keys and keychain entries are not migrated automatically.
Disconnect host-native OAuth for this server if it would override the plugin's shared login.

Claude background notifications are supported only in an interactive CLI where monitors
are available. Codex checks progress through MCP when asked; it has no background watcher.
