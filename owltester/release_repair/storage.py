"""Plan storage: ``<upload>/audits/<job_id>/repair/<plan_id>/`` (spec section 2).

    plan.json      the plan: remedies, decisions, members, log
    apply.json     the apply job's status and result (written by its thread only)
    work/          the patched copy of the release (removed after the retention period)
    out/           outputs: repaired zip, FIXLOG, patch, the two audit reports

The release itself is kept by the audit job under ``<job>/release/`` when its
owner may repair (see ``audit_service.audit_start``).
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import threading
import time

from ..audit import jobs
from .model import Plan

PLAN_ID = re.compile(r"^[0-9a-f]{32}$")
_locks = {}
_locks_guard = threading.Lock()


def retention_days():
    return int(os.environ.get("REPAIR_RETENTION_DAYS", "90"))


def lock(plan_dir):
    with _locks_guard:
        return _locks.setdefault(plan_dir, threading.Lock())


def plans_root(upload_dir, job_id):
    return os.path.join(jobs.job_dir(upload_dir, job_id), "repair")


def plan_dir(upload_dir, job_id, plan_id):
    if not PLAN_ID.match(plan_id or ""):
        raise ValueError("not a plan id")
    return os.path.join(plans_root(upload_dir, job_id), plan_id)


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=False)
    os.replace(tmp, path)


def save(upload_dir, plan):
    d = plan_dir(upload_dir, plan.job_id, plan.plan_id)
    os.makedirs(d, exist_ok=True)
    _write_json(os.path.join(d, "plan.json"), plan.to_dict())


def load(upload_dir, job_id, plan_id):
    try:
        with open(os.path.join(plan_dir(upload_dir, job_id, plan_id), "plan.json"), encoding="utf-8") as fh:
            return Plan.from_dict(json.load(fh))
    except (ValueError, OSError):
        return None


def list_plans(upload_dir, job_id):
    root = plans_root(upload_dir, job_id)
    out = []
    if os.path.isdir(root):
        for pid in sorted(os.listdir(root)):
            p = load(upload_dir, job_id, pid) if PLAN_ID.match(pid) else None
            if p is not None:
                out.append(p)
    return sorted(out, key=lambda p: p.created_at)


def read_apply(upload_dir, job_id, plan_id):
    try:
        with open(os.path.join(plan_dir(upload_dir, job_id, plan_id), "apply.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return {"status": "none"}
    if data.get("status") == "running":
        try:
            started = datetime.datetime.fromisoformat(data["started_at"])
            age = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - started).total_seconds()
            if age > jobs.stale_seconds():
                data["status"] = "stale"
        except (KeyError, ValueError, TypeError):
            data["status"] = "stale"
    return data


def write_apply(upload_dir, job_id, plan_id, data):
    d = plan_dir(upload_dir, job_id, plan_id)
    os.makedirs(d, exist_ok=True)
    _write_json(os.path.join(d, "apply.json"), data)


# -- the release ---------------------------------------------------------------------------

def release_dir(upload_dir, job_id):
    return os.path.join(jobs.job_dir(upload_dir, job_id), "release")


def release_source(upload_dir, job_id, job=None):
    """The kept release as run_audit/load_artifact take it (zip path or file list), or None."""
    d = release_dir(upload_dir, job_id)
    if not os.path.isdir(d):
        return None
    job = job or jobs.read(upload_dir, job_id) or {}
    names = job.get("release_files") or sorted(os.listdir(d))
    paths = [os.path.join(d, n) for n in names if os.path.exists(os.path.join(d, n))]
    if not paths:
        return None
    if len(paths) == 1 and (paths[0].lower().endswith(".zip") or os.path.isdir(paths[0])):
        return paths[0]
    return paths


def sha256_of(paths):
    h = hashlib.sha256()
    for p in sorted(paths, key=os.path.basename):
        h.update(os.path.basename(p).encode())
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def keep_release(upload_dir, job_id, input_dir, names):
    """Move the audit's input to ``release/`` (called by the audit thread when done)."""
    d = release_dir(upload_dir, job_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.replace(input_dir, d)
    return [os.path.join(d, n) for n in names]


# -- retention -----------------------------------------------------------------------------

def sweep(upload_dir, days=None):
    """Remove work trees older than REPAIR_RETENTION_DAYS. Fix logs and outputs stay."""
    days = retention_days() if days is None else days
    cutoff = time.time() - days * 86400
    root = jobs.jobs_root(upload_dir)
    removed = 0
    if not os.path.isdir(root):
        return 0
    for job_id in os.listdir(root):
        rroot = os.path.join(root, job_id, "repair")
        if not os.path.isdir(rroot):
            continue
        for pid in os.listdir(rroot):
            work = os.path.join(rroot, pid, "work")
            if os.path.isdir(work) and os.path.getmtime(work) < cutoff:
                shutil.rmtree(work, ignore_errors=True)
                removed += 1
    return removed
