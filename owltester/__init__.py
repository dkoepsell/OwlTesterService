"""owltesterservice — the SOoL OWL validation & repair gate.

Replaces the destructive "autofix" with a gate that never silently deletes and
treats a coherent-but-empty artifact as a failure.

Public API:
    check(path, kernel_path=None, all_stages=False, ...) -> Report
    repair(path, kernel_path=None, max_removed=0.02) -> (serialization, result)
    baseline_for(path) -> Counts
"""

from .pipeline import check, baseline_for
from .repair import repair
from .kernel import load_kernel, default_kernel_path
from . import errors

__all__ = [
    "check", "repair", "baseline_for", "load_kernel", "default_kernel_path",
    "errors",
]
