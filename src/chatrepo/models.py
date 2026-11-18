from datetime import datetime, timezone
from pydantic import BaseModel, Field

class RepoReport(BaseModel):
    """Everything the inspector extracts from one repo at one commit."""

    # identity (code-filled)
    owner: str
    name: str
    head_sha: str                                   # inspected commit; cache key with owner/name
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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