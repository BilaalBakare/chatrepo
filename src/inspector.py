import subprocess
from urllib.parse import urlparse

def inspect_repo(link):
    if not verify_link:
        raise ValueError("Invalid link")

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
