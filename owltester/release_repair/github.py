"""Opening a pull request with the owner's own GitHub token (spec section 6).

Only the plan's owner may do this, only after an explicit confirmation, and only
with a token the owner stored for themselves. The token is kept encrypted (Fernet,
key from REPAIR_TOKEN_KEY or derived from SESSION_SECRET) in a file readable by
the service alone; it is never sent back to the browser. No server token exists.
The only host contacted is api.github.com.
"""

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

API = "https://api.github.com"
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH = re.compile(r"^(?!/)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,100}(?<!/)(?<!\.lock)$")
PREFIX = re.compile(r"^([A-Za-z0-9._@+-]+/)*$")


class GitHubError(Exception):
    pass


# -- the stored token --------------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("REPAIR_TOKEN_KEY", "").strip()
    if not key:
        secret = os.environ.get("SESSION_SECRET", "")
        if not secret:
            raise GitHubError("Set SESSION_SECRET (or REPAIR_TOKEN_KEY) before storing tokens.")
        key = base64.urlsafe_b64encode(hashlib.sha256(b"owltester-repair-github:" + secret.encode()).digest())
    return Fernet(key)


def _token_path(upload_dir, user_id):
    if not isinstance(user_id, int):
        raise GitHubError("not a user")
    return os.path.join(upload_dir, "secrets", f"github-{user_id}.token")


def store_token(upload_dir, user_id, token):
    token = str(token or "").strip()
    if not re.match(r"^[A-Za-z0-9_]{20,255}$", token):
        raise GitHubError("That does not look like a GitHub token.")
    path = _token_path(upload_dir, user_id)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    data = _fernet().encrypt(token.encode())
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(path + ".tmp", path)


def load_token(upload_dir, user_id):
    try:
        with open(_token_path(upload_dir, user_id), "rb") as fh:
            return _fernet().decrypt(fh.read()).decode()
    except (OSError, GitHubError):
        return None
    except Exception:  # noqa: BLE001 - a changed key makes the stored token unreadable
        return None


def delete_token(upload_dir, user_id):
    try:
        os.remove(_token_path(upload_dir, user_id))
        return True
    except OSError:
        return False


# -- the API -----------------------------------------------------------------------------

def _call(token, method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28",
                                          "User-Agent": "owltester-release-repair"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:   # noqa: S310 - fixed https host
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode()).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        raise GitHubError(f"GitHub answered {e.code} on {method} {path.split('?')[0]}: {detail}"[:400])
    except urllib.error.URLError as e:
        raise GitHubError(f"GitHub could not be reached: {e.reason}")


def changed_files(original_root, new_root):
    """[(path, text or None for a deletion)] between two copies of the release."""
    from .ops import Tree
    old, new = set(Tree(original_root).files()), set(Tree(new_root).files())
    out = []
    for rel in sorted(old | new):
        a = os.path.join(original_root, *rel.split("/"))
        b = os.path.join(new_root, *rel.split("/"))
        if rel not in new:
            out.append((rel, None))
            continue
        with open(b, "rb") as fh:
            nb = fh.read()
        if rel in old:
            with open(a, "rb") as fh:
                if fh.read() == nb:
                    continue
        try:
            out.append((rel, nb.decode("utf-8")))
        except UnicodeDecodeError:
            raise GitHubError(f"{rel} is binary; repair never changes binary files")
    return out


def open_pull_request(token, repo, base, prefix, changes, title, body, branch, call=None):
    """Create ``branch`` from ``base`` with ``changes`` under ``prefix`` and open a PR."""
    call = call or (lambda method, path, payload=None: _call(token, method, path, payload))
    if not REPO.match(repo or ""):
        raise GitHubError("Repository must be owner/name.")
    if not BRANCH.match(base or "") or not BRANCH.match(branch or ""):
        raise GitHubError("Not a valid branch name.")
    prefix = (prefix or "").strip()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    if not PREFIX.match(prefix) or ".." in prefix.split("/"):
        raise GitHubError("The path inside the repository must be a plain relative folder.")
    if not changes:
        raise GitHubError("The repaired release has no changes to propose.")
    ref = call("GET", f"/repos/{repo}/git/ref/heads/{base}")
    head = ref["object"]["sha"]
    commit = call("GET", f"/repos/{repo}/git/commits/{head}")
    tree = [{"path": prefix + rel, "mode": "100644", "type": "blob",
             **({"content": text} if text is not None else {"sha": None})} for rel, text in changes]
    new_tree = call("POST", f"/repos/{repo}/git/trees", {"base_tree": commit["tree"]["sha"], "tree": tree})
    new_commit = call("POST", f"/repos/{repo}/git/commits",
                      {"message": title, "tree": new_tree["sha"], "parents": [head]})
    call("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]})
    pr = call("POST", f"/repos/{repo}/pulls", {"title": title, "head": branch, "base": base, "body": body})
    return {"url": pr.get("html_url"), "number": pr.get("number"), "branch": branch,
            "files": [rel for rel, _ in changes]}
