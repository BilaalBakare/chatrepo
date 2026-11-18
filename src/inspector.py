import subprocess
import os
import ast
from urllib.parse import urlparse
from models import RepoReport
from pathlib import Path

MANIFEST_NAMES = ["pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
                  "package.json", "Dockerfile", "docker-compose.yml", "Makefile",
                  "Cargo.toml", "go.mod"]



def inspect_repo(given_link):
    if not verify_link(given_link):
        raise ValueError("Invalid link")

    target_dir = f"../repo_sandbox/{get_repo_name(given_link)}"
    
    subprocess.run(
        ["git", "clone", "--depth", "1", given_link, target_dir],
        check=True
    )

    owner, name = get_repo_name(given_link)
    sha = subprocess.run(["git", "-C", str(target_dir), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip() 
    manifests = {p: (root / p).read_text(errors="ignore")[:4000] for p in MANIFEST_NAMES if p in tree}
    
    report = RepoReport(owner='')

    pass


def verify_link(link):
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "-h", url],
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