import subprocess
from urllib.parse import urlparse
from datetime import datetime
from pydantic import BaseModel, Field

def inspect_repo(given_link):
    if not verify_link(given_link):
        raise ValueError("Invalid link")

    target_dir = f"../repo_sandbox/{get_repo_name(given_link)}"
    
    subprocess.run(
        ["git", "clone", "--depth", "1", given_link, target_dir],
        check=True
    )

    pass


class RepoReport(BaseModel):
    """Everything the inspector extracts from one repo at one commit."""

    # identity (code-filled)
    owner: str
    name: str
    head_sha: str                                   # inspected commit; cache key with owner/name
    fetched_at: datetime = Field(default_factory=datetime.now)
    schema_version: int = 1                         # bump when this model changes; reject stale cache

    # structure (code-filled)
    tree: dict[str, int]                            # file path -> size in bytes
    edges: list[tuple[str, str]]                    # (importing file, imported file), internal only

    # history (code-filled, optional, capped)
    recent_commits: list[dict] = []                 # keys: "sha", "date", "message" (first line only)

    # text for the LLM (code-filled, truncated)
    readme: str | None = None
    manifests: dict[str, str] = {}                  # path -> truncated content
    dependencies: dict[str, str | None] = {}        # package name -> version spec, if any
    outlines: dict[str, str] = {}                   # path -> signatures and docstrings

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