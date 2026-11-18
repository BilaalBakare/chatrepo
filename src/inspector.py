import subprocess
from urllib.parse import urlparse

def inspect_repo(given_link):
    if not verify_link(given_link):
        raise ValueError("Invalid link")

    target_dir = f"../repo_sandbox/{get_repo_name(given_link)}"
    
    subprocess.run(
        ["git", "clone", "--depth", "1", given_link, target_dir],
        check=True
    )

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