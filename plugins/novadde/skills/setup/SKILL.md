---
name: setup
description: Connect this session to the Geodesic Model Platform, or work out why it is not connected. Use when submit_job or any job tool answers that it needs a credential, when the session brief or /novadde:status says there is no key or that the platform refused it, or when a key has been revoked and has to be replaced.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/setup-credential.sh --check)
---

# Connecting to the Model Platform

The catalog half of the platform is open: `list_models`, `describe_model`, `get_model_readme`,
`list_pipelines` and `describe_pipeline` answer with no credential at all. Everything that submits a
run or reads one back needs an `mp_` API key.

The key lives in one file, `~/.config/geodesic/model-platform.env` (mode 600), and nowhere else. The
MCP connection, the hooks and the job watcher all read that file, whichever host this is.

For now the plugin uses the platform's development deployment, https://dev-platform.geodesiclab.org,
whose accounts and keys are its own. A key minted on platform.geodesiclab.com is refused there, so a
user who has one mints another on the development deployment.

**Never ask for the key in this conversation, and never run the saving command yourself.** The user
mints the key in their browser and saves it from their own terminal, so it never has to pass
through here. If they paste one anyway, tell them to delete it on the API Keys page and mint
another: a key that has been in a conversation cannot be taken back out of it.

## The steps to give the user

1. Open https://dev-platform.geodesiclab.org and choose **Continue with Google**. The first sign-in
   creates the account.
2. Open **API Keys** at https://dev-platform.geodesiclab.org/keys and create a key labelled
   `novadde-plugin`. Leave the model list empty: a key restricted to some models is refused here.
   Copy the secret.
3. **In a terminal, not in any chat**, run this and paste the key at the prompt. The key is read
   hidden, never goes on a command line, and the file's other lines are kept; an older
   `MODEL_PLATFORM_API_KEY=` line, with or without `export`, is replaced.

   ```bash
   bash -c 'set -e; f="$HOME/.config/geodesic/model-platform.env"; read -rsp "Model Platform key (mp_...): " k; echo
   case "$k" in mp_*) ;; *) echo "That is not an mp_ key." >&2; exit 1;; esac
   mkdir -p "${f%/*}"; umask 077; touch "$f"; { grep -Ev "^[[:space:]]*(export[[:space:]]+)?MODEL_PLATFORM_API_KEY=" "$f" || true; printf "MODEL_PLATFORM_API_KEY=%s\n" "$k"; } > "$f.new"
   mv "$f.new" "$f"; chmod 600 "$f"; echo "Saved to $f. Start a new Claude Code or Codex session."'
   ```

4. Start a new session. The MCP connection reads the key only when it connects, so a session that
   was already open keeps connecting without it. The hooks read the file each time they run, and a
   job watcher that started with no key picks one up on its next pass; a watcher whose key the
   platform refused has stopped, and only a new session starts it again.

A key that was deleted at `/keys`, or that the platform refuses for any other reason, is replaced
the same way, from step 2.

## Finding out what is there

In Claude Code:

```bash
"${CLAUDE_PLUGIN_ROOT}"/scripts/setup-credential.sh --check
```

Exit 3 means there is no key in the file, exit 4 means the platform refused the one that is there.
Say which of the two it is rather than describing both. It prints only the first and last few
characters of the key.

On any host, once the new session has started, listing the account's jobs (`list_jobs`) shows
whether the key works: it answers, even with an empty list, or it refuses. The catalog tools are no
test, because they answer with no key at all.

## Afterwards

`/novadde:status` should show the credential, the account's allowance and any recent jobs.
