---
name: environment-orientation
description: Use FIRST, before concluding that a tool or package is missing, and whenever something needs installing. Says where this container actually keeps things — which interpreter `python3` is, what is already importable, which bioinformatics binaries are on PATH, which skills directory is really read, and how to install a package so it survives the next container recycle. Triggers include "module not found", "is X installed", "pip install", "set up an environment", "where do skills live", "what tools do I have", "ModuleNotFoundError", "command not found".
---

# Environment orientation

Read this before reporting that something is missing. A capability audit run inside
this product on 2026-09-22 judged eleven working skills unusable, and every one of
those judgements came from probing the wrong path — not from anything being absent.
The most expensive example: `antibody-numbering` was reported broken because
`import anarci` failed. That package is real, it is installed, and the skill never
uses it that way. `ANARCI` is a command.

## Where you are

```
/workspace/conversations/<id>/project   your working directory: the cwd of THIS conversation
/workspace/.oh                          conversations, persistence, worktrees; HOME is /workspace/.oh/home
/workspace                              THE ONLY DIRECTORY THAT PERSISTS
localhost:8000                          the agent server this conversation runs inside
```

Every conversation gets its own `project` directory; run `pwd` to see yours. There is also a
`/workspace/project`, and it is **empty and unused** — measured in every conversation on both
deployments. Looking there for your files, or for your skills, finds nothing, and the wrong
conclusion follows.

Port 8000 is taken by the server hosting this session, not by anything of yours. Do not bind
it, and do not kill the process listening on it: that is the session ending.

Everything outside `/workspace` — `/opt`, `/usr`, `/tmp`, site-packages — belongs to the
image and is restored from it whenever the container is recreated. That happens after
**600 seconds of idle** (the reaper). A package installed outside `/workspace` is gone
by the next session; a package installed inside it is still there.

## Which interpreter you actually get

`python3` is `/usr/local/bin/python3` (CPython 3.13). Every script in the science skills
repo is invoked as `python3 ...`, so that is the one that matters.

Normally importable there, no installation needed:

```
numpy  pandas  scipy  yaml  PIL  matplotlib  pypdf  requests
```

Images built before 2026-09-22 carry only `numpy`, and a container keeps the image it
started with, so check rather than assume — one line tells you which of them you have:

```bash
for m in numpy pandas scipy yaml PIL matplotlib pypdf requests; do python3 -c "import $m" 2>/dev/null && echo "$m"; done
```

`matplotlib` has no display. Select the headless backend **before** importing pyplot:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
```

Two other interpreters exist and neither is yours to use:

* `/opt/bio/.venv` — holds `anarci` and `biopython`. Reachable only through the `ANARCI`
  symlink on PATH, and **not writable**: it is owned by uid 10001, and you run as a
  different, unprivileged uid (`id -u` says which; it is not the same on every deployment).
  Do not try to install into it.
* `/agent-server/.venv` — the agent server's own. Installing into it can move a package
  the server depends on. Never touch it.

## Binaries already on PATH

None of these needs installing, and none of them is a Python import:

```
ANARCI      antibody numbering (IMGT, Kabat, Chothia, Martin, AHo)
hmmscan hmmsearch hmmbuild jackhmmer phmmer    HMMER
mafft  muscle                                  multiple sequence alignment
blastp psiblast makeblastdb                    BLAST+
mmseqs                                         MMseqs2
TMalign                                        structure superposition
mkdssp  dssp                                   secondary structure
```

Check with `command -v <name>` before concluding anything is absent. A failed
`import x` says nothing about whether `X` is on PATH — that is exactly the mistake this
skill exists to stop.

## Installing something that is not here

Make one venv under `HOME` (which is inside `/workspace`, so it survives), inherit
everything the system interpreter already has, and add only what is new.

```bash
# once per workspace
uv venv --python 3.13 --system-site-packages ~/.venvs/lab

# whenever you need something new
uv pip install --python ~/.venvs/lab/bin/python <package>

# run with it, by absolute path — no activation, no ambiguity
~/.venvs/lab/bin/python your_script.py
```

`--system-site-packages` is the part that matters: without it the new venv starts empty
and you reinstall numpy, pandas and matplotlib to get back to where you already were.
With it, `~/.venvs/lab/bin/python` sees everything `python3` sees, plus your additions.

This leaves `python3` untouched, so a skill script that expects the system interpreter
keeps working while your venv carries the extra.

A few skills (`rdkit`, `gget`, `bioservices`) name their own install line in their
SKILL.md. Those are deliberate on-demand choices — follow the line the skill gives, into
the venv above rather than `--system`.

## Where skills are read from

Check this; do not remember it. The answer depends on which agent you are, on the image
your container started from, and on when this conversation was created, and it has changed
more than once. Looking in a directory that is not read finds skills that cannot be loaded,
or none at all, and the wrong conclusion follows.

**Codex** reads `~/.agents/skills`, where the control plane installs them.
`ls ~/.agents/skills/` shows what is there.

**Claude Code** reads *user* skills from `$CLAUDE_CONFIG_DIR/skills` when that variable is
set, and from `~/.claude/skills` only when it is not: setting it *replaces* `~/.claude`, it
does not add to it. It also reads *project* skills from `.claude/skills` in the working
directory, if that exists. From your project directory:

```bash
echo "CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR:-(unset)}"
for d in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills" "$PWD/.claude/skills"; do
  if [ -d "$d" ]; then echo "$d -> $(readlink -f "$d"): $(ls "$d/" | wc -l) skills"
  else echo "$d: absent"; fi
done
```

The loop prints the user skills directory first and the project skills directory
(`<cwd>/.claude/skills`) second. Claude Code reads each one that exists, and `->` shows
where it really lives. The shapes to expect for the user skills directory:

| the first directory line shows | user skills come from |
|---|---|
| `/workspace/.oh/home/.claude/skills -> /workspace/.oh/home/.claude/skills`, with `CLAUDE_CONFIG_DIR` unset | `~/.claude/skills`, read directly |
| `.../acp/claude-code/skills -> /workspace/.oh/home/.claude/skills` | `~/.claude/skills`, through a per-conversation link |
| `.../acp/claude-code/skills -> .../acp/claude-code/skills` | that per-conversation directory only; `~/.claude/skills` is not read |
| `...: absent` | nowhere: only the project skills directory is read |

Not every conversation has a project skills directory; the loop's second line says whether
this one does. A skill present in both is listed to you once, and the user copy is the one
that loads.

The `Skill` tool settles it. A loaded skill's text includes a line
`Base directory for this skill: <path>`, which is where it was found. `Unknown skill: <name>`
means no directory that is read holds a skill by that name, whatever a catalogue says.

Finding skills and running their scripts are separate. Skills run their scripts from
`~/.claude/skills/<name>/scripts/`, and that path can exist on disk whether or not Claude
Code finds skills there — `ls` it before concluding a script is missing.

There is no `invoke_skill` tool in this deployment. Skills are files: a skill in one of
the directories above is loaded by the runtime's own mechanism, and a skill that is not on
disk there cannot be loaded no matter what any catalogue says.

## When you think something is missing

In this order, and stop at the first one that answers:

1. `command -v <name>` — is it a binary already on PATH?
2. `python3 -c "import <module>"` — is it already importable?
3. Read the skill's own SKILL.md — does it name an install line, or a CLI rather than an
   import?
4. Only then install, into `~/.venvs/lab` per above.

Report "not available" only after step 3. Saying a capability is missing when it is one
`command -v` away costs more than the check does.
