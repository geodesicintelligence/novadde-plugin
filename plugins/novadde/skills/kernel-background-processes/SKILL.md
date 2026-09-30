---
name: kernel-background-processes
description: Use before starting a server, watcher, build, download or test run that may outlast one command. The container is stopped after an idle timeout (10 min by default) and a background job does not count; /tmp is a small RAM disk; port 8000 is this session's own server. Coding work, not OS kernel processes.
category: environment
---

# Long-running and background processes

## What ends a process here

* **The idle stop.** The container is stopped and removed once it has been idle for the
  deployment's timeout, which is 600 seconds by default. The timeout cannot be read from inside.
  * Activity means a turn in progress, the user's browser talking to the session, or the
    conversation's own event log changing.
  * A process of yours working on its own does **not** count.
  * When the container stops, everything in it dies, `nohup` and `tmux` jobs included.
* **The time limit on one tool call.**
* **Memory.** Past the container's limit the kernel kills a process: exit 137, not a slowdown.
  It picks the largest one in the container, which is not always yours.
* **Sharing.** One container serves every conversation this user has open. Their processes,
  servers and `/tmp` share its CPU, memory and pid limits with yours.
* **A restart.** Everything outside `/workspace` is reset from the image, `/tmp` included.
  `/workspace` persists; your working directory and `HOME` are both on it.

## Check first

```bash
pwd                                    # your working directory, on the persistent volume
df -h /tmp /workspace                  # /tmp is tmpfs: RAM, small, and counted as memory
cat /sys/fs/cgroup/cpu.max             # "100000 100000" = 1 CPU (`nproc` shows the host's cores)
cat /sys/fs/cgroup/memory.max          # bytes; past this, exit 137
cat /sys/fs/cgroup/pids.max            # processes and threads together
ss -ltnp 2>/dev/null || netstat -ltnp  # what is already listening, and which process owns it
```

`ss -ltnp` shows `python` on `0.0.0.0:8000`: the agent server hosting this conversation. Never
bind 8000, and never kill that process; doing so ends the session.

## Decide: foreground or background

* **It fits in one tool call.** Run it in the foreground with a bound:
  `mkdir -p .runs && timeout 540 <cmd> > .runs/job.log 2>&1; echo "exit=$?"`. Size the bound to
  your tool's own limit.
* **It must finish, but takes longer.** Start it in the background (below), then keep your turn
  going: poll it until it is done. A turn in progress counts as activity, so the container stays
  up while you poll.
  ```bash
  timeout 100 sh -c 'until [ -e .runs/job.exit ]; do sleep 5; done'; tail -n 5 .runs/job.log
  ```
  Not `sleep 120; tail ...`: Claude Code can refuse a command that starts with a long `sleep`
  (`Blocked: sleep 120 followed by: ...`), and 120 s is its Bash tool's default time limit.
* **It needs hours, or a GPU.** It does not belong in this container. Use the platform (the
  `geodesic` skill) for GPU work, or split the job into resumable chunks.

## Start it in the background

From your working directory, so that the logs land on the persistent volume where the user can
see them:

```bash
mkdir -p .runs
nohup setsid sh -c 'echo $$ > .runs/job.pid; <cmd>; echo $? > .runs/job.exit' \
  > .runs/job.log 2>&1 < /dev/null &
sleep 1; echo "started $(cat .runs/job.pid)"
```

* `setsid` gives the job its own session and process group. It outlives the shell that started
  it, and the whole group can be stopped at once. The pid file is written by the group's leader.
* `nohup`, `< /dev/null` and the log redirect detach it from the terminal.
* `.runs/job.exit` records how the job ended. Without it, a job that died and one that finished
  look the same.
* Keep logs, checkpoints and outputs out of `/tmp`: it is lost on restart, and a big log there
  eats memory. For a tool that fills `/tmp` with scratch files, point it at the volume instead:
  `mkdir -p .runs/tmp && TMPDIR="$PWD/.runs/tmp" <cmd>`.
* `.runs/` sits in your working directory, which is a git work tree. Do not commit it; stage
  paths by name.
* If your Bash tool has its own background option, the same rules apply: log to a file under
  the working directory, and remember that the idle stop still ends the job.

Make a long job resumable: write checkpoints and partial outputs under the working directory,
skip finished work on restart, and write a completion marker last.

## Check on it

```bash
pid=$(cat .runs/job.pid)
if kill -0 "$pid" 2>/dev/null && tr '\0' ' ' < /proc/$pid/cmdline | grep -q '<distinctive part of cmd>'; then
  echo running; ps -o pid,etime,rss,args -p "$pid"
else
  echo "not running; exit file: $(cat .runs/job.exit 2>/dev/null || echo none)"
fi
tail -n 20 .runs/job.log
```

Match the command line, not just the pid. After a restart pids start again from low numbers, so
an old pid file can point at an unrelated process.

If you end your turn while a job runs, tell the user that it will be stopped about 10 minutes
after they stop interacting, and where its log and outputs are.

## Servers

* Pick a free port other than 8000, and bind `127.0.0.1`:
  `python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'`.
* No port in this container is published. Unless the user tells you otherwise, a server here is
  for your own `curl` checks, not a URL to hand them.
* Wait until it answers, not merely until it has started:
  `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>/`.

## Stop what you started, and only that

```bash
pid=$(cat .runs/job.pid)
if tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | grep -q '<distinctive part of cmd>' \
   && [ "$(ps -o pgid= -p "$pid" | tr -d ' ')" = "$pid" ]; then
  kill -- -"$pid"                    # the minus sign: the job's whole process group
else echo "stale pid file: not killing"; fi
sleep 1; kill -0 "$pid" 2>/dev/null && echo "still running" || echo stopped
ps -eo pid,etime,comm                # anything else of yours still running?
```

Check the command line before a group kill, as above. After a restart an old pid file can name
a new process group; the agent server leads one of its own.

A job you stopped leaves no `.runs/job.exit`; one that ended on its own leaves its exit code
there.

* Never `pkill python`, `pkill node` or `killall`. The agent server is a Python process and the
  agent runtime runs on Node, so a pattern kill can end the session.
* Stop servers you no longer need before you end your turn. Leave nothing bound that you
  started, and never touch whatever is on 8000.
* Size parallelism by `cpu.max`, not `nproc`: on a one-CPU quota, use `-j1` or `-n 1`.
