"""Packaging (SPEC-release.md, sections 9.7, 9.8 and 11).

``audit.yaml``, ``MANIFEST.json``, the verification record and a deterministic
zip; the repository scaffold (``<name>-repo.zip``), the on-ramp to Part A; and
the w3id.org ``.htaccess`` with the text of its pull request.
"""

import hashlib
import json
import os
import shutil
import stat
import zipfile

from . import docs, record
from .answers import LICENSES, REPO_URL

ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MANIFEST = "MANIFEST.json"


def write(path, text, executable=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# A release zip carries no CI of its own; the builder audited it (SHACL and reasoning
# included) and the repository scaffold runs the OwlTester Action in CI.
BUILDER_EXPECTED = [
    {"finding": "W_CI_NO_REASONER",
     "reason": "A release archive has no CI of its own. The OwlTester release builder reasoned over "
               "this release (HermiT) and its repository runs the OwlTester Action on every push."},
    {"finding": "W_CI_NO_SHACL",
     "reason": "A release archive has no CI of its own. The OwlTester release builder validated this "
               "release against its shapes and its repository runs the OwlTester Action on every push."},
]


def audit_yaml(a, layout, release=True):
    """The audit configuration: roles, and the outcomes declared expected. ``release``:
    the archive (declares the builder's CI outcomes); False for the repository scaffold."""
    import yaml
    cfg = {"profile": a["profile"], "ontology": [layout["full"]], "modules": [layout["base"]]}
    if layout.get("shapes"):
        cfg["shapes"] = layout["shapes"]
    if layout.get("vocabularies"):
        cfg["vocabularies"] = layout["vocabularies"]
    if layout.get("examples"):
        cfg["data_sets"] = {"examples": layout["examples"]}
    ignore = sorted(layout.get("ignore") or [])
    if ignore:
        cfg["ignore"] = ignore
    expected = list(a["expected"])
    if release:
        have = {e["finding"] for e in expected}
        expected += [e for e in BUILDER_EXPECTED if e["finding"] not in have]
    if expected:
        cfg["expected"] = expected
    head = (f"# OwlTester audit configuration for {a['name']} {a['version']} (SPEC-audit.md, section 1).\n"
            "# Written by the release builder; findings listed under expected are designed\n"
            "# outcomes and do not count against the release.\n")
    return head + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=100)


def manifest(root):
    files = [{"path": rel, "sha256": record.sha256_file(ab), "bytes": os.path.getsize(ab)}
             for rel, ab in record.list_files(root)
             if rel not in record.NOT_AUDITED and rel != MANIFEST]
    return json.dumps({"manifest_version": "1", "files": files}, indent=2, sort_keys=True) + "\n"


def deterministic_zip(root, zpath, top=None):
    """Sorted entries, fixed timestamps and modes: the same tree gives the same bytes."""
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, ab in record.list_files(root):
            info = zipfile.ZipInfo((top + "/" if top else "") + rel, date_time=ZIP_DATE)
            mode = 0o755 if os.access(ab, os.X_OK) else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            with open(ab, "rb") as fh:
                zf.writestr(info, fh.read(), compresslevel=9)
    return zpath


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def repo_scaffold(dest, a, release_dir, edit_dir, layout, qc, cq):
    """The release laid out as a git repository the author can push (section 9.8)."""
    name = a["name"]
    src = os.path.join(dest, "src")
    shutil.copytree(edit_dir, os.path.join(src, "ontology"),
                    ignore=shutil.ignore_patterns("tmp", "*.tmp"))
    write(os.path.join(src, "ontology", "Makefile"),
          docs.render("Makefile", title=a["title"], name=name, base=a["base"],
                      ontology_iri=a["ontology_iri"], version=a["version"]))
    for key, sub in (("shapes", "shapes"), ("vocabularies", "vocab"), ("examples", "examples")):
        for rel in layout.get(key) or []:
            os.makedirs(os.path.join(src, sub), exist_ok=True)
            shutil.copyfile(os.path.join(release_dir, rel), os.path.join(src, sub, os.path.basename(rel)))
    for fname, text in sorted(qc.items()):
        write(os.path.join(src, "sparql", fname), text)
    for fname, text in sorted(cq.items()):
        write(os.path.join(src, "sparql", "cq", fname), text)
    # The release files at the root, as `make release` leaves them.
    for rel in [layout["full"], layout["base"], f"{name}.ttl", "README.md", "CHANGELOG.md",
                "LICENSE", "NOTICE", "CITATION.cff", "audit.yaml"] + sorted(layout.get("formats") or []):
        if os.path.isfile(os.path.join(release_dir, rel)):
            shutil.copyfile(os.path.join(release_dir, rel), os.path.join(dest, rel))
    if os.path.isdir(os.path.join(release_dir, "docs")):
        shutil.copytree(os.path.join(release_dir, "docs"), os.path.join(dest, "docs"))
    # In the repository the shapes and examples live under src/; point the audit there.
    repo_layout = dict(layout,
                       shapes=[f"src/shapes/{os.path.basename(r)}" for r in layout.get("shapes") or []],
                       vocabularies=[f"src/vocab/{os.path.basename(r)}" for r in layout.get("vocabularies") or []],
                       examples=[f"src/examples/{os.path.basename(r)}" for r in layout.get("examples") or []],
                       ignore=["src/ontology/**", "src/sparql/**", "scripts/**", ".github/**"])
    write(os.path.join(dest, "audit.yaml"), audit_yaml(a, repo_layout, release=False))
    write(os.path.join(dest, ".github", "workflows", "audit.yml"),
          docs.render("workflow-audit.yml", profile=a["profile"]))
    write(os.path.join(dest, ".github", "workflows", "release.yml"),
          docs.render("workflow-release.yml", profile=a["profile"], fail_on=a["fail_on"]))
    files = " ".join([layout["full"], layout["base"], f"{name}.ttl"] + sorted(layout.get("formats") or [])
                     + ["audit.yaml", "README.md", "CHANGELOG.md", "LICENSE", "NOTICE", "CITATION.cff"])
    write(os.path.join(dest, "scripts", "stage-release.sh"),
          docs.render("stage-release.sh", release_files=files, release_dirs="src/shapes src/vocab src/examples docs"),
          executable=True)
    write(os.path.join(dest, ".gitignore"), docs.render("gitignore"))
    return dest


def w3id(a):
    """{".htaccess": text, "W3ID-PR.md": text}, or {} when the base is not on w3id.org."""
    project = a.get("w3id_project")
    m = REPO_URL.match(a.get("repository") or "")
    if not project or not m or not a["base"].startswith("https://w3id.org/"):
        return {}
    owner, repo = m.group(1), m.group(2)
    path = a["base"][len(f"https://w3id.org/{project}"):].strip("/")
    prefix = path + "/" if path else ""
    onto_rel = a["ontology_iri"][len(f"https://w3id.org/{project}/"):] if a["ontology_iri"].startswith(
        f"https://w3id.org/{project}/") else prefix + a["name"] + ".owl"
    plain = onto_rel.replace(".", "\\.")
    maintainers = ", ".join(p["name"] for p in a["creators"])
    return {".htaccess": docs.render("htaccess", project=project, path_prefix=prefix, owner=owner, repo=repo,
                                     plain=plain, name=a["name"], root=(path + "/?") if path else ""),
            "W3ID-PR.md": docs.render("w3id-pr.md", project=project, title=a["title"], owner=owner,
                                      repo=repo, maintainers=maintainers)}


def license_url(a):
    return LICENSES[a["license"]][1]
