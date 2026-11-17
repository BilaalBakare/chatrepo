import subprocess

def inspect_repo(link):
    if not verify_link:
        

    pass

def verify_link(link):
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "-h", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0