---
name: status
description: Report how this session is connected to the Geodesic Model Platform - credential, the account's allowance (daily submissions or weekly credits), recent jobs, and whether the background job watcher can see them. Use before submitting work, when the user asks what is running, or when a job tool behaves unexpectedly.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/status.sh)
---

# Where this session stands

```bash
"${CLAUDE_PLUGIN_ROOT}"/scripts/status.sh
```

Resolve the installed plugin path as in the setup skill. If the script cannot run, call
`get_profile`, `get_usage` and `list_jobs` through the installed MCP connection and report them.

Report what it prints. Four things are worth reading carefully rather than summarising away:

- **Authentication and account**. OAuth is stored in `~/.config/geodesic/novadde-oauth.json`
  and shared by MCP, hooks and the watcher. No connection means protected tools and job
  notifications are unavailable. Point at `/novadde:setup`; never print the store's secrets.
- **Quota**. The platform is the only thing that knows this. Relay the numbers exactly and never
  estimate one. It counts in one of two units, and the line says which: submissions per UTC day,
  or credits per week with a purchased balance beside them. The week's credits are spent first,
  so an account with none left this week can still run on purchased ones. A purchased balance can
  be below zero, when runs cost more than quoted after the week ran out; relay it as the negative
  number it is, because the next purchase covers that part first. Either way the limit is per
  person, not per session, and no line at all means the platform did not say.
- **Recent jobs** are the account's, not this session's. A job the user started in the web app or
  in another session appears here, which is correct and worth saying once.
- **Tools served** is what the platform's MCP endpoint lists right now. A number lower than the
  tool list you can see means the probe failed, not that tools were withdrawn.

This reads state and changes nothing. To fix a missing or refused credential, use `/novadde:setup`.
