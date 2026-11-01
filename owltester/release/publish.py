"""Publish a built release to GitHub (SPEC-release.md, section 9.9).

Owner only, with the owner's own token (stored encrypted per user by
``release_repair.github``; never a server token), and an explicit confirmation
each time: ``plan()`` says exactly what will happen, ``publish()`` does it.

One commit holding the repository scaffold goes to ``main`` of a repository the
owner creates here, or to a new branch ``release/v<version>`` of an existing
one; it is tagged ``v<version>``, and a GitHub Release carries the zip with
``VERIFICATION.md`` as its body. Zenodo is linked by the author on Zenodo
(GitHub integration); the builder only explains it. The only hosts contacted are
api.github.com and uploads.github.com.
"""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ..release_repair import github
from ..release_repair.github import GitHubError, REPO

UPLOADS = "https://uploads.github.com"


def _upload(token, repo, release_id, name, data):
    url = f"{UPLOADS}/repos/{repo}/releases/{int(release_id)}/assets?name={urllib.parse.quote(name)}"
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/zip",
                                          "User-Agent": "owltester-release-builder"})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:   # noqa: S310 - fixed https host
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise GitHubError(f"GitHub answered {e.code} on the asset upload") from e
    except urllib.error.URLError as e:
        raise GitHubError(f"GitHub could not be reached: {e.reason}") from e


def scaffold_files(repo_dir):
    """(path, bytes) of every file in the unpacked repository scaffold."""
    from .record import list_files
    out = []
    for rel, ab in list_files(repo_dir):
        with open(ab, "rb") as fh:
            out.append((rel, fh.read(), os.access(ab, os.X_OK)))
    return out


def plan(repo, version, files, zip_name, create=False):
    if not REPO.match(repo or ""):
        raise GitHubError("Repository must be owner/name.")
    branch = "main" if create else f"release/v{version}"
    return {"repo": repo, "create": bool(create), "branch": branch, "tag": f"v{version}",
            "files": [f[0] for f in files], "asset": zip_name,
            "steps": ([f"create the repository {repo} (private) under your account"] if create else []) +
                     [f"commit {len(files)} file(s) to {'main' if create else 'a new branch ' + branch}",
                      f"tag the commit v{version}",
                      f"create the GitHub Release v{version} with {zip_name} attached"]}


def publish(token, repo, version, files, zip_path, body, create=False, private=True, call=None, upload=None):
    call = call or (lambda method, path, payload=None: github._call(token, method, path, payload))
    upload = upload or (lambda rid, name, data: _upload(token, repo, rid, name, data))
    p = plan(repo, version, files, os.path.basename(zip_path), create)
    owner, name = repo.split("/", 1)
    if create:
        me = call("GET", "/user")
        if (me.get("login") or "").lower() != owner.lower():
            raise GitHubError("A new repository is created under your own account; use your login as the owner.")
        call("POST", "/user/repos", {"name": name, "private": bool(private), "auto_init": True,
                                     "description": body.splitlines()[0][:300] if body else ""})
    head = call("GET", f"/repos/{repo}/git/ref/heads/main")["object"]["sha"]
    try:
        call("GET", f"/repos/{repo}/git/ref/tags/{p['tag']}")
        raise GitHubError(f"The tag {p['tag']} already exists in {repo}.")
    except GitHubError as e:
        if "already exists" in str(e):
            raise
    parent = call("GET", f"/repos/{repo}/git/commits/{head}")
    tree = []
    for rel, data, executable in files:
        blob = call("POST", f"/repos/{repo}/git/blobs",
                    {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        tree.append({"path": rel, "mode": "100755" if executable else "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = call("POST", f"/repos/{repo}/git/trees", {"base_tree": parent["tree"]["sha"], "tree": tree})
    commit = call("POST", f"/repos/{repo}/git/commits",
                  {"message": f"Release v{version} (OwlTester release builder)", "tree": new_tree["sha"],
                   "parents": [head]})
    if create:
        call("PATCH", f"/repos/{repo}/git/refs/heads/main", {"sha": commit["sha"]})
    else:
        call("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{p['branch']}", "sha": commit["sha"]})
    call("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/tags/{p['tag']}", "sha": commit["sha"]})
    rel = call("POST", f"/repos/{repo}/releases", {"tag_name": p["tag"], "name": f"v{version}", "body": body,
                                                   "draft": False, "prerelease": version.startswith("0.")})
    with open(zip_path, "rb") as fh:
        asset = upload(rel["id"], os.path.basename(zip_path), fh.read())
    return {"url": rel.get("html_url"), "tag": p["tag"], "branch": p["branch"], "commit": commit["sha"],
            "asset": asset.get("browser_download_url")}
