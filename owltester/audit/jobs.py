"""Background audit jobs (the ``bundle_layers.py`` pattern).

Each job has a directory under ``<upload folder>/audits/<job_id>/`` holding the
uploaded input and a JSON sidecar (status, current stage, the report when
done). Every gunicorn worker reads the same sidecar; a 'running' marker older
than the stale timeout is reported as 'stale'. A daemon thread does the work.
If the app later gains a queue (RQ, Celery), ``start`` is the only part to change.
"""

import datetime
import json
import logging
import os
import re
import shutil
import threading
import uuid

logger = logging.getLogger(__name__)

JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def stale_seconds():
    return int(os.environ.get("AUDIT_STALE_SECONDS", str(30 * 60)))


def _now():
    return _utcnow().isoformat(timespec="seconds")


def jobs_root(upload_dir):
    return os.path.join(upload_dir, "audits")


def job_dir(upload_dir, job_id):
    if not JOB_ID.match(job_id or ""):
        raise ValueError("not a job id")
    return os.path.join(jobs_root(upload_dir), job_id)


def _sidecar(d):
    return os.path.join(d, "job.json")


def write(d, data):
    tmp = _sidecar(d) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _sidecar(d))


def read(upload_dir, job_id):
    """The sidecar, with a stranded running marker reported as 'stale'; None if absent."""
    try:
        d = job_dir(upload_dir, job_id)
        with open(_sidecar(d), encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return None
    if data.get("status") in ("queued", "running"):
        try:
            started = datetime.datetime.fromisoformat(data["started_at"])
            if (_utcnow() - started).total_seconds() > stale_seconds():
                data["status"] = "stale"
        except (KeyError, TypeError, ValueError):
            data["status"] = "stale"
    return data


def create(upload_dir, owner, artifact_name, profile):
    job_id = uuid.uuid4().hex
    d = job_dir(upload_dir, job_id)
    os.makedirs(os.path.join(d, "input"))
    write(d, {"job_id": job_id, "status": "queued", "stage": None, "progress": "",
              "owner": owner, "artifact": artifact_name, "profile": profile,
              "started_at": _now()})
    return job_id, d


def update(upload_dir, job_id, **changes):
    d = job_dir(upload_dir, job_id)
    data = read(upload_dir, job_id) or {}
    data.update(changes)
    write(d, data)
    return data


def _run(upload_dir, job_id, source, profile, options):
    from .runner import run_audit
    d = job_dir(upload_dir, job_id)
    done_stages = []

    def progress(stage, note=""):
        if stage not in done_stages:
            done_stages.append(stage)
        try:
            update(upload_dir, job_id, status="running", stage=stage, progress=note,
                   stages_started=list(done_stages))
        except OSError as e:
            logger.warning("audit %s: could not record progress: %s", job_id, e)

    try:
        report = run_audit(source, profile=profile, progress=progress, **options)
        update(upload_dir, job_id, status="done", stage=None, progress="",
               finished_at=_now(), report=report.to_dict())
    except Exception as e:  # noqa: BLE001 - the thread must never die silently
        logger.error("audit %s failed: %s", job_id, e)
        update(upload_dir, job_id, status="error", finished_at=_now(),
               error=f"{type(e).__name__}: {str(e)[:500]}")
    finally:
        shutil.rmtree(os.path.join(d, "input"), ignore_errors=True)


def start(upload_dir, job_id, source, profile="general", options=None):
    t = threading.Thread(target=_run, args=(upload_dir, job_id, source, profile, options or {}),
                         name=f"audit-{job_id[:8]}", daemon=True)
    t.start()
    return t
