---
name: kernel-verify-before-done
description: Use before saying done, fixed, passing or works. Find the project's own test runner (pytest may not be installed), run the command that proves the claim, and read its exit code and output. Zero tests collected, all skipped, or a pipe that hides a failure is not evidence. Coding work, not an OS or Jupyter kernel.
category: code-quality
---

# Verify before you say it is done

A claim is verified when you ran the command that would have shown it false, and read what that
command printed and returned. Anything else is a guess, and must be reported as one.

## Check first: what runs the tests here

What is installed differs between images and between projects, so look before you assume.

```bash
pwd; git rev-parse --show-toplevel 2>/dev/null
ls pyproject.toml uv.lock poetry.lock setup.cfg tox.ini noxfile.py Makefile package.json 2>/dev/null
grep -nE '^[A-Za-z_.-]*(test|check|lint)[A-Za-z_-]*:' Makefile 2>/dev/null
grep -nE '^\[(tool\.(pytest|uv|hatch|tox)|dependency-groups|project\.optional-dependencies)' pyproject.toml 2>/dev/null
grep -nE '^\s*(- )?run:' .github/workflows/*.y*ml 2>/dev/null | head -20      # what CI runs
jq -r '.scripts // {} | to_entries[] | "\(.key): \(.value)"' package.json 2>/dev/null
for c in pytest uv make node npm; do printf '%s: ' "$c"; command -v "$c" || echo missing; done
python3 -m pytest --version 2>&1 | head -1          # "No module named pytest" = not installed
cat /sys/fs/cgroup/cpu.max    # "100000 100000" = 1 CPU; `nproc` reports the host's cores
```

Then use the first of these that applies:

1. **The project says how.** Run the Makefile target, `tox`/`nox` session, `package.json`
   script or CI step exactly as it is written.
2. **A uv project** (`uv.lock`, or `[tool.uv]` / `[dependency-groups]`): `uv run pytest`. If
   pytest is not declared, that fails with `error: Failed to spawn`; use
   `uv run --with pytest pytest` instead.
3. **A plain Python project with no pytest:** make a project venv once, then run through it by
   path:
   ```bash
   uv venv .venv && uv pip install --python .venv/bin/python pytest -e .
   .venv/bin/python -m pytest -q
   ```
   Drop `-e .` if the project is not an installable package. Both installs need the package
   index. Check it first with
   `curl -sS -o /dev/null -w '%{http_code}\n' https://pypi.org/simple/pytest/`, which should
   print 200. Do not commit `.venv/`.
4. **Node:** `npm test` or the named script, after `npm ci` if `node_modules` is missing.

Never use `/agent-server/.venv/bin/pytest`, and never install into that venv: it belongs to the
agent server this session runs in. Do not `pip install` into the system `python3` either. For a
general-purpose venv, see `environment-orientation`.

Size parallelism by `cpu.max`, not by `nproc`. With `-n auto` or `-j$(nproc)`, a one-CPU quota
behind an 8-core host starts eight workers under one memory limit.

## Run it, and read the exit code

```bash
log=$(mktemp); <command> > "$log" 2>&1; echo "exit=$?"; tail -n 40 "$log"   # a log you read now
```

`mktemp`, not a fixed name such as `/tmp/run.log`: one container serves every conversation this
user has open, so a fixed path in `/tmp` can be overwritten by another conversation's run while
you read it.

* **Read the exit code of the command that matters.** A pipeline reports its *last* command's
  status: `false | tail -1; echo $?` prints `0` (measured). Redirect to a file as above, or run
  `set -o pipefail` first (bash).
* **Empty output is not success.** Neither is "no errors" scrolling past on the first screen.
* **A run stopped by a time limit did not pass.** `timeout` exits 124 when it fires; a process
  killed for memory exits 137.

pytest's exit codes:

| code | meaning |
|---|---|
| 0 | every collected test passed |
| 1 | some tests failed |
| 2 | interrupted, e.g. by a collection error |
| 3 | internal error |
| 4 | usage error, e.g. a path that does not exist |
| 5 | **no tests were collected** |

Read the summary line (`N passed, M skipped, K failed`). Zero collected, or everything skipped,
verifies nothing. `-rs` prints why each test was skipped.

## Make sure you checked the right thing

```bash
git rev-parse --short HEAD; git status --short; git diff --stat          # the change you think you made
<runner python> -c 'import sys, pkg; print(sys.executable, pkg.__file__)' # this checkout, not an installed copy
```

* **A server:** request it, and read the status code:
  `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>/<path>`.
  A process that started is not a service that answers. Port 8000 is the agent server hosting
  this session, so an answer from `:8000` is not your app.
* **A file you produced:** check that it exists and has a sensible size and content (`ls -l`,
  `head`). Parse it if it is structured, for example
  `python3 -c 'import json, sys; json.load(open(sys.argv[1]))' out.json`.
* **A fix for a reported error:** run the user's original failing command again, not only your
  new test.

## Report

* **The evidence:** the commands you ran, their exit codes, and the relevant output lines,
  trimmed.
* **What you did not run:** say "not run".
* **What you inferred without running it:** say "inferred".
* **Anything unexpected:** skipped tests, warnings, a failure that was there before your change.
  Report it; do not bury it.
