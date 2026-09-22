"""Workspace scoping: the agent operates inside one declared project root.

Every filesystem tool resolves paths through here, so "the agent can only
touch what it was pointed at" is enforced in one place rather than trusted to
each handler. Symlinks are resolved before the containment check, so a link
inside the workspace cannot be used to reach outside it.
"""
import functools
import os
import shutil
from pathlib import Path


def _qt6_qml_tool(name):
    """Resolve `name` to Qt6's own binary, not a same-named Qt5 one earlier
    on PATH. This host has both `qt5-declarative` and `qt6-declarative`
    installed; Qt5's package claims the unversioned `qmllint`/`qmlformat`
    names in /usr/bin, while Qt6's equivalents sit unversioned and un-PATHed
    in /usr/lib/qt6/bin (unlike qmlls, which Qt6 does ship as `qmlls6` on
    PATH). The Qt5 binaries don't understand Qt6/Quickshell-only QML syntax
    and silently exit non-zero with **no diagnostic text at all** — on
    genuinely valid Quickshell QML and on genuinely invalid QML alike, so
    the exit code carries no signal either. Confirmed via `qmllint 6.11.2`
    (the real one) correctly parsing and warning on the same file the PATH
    `qmllint 1.0` (Qt5's) silently exit(-1)'d on. Falls back to a plain PATH
    lookup, so this is a no-op on any system without that dual-install."""
    for candidate in (f"/usr/lib/qt6/bin/{name}", name):
        if shutil.which(candidate):
            return candidate
    return name

# extension → language id (LSP) and tooling
LANGUAGES = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescriptreact", ".jsx": "javascriptreact",
    ".qml": "qml", ".qmltypes": "qml",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".rs": "rust", ".go": "go", ".lua": "lua",
    ".sh": "shellscript", ".bash": "shellscript", ".zsh": "shellscript",
    ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".css": "css", ".html": "html",
}

# marker file → project kind
MARKERS = [
    ("pyproject.toml", "python"), ("setup.py", "python"), ("requirements.txt", "python"),
    ("package.json", "node"), ("Cargo.toml", "rust"), ("go.mod", "go"),
    ("CMakeLists.txt", "cmake"), ("shell.qml", "quickshell"),
    ("Makefile", "make"),
]

# per-language verification commands (only used when the binary exists)
VERIFY = {
    "python":     {"syntax": ["python3", "-m", "py_compile"],
                   # E501 included deliberately: the eval record shows line
                   # length is the single most common surviving style defect
                   # (11 violations shipped under default rules), and the
                   # agent's own "lint passed" claims were true-but-incomplete
                   # because the default ruleset never checked it.
                   "format": ["ruff", "format"], "lint": ["ruff", "check", "--select", "E,F"],
                   "test": ["python3", "-m", "pytest", "-q"]},
    "javascript": {"syntax": ["node", "--check"], "format": ["prettier", "--write"],
                   "lint": ["eslint"], "test": ["npm", "test", "--silent"]},
    "typescript": {"syntax": ["node", "--check"], "format": ["prettier", "--write"],
                   "lint": ["eslint"], "test": ["npm", "test", "--silent"]},
    "qml":        {"syntax": [_qt6_qml_tool("qmllint")], "format": [_qt6_qml_tool("qmlformat"), "-i"],
                   "lint": [_qt6_qml_tool("qmllint")], "test": None},
    "rust":       {"syntax": ["rustc", "--edition", "2021", "--emit=metadata", "--crate-type=lib"],
                   "format": ["rustfmt"], "lint": ["cargo", "clippy"], "test": ["cargo", "test"]},
    "c":          {"syntax": ["gcc", "-fsyntax-only"], "format": ["clang-format", "-i"],
                   "lint": ["clang-tidy"], "test": None},
    "cpp":        {"syntax": ["g++", "-fsyntax-only"], "format": ["clang-format", "-i"],
                   "lint": ["clang-tidy"], "test": None},
    "shellscript": {"syntax": ["bash", "-n"], "format": ["shfmt", "-w"],
                    "lint": ["shellcheck"], "test": None},
    "lua":        {"syntax": ["luac", "-p"], "format": ["stylua"], "lint": None, "test": None},
}

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "target",
               "dist", "build", ".cache", ".mypy_cache", ".pytest_cache"}


def _which(cmd):
    """Locate an executable the way the sandbox will see it.

    shutil.which alone checks the daemon's ambient PATH, but sandboxed
    commands run under BWRAP_BASE's synthetic PATH (which includes
    /tmp/home/.local/bin via the ~/.local read-only bind). A tool installed
    with `pip install --user` is therefore runnable in the sandbox while
    being invisible to a bare which() — the old code reported "no linter
    installed" for exactly this reason. Check the user bin dirs explicitly
    so the probe agrees with the sandbox.
    """
    found = shutil.which(cmd)
    if found:
        return found
    for bind in (Path.home() / ".local" / "bin", Path("/tmp/home/.local/bin")):
        candidate = bind / cmd
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


class Workspace:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace is not a directory: {self.root}")

    # ── path handling ────────────────────────────────────────────────────
    def resolve(self, path, must_exist=False):
        """Resolve `path` (absolute or workspace-relative) and refuse
        anything outside both the declared workspace and the user's home
        directory, including via symlink.

        Confirmed with the user: every file tool should reach anywhere
        under $HOME (other projects, dotfiles, Downloads, ...), not just
        the one declared workspace — while system paths, other users' home
        directories, and device files stay genuinely out of reach (nothing
        here widens the boundary past $HOME itself). The declared
        workspace stays allowed even when it sits outside $HOME entirely
        (this codebase's own test suite uses /tmp fixtures), so this is
        strictly additive to the old workspace-only boundary, never a
        narrowing of it.
        """
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.root / p
        # resolve() follows symlinks; do it before the containment check
        target = p.resolve() if p.exists() else p.parent.resolve() / p.name
        allowed_roots = (self.root, Path.home())
        if not any(target == r or r in target.parents for r in allowed_roots):
            raise PermissionError(f"path escapes both the workspace and the home directory: {path}")
        if must_exist and not target.exists():
            raise FileNotFoundError(str(target))
        return target

    def rel(self, path):
        try:
            return str(Path(path).resolve().relative_to(self.root))
        except Exception:
            return str(path)

    # ── introspection ────────────────────────────────────────────────────
    def language(self, path):
        return LANGUAGES.get(Path(path).suffix.lower(), "text")

    def project(self):
        kinds = [k for marker, k in MARKERS if (self.root / marker).exists()]
        return {"root": str(self.root), "kinds": kinds,
                "kind": kinds[0] if kinds else "generic",
                "git": (self.root / ".git").exists()}

    def tooling(self, path):
        """Which verify commands are actually runnable for this file.

        Availability is checked properly, not just `which`: a Python test
        runner is only offered when the module actually imports, otherwise the
        agent would be told pytest exists and then fail confusingly.
        """
        import shutil
        import subprocess
        lang = self.language(path)
        spec = VERIFY.get(lang, {})
        out = {}
        for kind, cmd in spec.items():
            if not cmd:
                continue
            if kind == "test" and lang == "python":
                out[kind] = self._python_test_cmd()
                continue
            out[kind] = cmd if _which(cmd[0]) else None
        return {"language": lang, "commands": out}

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _python_test_cmd():
        # Cached: this spawns up to two subprocesses (confirmed live —
        # ~80ms per tooling() call on this host), and tooling() is called
        # unconditionally for every VERIFY kind, including from
        # argusd.verify() after *every* write_file/edit_file/multi_edit —
        # even though verify() only ever reads the "lint" key. A task doing
        # a dozen small edits to Python files was paying for this probe a
        # dozen times over for a result that cannot change mid-process
        # (pytest/unittest's importability isn't going to flip between one
        # edit and the next).
        import subprocess
        for probe, cmd in ((("import", "pytest"), ["python3", "-m", "pytest", "-q"]),
                           (("import", "unittest"), ["python3", "-m", "unittest", "discover", "-q"])):
            try:
                r = subprocess.run(["python3", "-c", f"{probe[0]} {probe[1]}"],
                                   capture_output=True, timeout=10)
                if r.returncode == 0:
                    return cmd
            except Exception:
                continue
        return None

    def walk(self, subdir=".", limit=4000):
        """Files under the workspace, skipping vendor/build directories."""
        base = self.resolve(subdir)
        out = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".git")]
            for f in filenames:
                out.append(Path(dirpath) / f)
                if len(out) >= limit:
                    return out
        return out
