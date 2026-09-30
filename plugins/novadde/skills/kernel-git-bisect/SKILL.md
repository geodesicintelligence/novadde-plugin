---
name: kernel-git-bisect
description: Use when something that used to work now fails and several commits lie between - a regression, "it worked last week", "which commit broke this". Find the first bad commit with git bisect run and a time-bounded check script (exit 125 skips a commit), then git bisect reset. Coding work, not an OS or Jupyter kernel.
category: code-quality
---

# Finding the commit that broke it

`git bisect run` tests about log2(N) commits instead of you reading N diffs. It never opens an
editor and never commits, so it works without an editor or a git identity (measured).

## Check first

```bash
cd "$(git rev-parse --show-toplevel)" && git status --short   # run everything from the top
command -v timeout                                              # bounds each step
cat /sys/fs/cgroup/cpu.max    # "100000 100000" = 1 CPU; `nproc` reports the host's cores
```

`git bisect start` refuses to begin while a tracked file has changes that a checkout would
overwrite. Commit them, or set them aside with `git stash`, which needs no identity.

## 1. Write the check as a script inside `.git`

Bisect checks out old commits over the work tree. A script in the work tree can be overwritten,
or deleted by an old commit that tracks the same path. Put it inside the repository's `.git`
directory instead. Checkouts never touch it, it is never committed, it persists on
`/workspace`, and it goes away with the repository. Not `/tmp`: that is lost on restart. (In a
linked worktree or a submodule `.git` is a file; use the path `git rev-parse --git-dir` prints.)

```bash
cat > .git/bisect-check.sh <<'EOF'
#!/bin/sh
# exit 0 = good, 1 = bad, 125 = cannot judge this commit (bisect skips it)
make -s build >/dev/null 2>&1 || exit 125     # does not build: unknown, not bad
timeout 300 <runner> <the one failing test> >/dev/null 2>&1
rc=$?
case $rc in
  0) exit 0 ;;
  1) exit 1 ;;     # the test ran and failed: bad
  *) exit 125 ;;   # 124 timeout, 137 OOM kill, 126/127 missing tool, 2-5 pytest could not run
esac
EOF
```

* Replace the build line and `<runner>` with the project's own. Check that the runner exists
  first: `python3 -m pytest` is not installed on every image. `kernel-verify-before-done` covers
  finding it.
* Keep the check to the one failing case. There is one CPU, and it runs once per step.

Map every "could not tell" outcome to 125. What `git bisect run` does with other codes
(measured, git 2.47):

* **1-127 except 125 counts as bad.** A 124 from `timeout` on good commits made bisect blame
  an innocent commit.
* **128 or more aborts the run.** An OOM kill's 137 stopped it with
  `exit code 137 ... is < 0 or >= 128`, and left bisect in progress on a detached HEAD.
* **git does not test your endpoints.** It runs the good end only when the first step exits 126
  or 127, to catch a missing script (`bogus exit code 127 for good revision`). A check that
  failed everywhere, good end included, finished with exit 0 and named the commit right after
  the good end as the first bad one. Step 2 is what catches that.

## 2. Prove both endpoints

Run this as one block, so `start` still holds your branch at the end:

```bash
start=$(git symbolic-ref -q --short HEAD || git rev-parse HEAD)
git checkout -q <known-good> && sh .git/bisect-check.sh; echo "good end: $?"   # must be 0
git checkout -q <known-bad>  && sh .git/bisect-check.sh; echo "bad end: $?"    # must be 1
git checkout -q "$start"
```

If the good end is not 0, or the bad end is not 1, the script does not measure the bug. Fix the
script before bisecting.

## 3. Run it

```bash
git bisect start <known-bad> <known-good>
git bisect run sh .git/bisect-check.sh > .git/bisect-run.log 2>&1; echo "bisect run exit: $?"
tail -n 25 .git/bisect-run.log
```

The log goes to a file, not into a pipe: a pipe would report `tail`'s exit status instead of
bisect's.

* **Merge-heavy history:** `git bisect start --first-parent <bad> <good>` walks the mainline only.
* **A flaky check:** run it several times inside the script, and exit 125 when the runs disagree.
* **By hand:** `git bisect good`, `git bisect bad` and `git bisect skip` work at any point.
* **Longer than one tool call** (steps × about log2(N)): run it as a background job that writes
  `.git/bisect-run.log`. See `kernel-background-processes`, including why an idle container is
  stopped. The bisect state is kept in `.git` on `/workspace`, so it survives a restart.
  `git bisect log` shows how far it got, and running `git bisect run ...` again continues from
  there (measured after an aborted run: it resumed and found the right commit).

## 4. Read the answer, and confirm it

The run ends with `<sha> is the first bad commit`. Copy that hash from the output; never retype
it. Then confirm it:

```bash
git show --stat <sha>
git checkout -q <sha>^ && sh .git/bisect-check.sh; echo "parent: $?"    # expect 0
git checkout -q <sha>  && sh .git/bisect-check.sh; echo "culprit: $?"   # expect 1
```

If skipped commits sit next to the answer, bisect prints `The first bad commit could be any of:`
and a list, and exits 2. Report the list. Do not pick one.

## 5. Always clean up

```bash
git bisect reset                                  # back to the branch you started on (measured)
rm -f .git/bisect-check.sh .git/bisect-run.log
```

Run `git bisect reset` after an aborted run as well. Until you do, HEAD stays detached on
whatever commit bisect last checked out.

## Report

* the first bad commit, as bisect printed it, and its subject line;
* the check script's test command;
* the check's result at that commit and at its parent;
* any commits that were skipped.
