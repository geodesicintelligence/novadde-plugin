---
name: kernel-git-identity-and-commits
description: Use before the first git commit in a repo, or on "Author identity unknown" or "Please tell me who you are". No git identity is set up here - ask the user for the name and email, set them for this repo only, never invent one. Commit with -m, stage by path, never force-push unless asked. Coding work, not an OS kernel.
category: code-hosting
---

# Git identity and commits

## Check first

```bash
git var GIT_AUTHOR_IDENT 2>&1 | head -3        # a name and email, or "Author identity unknown"
git config --show-origin --get-regexp '^user\.' # where an identity comes from, if there is one
ed=$(git var GIT_EDITOR); echo "GIT_EDITOR: $ed"; command -v "${ed%% *}" >/dev/null || echo "NOT installed"
git status --short | head -30
```

What these showed when this skill was written (git 2.47):

* There is no system or global git config.
* The runtime uid has no passwd entry, so git cannot guess a name either. `git commit` stops
  with `Author identity unknown`, then `fatal: unable to auto-detect email address`, and exits
  128. `merge`, `rebase` and `cherry-pick` also commit, and fail the same way (their message
  says `Committer identity unknown`). `stash` and `bisect` work without an identity.
* `GIT_EDITOR` was not the same on every deployment: `code --wait` (not installed) on one,
  `true` on another. Read it; do not assume it.

Trust the check, not this list: the user may already have set an identity.

## Setting an identity

Git's own message suggests `git config --global user.email "you@example.com"`. Do not follow it
as written.

1. **Ask the user** which name and email to commit as, unless they already said so in this
   conversation.
2. **Never invent an identity.** That rules out a placeholder such as `you@example.com` or
   `agent@localhost`, a name made up for yourself, and an address lifted from `git log`. If the
   user says "use the one in the history", show them the exact one
   (`git log -1 --format='%an <%ae>'`) and wait for a yes.
3. **Set it for this repository only:**
   ```bash
   git config user.name "<name the user gave>"
   git config user.email "<email the user gave>"
   git var GIT_AUTHOR_IDENT                    # confirm
   ```
   Not `--global`. `HOME` is on the persistent volume and shared by every conversation this user
   has, so a global identity would silently sign later work in other repositories. Use
   `--global` only if the user asks for it.
4. **For a single commit** without storing anything:
   `git -c user.name="<name>" -c user.email="<email>" commit -m "..."`.

If the user will not give an identity, do not commit. Leave the changes in the work tree, or
write a patch (`git diff > change.patch`), and say so.

## Choosing what to commit

Your working directory is itself a git repository, with no commits when the conversation starts.
In a Claude Code session the platform can write files into it under `.claude/` (in some
conversations, a copy of every skill), untracked and not ignored. Scratch such as `.venv/`,
`.runs/` and logs lands there too. So `git add -A` or `git add .` would commit all of it.

```bash
git status --short                   # read every line: "??" is untracked, "?? .claude/" is not yours
git add path/one path/two            # stage by path
git diff --cached --stat             # exactly what will be committed
```

## Committing without an editor

Always give the message on the command line. A commit that would open an editor fails either
way: with a missing editor, git reports `there was a problem with the editor`; with
`GIT_EDITOR=true`, it reports `Aborting commit due to empty commit message` (both measured).

```bash
git commit -m "Fix off-by-one in window slicing" -m "The last residue was dropped when ..."
git commit -F - <<'EOF'
Subject line under 72 characters

Body: what changed and why.
EOF
git commit --amend --no-edit         # only on your own commit that is not pushed yet
git commit --no-edit                 # concludes a merge with its prepared message
git tag -a v1.2 -m "..."             # an annotated tag needs -m too
```

Follow the repository's own message style (`git log --oneline -10`). If a pre-commit hook fails,
fix what it reports. Use `--no-verify` only if the user asks. `kernel-merge-conflicts` covers
`merge --continue`, `rebase --continue` and the rest.

## Pushing and history

* Before promising a push, check that one can work: `git remote -v`, then `gh auth status` for a
  GitHub remote. Credentials are often not configured. If they are not, tell the user; do not set
  them up with a token you found.
* Push only when the user asked, and only to the branch they named. Never push to the default
  branch unasked.
* Never `git push --force`, `-f` or a `+refspec` unless the user explicitly asked. If they did,
  use `--force-with-lease`, and say what it overwrites.
* Do not amend, rebase or reset commits that are already pushed unless asked. Rewriting shared
  history breaks everyone else's clone.

## Report

* **The identity:** which one you used, and that it came from the user.
* **The commits:** each hash and subject, copied from `git log --oneline -n <k>`, never retyped.
* **The push state:** whether anything was pushed, and where.
