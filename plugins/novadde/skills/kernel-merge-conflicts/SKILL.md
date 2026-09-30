---
name: kernel-merge-conflicts
description: Use when git reports CONFLICT, a merge, rebase, cherry-pick or stash pop stops, or a file holds <<<<<<< markers. Read both sides and the base, resolve by intent, run the tests, then finish without an editor (GIT_EDITOR=true git rebase --continue, git commit --no-edit). Coding work, not an OS or Jupyter kernel.
category: code-quality
---

# Resolving merge conflicts

A conflict is two intents git could not combine. Keep both, prove the result works, and
finish the operation without an editor.

## Check first

```bash
git status                                    # which operation stopped, and the unmerged paths
git diff --name-only --diff-filter=U          # just the conflicted files
ed=$(git var GIT_EDITOR); echo "GIT_EDITOR: $ed"
command -v "${ed%% *}" >/dev/null || echo "that editor is NOT installed"
git var GIT_COMMITTER_IDENT >/dev/null 2>&1 || echo "no git identity: see kernel-git-identity-and-commits"
```

The editor differs between deployments, so read it rather than assume. If it names a program
that is not installed (the image's default, `code --wait`), every step that opens an editor fails
with `error: there was a problem with the editor 'code --wait'`. If it is `true`, those steps keep
git's prepared message. Every command below works in both cases.

`git -c core.editor=true ...` does **not** help. The `GIT_EDITOR` environment variable outranks
`core.editor`, so the step still fails (measured, git 2.47). Put `GIT_EDITOR=true` in front of
the command instead.

Git also needs a committer identity (measured with none set). `merge` exits 128 with
`Committer identity unknown` before it shows any conflict. `cherry-pick` and `rebase` stop at
the conflict and fail the same way at `--continue`, after you have resolved it.

## 1. Read both sides and the base before editing

```bash
git checkout --conflict=zdiff3 -- path/to/file   # re-mark the file with the base between ||||||| and =======
git show :1:path/to/file                          # the common ancestor
git show :2:path/to/file                          # "ours"
git show :3:path/to/file                          # "theirs"
git log --merge --oneline -- path/to/file         # the commits on each side that touched it
```

The base shows what each side changed *from*, which is what you judge intent by.
`--conflict=zdiff3` rewrites the file, so run it before you edit, not after. Then read the
commit messages of both sides. Resolve by what each change was for, not by which text looks
newer.

## 2. Which side is "ours" depends on the operation

| operation | `--ours` / stage 2 | `--theirs` / stage 3 |
|---|---|---|
| `git merge X` | your current branch | X |
| `git rebase U` | U, plus your commits replayed so far | **your** commit being replayed |
| `git cherry-pick C`, `git revert C` | your current branch | C (or its reversal) |
| `git stash pop` | your current branch | the stash |

The rebase row is the trap. Measured: rebasing `feat` onto `main`, `--ours` gave `main`'s line
and `--theirs` gave `feat`'s.

Take one whole side of a file only when that side is right for the whole file:

```bash
git checkout --theirs -- path/to/file && git add path/to/file
```

Never run that over `.` or a directory. For a lockfile or other generated file, take one side,
then regenerate it with the project's own tool (`uv lock`, `npm install --package-lock-only`),
rather than merging it by hand.

## 3. Resolve, then prove it

1. Edit each file so that both intents survive, and delete every marker line.
2. **Before** `git add`, look for leftover markers:
   ```bash
   git diff --check                                              # non-zero, "leftover conflict marker"
   grep -nE '^(<<<<<<<|\|\|\|\|\|\|\||=======|>>>>>>>)( |$)' path/to/file
   ```
   Once a file is staged, plain `git diff --check` no longer sees its markers. Use
   `git diff --cached --check` instead. Git commits a staged file with its markers still in it
   (measured).
3. `git add` each resolved file. Then `git diff --name-only --diff-filter=U` must print nothing.
4. Build, and run the tests that cover these files, **before** you continue. Continuing commits
   the resolution. `kernel-verify-before-done` covers finding the runner and reading the result.

## 4. Finish without an editor

```bash
git commit --no-edit                     # concludes a merge with git's prepared message
GIT_EDITOR=true git merge --continue     # the same
GIT_EDITOR=true git rebase --continue    # repeat 1-4 at each stop until status shows no rebase
GIT_EDITOR=true git cherry-pick --continue
GIT_EDITOR=true git revert --continue
```

Measured with the editor missing (git 2.47):

* bare `git merge --continue` and `git rebase --continue` failed;
* `cherry-pick --continue` and `revert` went through, because they do not edit when no
  terminal is attached.

The prefix is harmless everywhere, so always use it. `git merge --continue --no-edit` is refused
(`--continue expects no arguments`); use `git commit --no-edit` or `git commit -m "..."`.

A conflicted `git stash pop` keeps the stash. Resolve the file, `git add` it, and run
`git stash drop` only when the result is right.

`git rebase -i` edits its todo list with the same editor. With `GIT_EDITOR=true` it runs the list
unchanged. To change the list, script it with `GIT_SEQUENCE_EDITOR`. For example, this squashes
the second of the last two commits into the first (measured):
`GIT_SEQUENCE_EDITOR="sed -i '2s/^pick/squash/'" GIT_EDITOR=true git rebase -i HEAD~2`.

## 5. Backing out

* `git merge --abort`, `git rebase --abort` and `git cherry-pick --abort` each return to the
  state before the operation. `git reflog` shows where HEAD was, if you need to go further back.
* Before an abort, `reset --hard` or `checkout -- <file>` that throws away edits, tell the user
  what it discards.
* A rebase rewrites commits. Never `git push --force` a branch that is already pushed unless the
  user asked. If they did, use `--force-with-lease`.

## Report

Which files conflicted and how each was resolved; the tests you ran and their result; and the
final state, `git log --oneline -3`, copied from the output.
