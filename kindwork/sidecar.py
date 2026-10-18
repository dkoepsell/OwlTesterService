"""Call the kindwork-core sidecar (kindwork_core/bin/kindwork-core.mjs).

One JSON request on stdin, one JSON reply on stdout, a fresh Node process per
call (module spec section 3, ADJUDICATE A2: spawn first, pool later if needed).
Exit 0 is success, 2 an input error with diagnostics, 1 an internal error.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

CORE_DIR = Path(os.environ.get("KINDWORK_CORE_DIR")
                or Path(__file__).resolve().parent.parent / "kindwork_core")
BIN = CORE_DIR / "bin" / "kindwork-core.mjs"
PAGE = CORE_DIR / "core" / "kindwork.html"
CALL_TIMEOUT = 30


class SidecarError(RuntimeError):
    """The sidecar could not run or crashed. Not an input problem."""


class SidecarInputError(ValueError):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or []


@functools.lru_cache(maxsize=1)
def core_hash() -> str:
    """First 12 hex of the vendored page's sha256, sent as X-Kindwork-Core."""
    try:
        return hashlib.sha256(PAGE.read_bytes()).hexdigest()[:12]
    except OSError:
        return "missing"


def node_bin():
    return os.environ.get("KINDWORK_NODE") or shutil.which("node")


def call(op: str, **payload) -> dict:
    node = node_bin()
    if not node:
        raise SidecarError("Node.js is not installed on this server.")
    try:
        proc = subprocess.run([node, str(BIN)], input=json.dumps({"op": op, **payload}),
                              capture_output=True, text=True, timeout=CALL_TIMEOUT,
                              cwd=str(CORE_DIR), check=False)
    except subprocess.TimeoutExpired as e:
        raise SidecarError(f"kindwork-core did not answer within {CALL_TIMEOUT}s") from e
    except OSError as e:
        raise SidecarError(f"kindwork-core could not start: {e}") from e
    try:
        reply = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise SidecarError(f"kindwork-core replied with non-JSON (exit {proc.returncode}): "
                           f"{proc.stderr[-300:]}") from e
    if proc.returncode == 2:
        raise SidecarInputError(reply.get("error") or "The input was refused.",
                                reply.get("errors") or [])
    if proc.returncode != 0:
        raise SidecarError(reply.get("detail") or reply.get("error") or "kindwork-core failed")
    return reply
