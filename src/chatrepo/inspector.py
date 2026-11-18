"""Inspect a public GitHub repository and return a RepoReport.

Code only, no LLM: every function here is deterministic and testable.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath

from chatrepo.models import RepoReport

# ---- constants ----------------------------------------------------------------
MANIFEST_NAMES = (
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "package.json", "Dockerfile", "docker-compose.yml", "Makefile",
    "Cargo.toml", "go.mod",
)
SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "vendor", "bower_components",
    ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".tox",
    "dist", "build", "target", ".next", ".nuxt", ".gradle", ".idea", ".vscode",
    "site-packages", "coverage", "htmlcov",
}
# a tuple, because str.endswith() accepts a tuple but not a set
SKIP_SUFFIXES = (
    ".lock", "package-lock.json",
    ".min.js", ".min.css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".whl",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4", ".mov",
    ".pyc", ".so", ".dll", ".exe", ".bin", ".class", ".jar",
)
MAX_FILE_BYTES = 200_000
README_LIMIT = 8_000
MANIFEST_LIMIT = 4_000
COMMIT_LIMIT = 30
OUTLINE_LIMIT = 15
CLONE_TIMEOUT = 120

GITHUB_LINK = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})"
    r"/(?P<name>[A-Za-z0-9_.-]{1,100})(?:/.*)?$"
)
SPEC = re.compile(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*(.*)")  # name, extras, version spec


# ---- fetching -----------------------------------------------------------------
def parse_link(link: str) -> tuple[str, str]:
    """Validate a GitHub URL and return (owner, name). Raises ValueError otherwise."""
    m = GITHUB_LINK.match(link.strip())
    if not m:
        raise ValueError("Expected a link like https://github.com/owner/repo")
    owner, name = m["owner"], m["name"].removesuffix(".git")
    if name in {"", ".", ".."}:
        raise ValueError("Invalid repository name")
    return owner, name


def _git(repo_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout


def fetch(owner: str, name: str, dest: Path) -> str:
    """Shallow-clone a validated repo into dest and return the HEAD commit sha."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "https"}
    try:
        subprocess.run(
            ["git", "clone", "--depth", str(COMMIT_LIMIT), "--single-branch", "--no-tags",
             "--", f"https://github.com/{owner}/{name}.git", str(dest)],
            check=True, capture_output=True, text=True, timeout=CLONE_TIMEOUT, env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Cloning {owner}/{name} timed out") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Could not clone {owner}/{name}: missing, private, or network error") from e
    return _git(dest, "rev-parse", "HEAD").strip()


# ---- analysis -----------------------------------------------------------------
def build_tree(root: Path) -> dict[str, int]:
    """Map relative path -> size in bytes, skipping noise, symlinks and huge files."""
    tree = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]  # prune in place
        for f in filenames:
            p = Path(dirpath) / f
            if p.is_symlink() or p.name.lower().endswith(SKIP_SUFFIXES):
                continue
            size = p.stat().st_size
            if size <= MAX_FILE_BYTES:
                tree[p.relative_to(root).as_posix()] = size
    return tree


def _join(*parts: str) -> str:
    return "/".join(p for p in parts if p)


def build_edges(root: Path, tree: dict[str, int]) -> list[tuple[str, str]]:
    """Internal import graph for Python files: (importing file, imported file)."""
    py_files = {p for p in tree if p.endswith(".py")}
    edges: set[tuple[str, str]] = set()

    def resolve(stem: str, roots: list[str]) -> str | None:
        for r in roots:
            for cand in (_join(r, stem) + ".py", _join(r, stem, "__init__.py")):
                if cand in py_files:
                    return cand
        return None

    for path in sorted(py_files):
        try:
            module = ast.parse((root / path).read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, ValueError):
            continue
        here = list(PurePosixPath(path).parent.parts)
        absolute_roots = ["", "src", "/".join(here)]
        for node in ast.walk(module):
            targets: list[str | None] = []
            if isinstance(node, ast.Import):
                targets = [resolve(a.name.replace(".", "/"), absolute_roots) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import: climb (level - 1) folders from this file
                    keep = len(here) - (node.level - 1)
                    if keep < 0:
                        continue
                    roots, base = [""], here[:keep]
                else:
                    roots, base = absolute_roots, []
                base_stem = "/".join(base + (node.module.split(".") if node.module else []))
                for alias in node.names:  # `from a import b`: b may be a submodule or a name
                    targets.append(resolve(_join(base_stem, alias.name), roots) or resolve(base_stem, roots))
            edges.update((path, t) for t in targets if t and t != path)
    return sorted(edges)


def get_commits(repo_dir: Path) -> list[dict]:
    out = _git(repo_dir, "log", "-n", str(COMMIT_LIMIT), "--format=%H%x1f%aI%x1f%s")
    commits = []
    for line in out.splitlines():
        sha, date, message = line.split("\x1f", 2)
        commits.append({"sha": sha, "date": date, "message": message})
    return commits


def read_readme(root: Path) -> str | None:
    for p in sorted(root.iterdir()):
        if p.is_file() and p.name.lower().startswith("readme"):
            return p.read_text(encoding="utf-8", errors="ignore")[:README_LIMIT]
    return None


def build_outline(source: str) -> str:
    """One line per class/function: kind, name, line number, first docstring line."""
    try:
        module = ast.parse(source)
    except (SyntaxError, ValueError):
        return ""
    lines = []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            doc = (ast.get_docstring(node) or "").split("\n")[0]
            lines.append(f"{kind} {node.name}  (line {node.lineno})  {doc}")
    return "\n".join(lines)


def build_outlines(root: Path, tree: dict[str, int], edges: list[tuple[str, str]]) -> dict[str, str]:
    """Outlines for the most important Python files: most imported first, larger as tiebreak."""
    incoming = Counter(target for _, target in edges)
    py_files = [p for p in tree if p.endswith(".py")]
    ranked = sorted(py_files, key=lambda p: (-incoming[p], -tree[p]))[:OUTLINE_LIMIT]
    outlines = {}
    for path in ranked:
        text = build_outline((root / path).read_text(encoding="utf-8", errors="ignore"))
        if text:
            outlines[path] = text
    return outlines


def get_dependencies(manifests: dict[str, str]) -> dict[str, str | None]:
    """Parse package names and version specs from requirements.txt, pyproject.toml, package.json.

    Pass the FULL manifest text: a truncated file fails to parse and is silently skipped.
    """
    deps: dict[str, str | None] = {}

    def add(spec: str) -> None:
        spec = spec.split("#")[0].split(";")[0].strip()  # drop comments and env markers
        if spec and not spec.startswith(("-", "git+", "http")):
            m = SPEC.match(spec)
            if m:
                deps[m[1].lower()] = m[2].strip() or None

    for path, text in manifests.items():
        try:
            match PurePosixPath(path).name:
                case "requirements.txt":
                    for line in text.splitlines():
                        add(line)
                case "pyproject.toml":
                    data = tomllib.loads(text)
                    for spec in data.get("project", {}).get("dependencies", []):
                        add(spec)
                    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                    for name, v in poetry.items():
                        if name.lower() != "python":
                            spec = v.get("version") if isinstance(v, dict) else v
                            deps[name.lower()] = spec if isinstance(spec, str) else None
                case "package.json":
                    data = json.loads(text)
                    if isinstance(data, dict):
                        for section in ("dependencies", "devDependencies"):
                            deps.update(data.get(section, {}))
        except ValueError:  # TOML and JSON decode errors both subclass ValueError
            continue  # malformed manifest: skip it
    return deps


# ---- public entry point -------------------------------------------------------
def inspect_repo(link: str) -> RepoReport:
    """Fetch a public GitHub repo and return code-derived facts about it."""
    owner, name = parse_link(link)
    workdir = Path(tempfile.mkdtemp(prefix="chatrepo_"))
    try:
        repo_dir = workdir / "repo"
        sha = fetch(owner, name, repo_dir)
        tree = build_tree(repo_dir)
        edges = build_edges(repo_dir, tree)

        full_manifests = {
            p: (repo_dir / p).read_text(encoding="utf-8", errors="ignore")
            for p in MANIFEST_NAMES if p in tree
        }
        return RepoReport(
            owner=owner,
            name=name,
            head_sha=sha,
            tree=tree,
            edges=edges,
            recent_commits=get_commits(repo_dir),
            readme=read_readme(repo_dir),
            manifests={p: t[:MANIFEST_LIMIT] for p, t in full_manifests.items()},
            dependencies=get_dependencies(full_manifests),
            outlines=build_outlines(repo_dir, tree, edges),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)