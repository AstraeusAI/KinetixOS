"""Sandboxed execution for agent-run commands.

Two independent layers, because they defend against different things:

  1. **bubblewrap** — filesystem, network and process isolation. The command
     sees a synthetic root containing only /usr, /etc, /proc, /dev and a
     tmpfs /tmp, plus the workspace bound at its real path. The host
     filesystem, other users' data, the session bus, the Wayland socket and
     the agent's own environment (including API keys) are simply not there.
     A PID namespace plus `--die-with-parent` means it cannot reach, signal or
     outlive anything outside its namespace.

  2. **cgroup limits via `systemd-run --user --scope`** — the thing that
     actually stops a command taking the machine down. MemoryMax and
     MemorySwapMax cap a runaway allocator before the kernel OOM killer starts
     roaming the whole system, TasksMax stops fork bombs, CPUQuota stops a
     spin loop from starving the desktop. Verified enforced on this host
     (memory.max is really set inside the scope, and overshoot is killed).

If systemd-run is unavailable the limits fall back to POSIX rlimits
(RLIMIT_AS, RLIMIT_NPROC, RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_CORE=0), applied
in the child via preexec_fn. Weaker than cgroups (RLIMIT_AS counts address
space, which some runtimes reserve generously) but never absent.

Design rule: **a sandbox that cannot be built is not silently skipped.**
`sandbox_available()` is consulted by the policy layer; with no bwrap at all
the caller must obtain explicit approval before running anything.
"""

import os
import resource
import shutil
import signal
import subprocess
from pathlib import Path

# ── limits ────────────────────────────────────────────────────────────────
MEMORY_MAX = "2G"
MEMORY_SWAP_MAX = "256M"
TASKS_MAX = 256
CPU_QUOTA = "200%"
FSIZE_MAX = 512 * 1024 * 1024  # 512 MiB per file
NOFILE_MAX = 1024
CPU_SECONDS = 120  # RLIMIT_CPU fallback
AS_MAX = 6 * 1024 * 1024 * 1024  # 6 GiB address space (fallback only)

# Minimal synthetic root. $HOME (both the bind and the environment
# variable) is set up dynamically in build_argv() below, not here — it has
# to be, so that mocking Path.home() in a test actually changes where the
# sandboxed shell thinks home is, and so that $HOME/~ expansion *inside*
# the sandbox agrees with the real path the sandbox actually bound
# (confirmed live: these used to disagree — HOME was hardcoded to a
# synthetic /tmp/home while the real home was separately bound at its own
# real path, so `~` inside a sandboxed command silently resolved to the
# wrong, mostly-empty directory instead of the one that was actually
# bound and actually had the files). Deliberately still absent: /home
# generally (other users), /root, /var, /run (session bus + Wayland
# socket), /sys, /boot, /mnt, /media.
BWRAP_BASE = [
    "--clearenv",
    "--ro-bind",
    "/usr",
    "/usr",
    "--ro-bind",
    "/etc",
    "/etc",
    "--symlink",
    "usr/lib",
    "/lib",
    "--symlink",
    "usr/lib64",
    "/lib64",
    "--symlink",
    "usr/bin",
    "/bin",
    "--symlink",
    "usr/bin",
    "/sbin",
    "--proc",
    "/proc",
    "--dev",
    "/dev",
    "--tmpfs",
    "/tmp",
    "--unshare-all",  # user, pid, net, ipc, uts, cgroup, ...
    "--die-with-parent",
    "--new-session",
    "--setenv",
    "TMPDIR",
    "/tmp",
    "--setenv",
    "LANG",
    "C.UTF-8",
    "--setenv",
    "TERM",
    "dumb",
]


def have_bwrap() -> bool:
    return shutil.which("bwrap") is not None


def have_systemd_run() -> bool:
    return shutil.which("systemd-run") is not None


def available() -> bool:
    """True when commands can be meaningfully isolated (bwrap present)."""
    return have_bwrap()


def _child_limits(cpu_seconds=CPU_SECONDS):
    """RLIMIT fallback, applied in the child after fork. Kept minimal so we
    never break legitimate builds; cgroups do the heavy lifting when present.

    `cpu_seconds` must track the caller's actual `timeout` (see `run()`) —
    it used to be the fixed module default regardless of what was asked for,
    so a command given a longer timeout (run_command allows up to 300s) could
    still get SIGXCPU'd at the default 120s: a confusing failure clearly
    different from, and arriving well before, "timed out after {timeout}s".
    """

    def lim(what, soft, hard):
        try:
            resource.setrlimit(what, (soft, hard))
        except (ValueError, OSError):
            pass

    lim(resource.RLIMIT_CORE, 0, 0)  # no core dumps
    lim(resource.RLIMIT_FSIZE, FSIZE_MAX, FSIZE_MAX)
    lim(resource.RLIMIT_NOFILE, NOFILE_MAX, NOFILE_MAX)
    lim(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds)
    if not have_systemd_run():
        lim(resource.RLIMIT_AS, AS_MAX, AS_MAX)
        lim(resource.RLIMIT_NPROC, TASKS_MAX, TASKS_MAX)


def build_argv(
    command: str,
    workspace: Path,
    *,
    write_workspace=False,
    extra_writable=(),
    read_only=(),
    net=False,
    sandbox=True,
    cwd=None,
) -> list:
    """argv for running `command` (a shell string) under the sandbox.

    The real $HOME (not just the declared workspace) is bound at its real
    path — read-write unless `write_workspace` is False — so a sandboxed
    command can reach the rest of the user's own files (other projects,
    dotfiles, Downloads, ...), matching workspace.py's resolve() (the file
    tools' own boundary, expanded the same way). System paths, other
    users, and device files stay out of reach regardless — this binds
    Path.home() specifically, never /home itself. The workspace is always
    bound too, even when it sits outside $HOME entirely (this codebase's
    own test suite uses /tmp fixtures) — binding both is harmless when one
    contains the other. `extra_writable` binds additional host directories
    read-write on top of that (used for build caches).
    """
    if not sandbox or not have_bwrap():
        return ["/bin/sh", "-c", command]

    argv = []
    if have_systemd_run():
        argv += [
            "systemd-run",
            "--user",
            "--scope",
            "-q",
            "--collect",
            "-p",
            "MemoryMax=" + MEMORY_MAX,
            "-p",
            "MemorySwapMax=" + MEMORY_SWAP_MAX,
            "-p",
            "TasksMax=%d" % TASKS_MAX,
            "-p",
            "CPUQuota=" + CPU_QUOTA,
            "--",
        ]

    argv += ["bwrap"] + list(BWRAP_BASE)
    for p in read_only:
        argv += ["--ro-bind", str(p), str(p)]
    flag = "--bind" if write_workspace else "--ro-bind"
    home = Path.home()
    if home.is_dir():
        # Bound and pointed to by $HOME at the *same* real path, so `~`
        # inside the sandboxed shell resolves to the directory that is
        # actually bound, not a stand-in the bind doesn't match.
        argv += [
            flag,
            str(home),
            str(home),
            "--setenv",
            "HOME",
            str(home),
            "--setenv",
            "PATH",
            f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
        ]
    else:
        # No real home to bind (unusual — e.g. a container with no home
        # directory at all): fall back to an empty synthetic one so $HOME
        # is still set to *something* sane rather than left unset, same as
        # before this function bound the real one.
        argv += [
            "--dir",
            "/tmp/home",
            "--setenv",
            "HOME",
            "/tmp/home",
            "--setenv",
            "PATH",
            "/tmp/home/.local/bin:/usr/local/bin:/usr/bin:/bin",
        ]
    if workspace:
        argv += [flag, str(workspace), str(workspace)]
    for p in extra_writable:
        if workspace and Path(p) == Path(workspace):
            continue
        argv += ["--bind", str(p), str(p)]
    if net:
        # re-open just the network namespace that --unshare-all closed
        argv += ["--share-net"]
    argv += ["--chdir", str(cwd or workspace or "/"), "--", "/bin/sh", "-c", command]
    return argv


def _proc_children(pid):
    """Direct children of `pid` via /proc/<pid>/task/*/children (Linux-
    specific; needs no special privileges to read for a process we can see
    at all). Used instead of process groups — see _kill_tree()."""
    out = []
    try:
        task_dir = Path(f"/proc/{pid}/task")
        for tid_dir in task_dir.iterdir():
            try:
                out += [int(x) for x in (tid_dir / "children").read_text().split()]
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return out


def _kill_tree(root_pid, sig=signal.SIGKILL):
    """Kill root_pid and every descendant by walking the actual /proc
    parent-child tree, not process groups.

    os.killpg() on the outer process's group was the first fix attempted
    here and it does not work: bwrap's own `--new-session` (already set in
    BWRAP_BASE, and there for a real reason — it's what stops a sandboxed
    process from using the TIOCSTI ioctl to inject input into the
    controlling terminal and escape the sandbox) puts the *inner* sandboxed
    process into a session and process group of its own, separate from the
    outer bwrap monitor process — confirmed live via `ps --forest`: outer
    bwrap had pgid == its own pid, inner bwrap (one level down, the one
    that actually execs the sandboxed command) had a *different* pgid, and
    killing only the outer group left a backgrounded `sleep 30 &` running
    on the host a full second after "timed out" had already been reported,
    a second time even after switching to killpg specifically to fix the
    first instance of this. Walking /proc and killing every PID found by
    its actual PID, layer by layer, doesn't depend on process-group or
    session boundaries at all, so it isn't affected by bwrap creating new
    ones internally for its own good security reasons.
    """
    frontier = [root_pid]
    seen = set()
    while frontier:
        pid = frontier.pop()
        if pid in seen:
            continue
        seen.add(pid)
        frontier.extend(_proc_children(pid))
    for pid in seen:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def run(
    command,
    workspace,
    *,
    write_workspace=False,
    extra_writable=(),
    read_only=(),
    net=False,
    sandbox=True,
    timeout=60,
    cwd=None,
):
    """Run a command sandboxed. Returns a result dict; never raises for the
    command's own failures.

    On timeout, kills the whole process tree the command spawned (see
    _kill_tree()), not just the single PID subprocess.run() would track.
    That distinction is real, not defensive paranoia: verified live that a
    backgrounded child (`sleep 30 &` inside the sandboxed command) was
    still running on the host a full second *after* this function had
    already returned "timed out after 2s" — bwrap forks internally
    (an outer monitor process plus an inner one that becomes PID 1 of the
    new PID namespace and execs the actual command), so killing only the
    single PID Python's default timeout handling tracks leaves that inner
    tree, and anything it backgrounded, running untracked and unbounded by
    anything but its own cgroup/rlimits. Every caller of this — run_command
    with an arbitrary model-written shell string most of all — depends on
    "timed out" actually meaning stopped, not just no-longer-reported-on.
    """
    workspace = Path(workspace).resolve() if workspace else None
    argv = build_argv(
        command,
        workspace,
        write_workspace=write_workspace,
        extra_writable=extra_writable,
        read_only=read_only,
        net=net,
        sandbox=sandbox,
        cwd=cwd,
    )
    # CPU_QUOTA allows up to 2 cores, so a legitimate multi-threaded command
    # can burn up to ~2x its wall-clock timeout in CPU-seconds; give the
    # RLIMIT_CPU fallback the same headroom instead of a fixed ceiling.
    cpu_limit = max(CPU_SECONDS, min(timeout * 2, 3600))

    try:
        p = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=lambda: _child_limits(cpu_limit),
        )
    except FileNotFoundError as e:
        return {"ok": False, "error": "sandbox tool missing: " + str(e)}
    except Exception as e:
        return {"ok": False, "error": "exec failed: " + str(e)}

    try:
        stdout, stderr = p.communicate(timeout=timeout)
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": stdout[-8000:],
            "stderr": stderr[-4000:],
            "sandboxed": bool(sandbox and have_bwrap()),
            "argv_head": argv[0],
        }
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid)
        try:
            p.communicate(timeout=5)  # reap; avoid leaving a zombie behind
        except Exception:
            pass
        return {
            "ok": False,
            "error": f"timed out after {timeout}s",
            "sandboxed": bool(sandbox and have_bwrap()),
        }
    except Exception as e:
        _kill_tree(p.pid)
        return {"ok": False, "error": "exec failed: " + str(e)}


def describe() -> dict:
    return {
        "bwrap": shutil.which("bwrap") or None,
        "systemd_run": shutil.which("systemd-run") or None,
        "isolation": "bwrap" if have_bwrap() else "none",
        "limits": {
            "memory": MEMORY_MAX,
            "tasks": TASKS_MAX,
            "cpu_quota": CPU_QUOTA,
            "fallback": "rlimits" if not have_systemd_run() else "cgroup",
        },
    }
