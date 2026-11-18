import subprocess
import os
import ast
import json
import re
import tomllib
from pathlib import PurePosixPath
from urllib.parse import urlparse
from models import RepoReport
from pathlib import Path

MANIFEST_NAMES = ["pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
                  "package.json", "Dockerfile", "docker-compose.yml", "Makefile",
                  "Cargo.toml", "go.mod"]
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

MAX_FILE_BYTES = 200_000   # about 200 KB; larger files are usually generated or data
SPEC = re.compile(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*(.*)")   # name, optional extras, rest



def inspect_repo(given_link):
    if not verify_link(given_link):
        raise ValueError("Invalid link")

    target_dir = f"../repo_sandbox/{get_repo_name(given_link)}"
    
    subprocess.run(
        ["git", "clone", "--depth", "1", given_link, target_dir],
        check=True
    )

    owner = get_repo_name(given_link)
    name = get_repo_name(given_link)
    sha = subprocess.run(["git", "-C", str(target_dir), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip() 
    tree = build_tree(target_dir)
    edges = imports_of(target_dir)
    recent_commits = get_commits(target_dir)
    readme = read_readme(target_dir)
    manifests = {p: (target_dir / p).read_text(errors="ignore")[:4000] for p in MANIFEST_NAMES if p in tree}
    outline = build_outline(target_dir)
    
    report = RepoReport(owner='')

    pass


def verify_link(link):
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "-h", link],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0

def get_repo_name(url):
    clean_url = url.rstrip("/").removesuffix(".git")
    path = urlparse(clean_url).path
    return path.strip("/").split("/")[-1]



def build_tree(root: Path) -> dict[str, int]:
    tree = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]   # edit in place to prune
        for f in filenames:
            p = Path(dirpath) / f
            if p.is_symlink() or p.suffix in SKIP_SUFFIXES:
                continue
            size = p.stat().st_size
            if size <= MAX_FILE_BYTES:
                tree[p.relative_to(root).as_posix()] = size
    return tree


def imports_of(source: str) -> list[tuple[int, str | None, str]]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(0, None, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.level, node.module, ""))     # level > 0 means a relative import
    return found

def get_commits(repo_dir):
    out = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "-n", "30", "--format=%H%x1f%aI%x1f%s"],
        capture_output=True, text=True, check=True).stdout
    commits = []
    for line in out.splitlines():
        sha, date, msg = line.split("\x1f")
        commits.append({"sha": sha, "date": date, "message": msg})

    return commits

def read_readme(root: Path, limit: int = 8000) -> str | None:
    for p in sorted(root.iterdir()):
        if p.is_file() and p.name.lower().startswith("readme"):
            return p.read_text(errors="ignore")[:limit]
    return None

def build_outline(source: str) -> str:
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            doc = (ast.get_docstring(node) or "").split("\n")[0]
            out.append(f"{kind} {node.name}  (line {node.lineno})  {doc}")
    return "\n".join(out)

def get_dependencies(manifests: dict[str, str]) -> dict[str, str | None]:
    """Parse package names and version specs from requirements.txt, pyproject.toml, package.json."""
    deps: dict[str, str | None] = {}

    def add(spec: str) -> None:
        spec = spec.split("#")[0].split(";")[0].strip()          # drop comments and env markers
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
                            deps[name.lower()] = v if isinstance(v, str) else (v.get("version") if isinstance(v, dict) else None)
                case "package.json":
                    data = json.loads(text)
                    for section in ("dependencies", "devDependencies"):
                        deps.update(data.get(section, {}))
        except ValueError:                                        # TOML and JSON decode errors both subclass it
            continue                                              # malformed manifest: skip it
    return deps