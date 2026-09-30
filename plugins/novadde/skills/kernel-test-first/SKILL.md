---
name: kernel-test-first
description: Use when fixing a bug or adding a regression test or guard. Write the test first and watch it fail for the reported reason, fix the code, then put the bug back on purpose and watch the test go red again - a test that also passes against the bug guards nothing. Coding work, not an OS or Jupyter kernel.
category: code-quality
---

# Test first, then prove the test can fail

Most useless tests fail in the same way: they pass against the bug. Two moves stop that. The
test must fail **before** the fix, and fail **again** when the fix is taken out on purpose.

## Check first: can you run one test at all?

```bash
python3 -m pytest --version 2>&1 | head -1    # "No module named pytest": not installed for python3
ls pyproject.toml uv.lock setup.cfg tox.ini Makefile package.json 2>/dev/null
cd "$(git rev-parse --show-toplevel)" && git status --short   # the paths below are relative to the top
git rev-parse -q --verify HEAD >/dev/null || echo "no commits yet: do step 2's git add first"
```

Whether pytest is installed differs between images and projects, so check rather than assume.
If it is missing, use the project's own runner. `kernel-verify-before-done` shows how to find
one, and how to give the project a venv. Never install into `/agent-server/.venv`: it belongs
to the agent server this session runs in. Check any other venv before installing into it
(`test -w <venv> || echo read-only`).

## 1. Reproduce the bug as a failing test

* Write the smallest test that drives the reported behaviour and asserts the **correct** result.
* Run only that test, and read the failure. It must fail **for the reported reason**: the wrong
  value, or the exception the user saw.
* An `ImportError`, a collection error, a typo or a missing fixture is not a reproduction. Fix
  the test until the only thing wrong is the bug.
* If you cannot make it fail, you do not understand the bug yet. Say so before changing code.

## 2. Fix it, and watch the test pass

**Before** you change the code, stage the files you are about to change:
`git add -- src/pkg/module.py`. It needs no identity and makes no commit, but it gives `git diff`
a "before". Without it, in a repo with no commits (a new conversation's working directory
usually is one) or for an untracked file, `git diff` shows nothing and steps 3 and 6 cannot take
the fix out (measured). `git reset -q -- <file>` unstages it again, with or without commits.

Change the code under test, not the test. Run the one test, then the file or module around it.

**Python: stale bytecode can report the wrong code.** Python reuses a `.pyc` whose recorded
source mtime (whole seconds) and size still match. A same-size edit in the same second as the
last run, such as `-` → `+` or `==` → `!=`, or the `git apply` in steps 3 and 6, then runs the
*previous* version. Measured: with a sub-second test, step 3 reported "fix back: FAIL" in 5 of
5 runs, and a fix made right after a run still failed. Start every block that edits and then
runs Python with these two lines (each Bash call is a new shell, so an earlier `export` is gone):

```bash
export PYTHONDONTWRITEBYTECODE=1
find . -name __pycache__ -type d -not -path '*/.venv/*' -prune -exec rm -rf {} +
```

## 3. Prove the test can fail: put the bug back

Take the fix out, run the test, then put the fix back. Save the fix inside `.git` so that it
persists on `/workspace` and is never committed. Do not save it in `/tmp`: if the container
restarts between two steps, a fix saved there is gone, and the bug is left in the tree.

```bash
export PYTHONDONTWRITEBYTECODE=1                   # Python: see "stale bytecode", step 2
find . -name __pycache__ -type d -not -path '*/.venv/*' -prune -exec rm -rf {} +
git diff -- src/pkg/module.py > .git/fix.patch     # the fix: code only, not the test file
if test -s .git/fix.patch && git apply -R .git/fix.patch; then
  <run the one test>                               # the bug is back: it MUST fail, as reported
  git apply .git/fix.patch && rm .git/fix.patch    # the fix is back
  <run the one test>                               # it passes again
else echo "empty patch: nothing was taken out (stage the file first, step 2)"; fi
```

If the fix is already committed, take it out with `git show <sha> -- src/pkg/module.py | git apply -R`,
and put it back with `git checkout HEAD -- src/pkg/module.py`. None of this needs an editor or a
git identity.

If the test stays green with the bug back, it guards nothing. Rewrite it; do not ship it.

For a guard on new behaviour, where there is no bug to put back, break the code under test on
purpose instead: flip the comparison, return early, or delete the line the guard is about. Watch
the test go red, then restore the file with `git checkout -- <file>`. Only do this to a file whose
other changes are committed or saved, because `checkout --` also discards them.

## 4. Make the assertion able to fail

* Assert the value that tells right from wrong. A substring, a type or a truthy check that the
  buggy output also satisfies proves nothing.
* Assert the precondition of what you check. `all(ok(x) for x in items)` is true when `items` is
  empty, so assert first that `items` is not empty. A guard whose input never reaches the
  guarded path passes forever.
* Keep sleeps, wall-clock time, randomness and the network out of the assertion. Seed them,
  freeze them or fake them.

## 5. Make sure the test runs this checkout

An installed copy of the package can shadow the files you edited. The test then passes or fails
against code you did not change. Ask the interpreter the test runs under:

```bash
<runner python> -c 'import pkg, sys; print(sys.executable); print(pkg.__file__)'
```

The path it prints must be inside this repository. For the same reason, compare before and
after in one checkout (step 6), not in two: a second checkout can still import the first one
through an editable install.

## 6. Compare before and after, not just "green"

Run the surrounding suite without your change and with it, and compare **which tests fail**.
Pre-existing failures are not yours to hide. A new failure is yours even when the count is
unchanged.

Run it as one block (bash):

```bash
export PYTHONDONTWRITEBYTECODE=1                                  # Python: see step 2
find . -name __pycache__ -type d -not -path '*/.venv/*' -prune -exec rm -rf {} +
git diff -- <the source files you changed> > .git/change.patch    # not the new test files
rm -f .git/before.txt .git/after.txt
if test -s .git/change.patch && git apply -R .git/change.patch; then
  <run the suite> > .git/before.txt 2>&1
  git apply .git/change.patch && rm .git/change.patch
  <run the suite> > .git/after.txt 2>&1
  diff <(grep -E '^(FAILED|ERROR)' .git/before.txt | sort) <(grep -E '^(FAILED|ERROR)' .git/after.txt | sort)
else echo "no before run: nothing was taken out (stage the files first, step 2)"; fi
```

* Not `git stash`: in a repo with no commits it refuses (`You do not have the initial commit
  yet`), and a stash that did not happen makes "before" the same run as "after", so the
  comparison shows no difference and proves nothing (measured).
* The new test files stay in place, as intended: without your change they should fail.
* If the block is interrupted, your change is safe in `.git/change.patch`:
  `git apply .git/change.patch` brings it back.
* The `grep` patterns match pytest's `-rfE` summary lines, so run the suite with `-rfE`, or use
  the equivalent for another runner.

## Report

* the test you added, and the failure it gave before the fix;
* that it failed again with the fix taken out, and passed with it back in;
* the before/after comparison of failing tests.
