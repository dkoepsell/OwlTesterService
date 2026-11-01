"""Tool versions for the verification record, and how to run ROBOT."""

import os
import shlex
import shutil
import subprocess


class ToolError(Exception):
    """The environment cannot run the step (missing Java or ROBOT): exit code 2."""


def robot_command():
    """ROBOT as an argv prefix: ``$ROBOT`` (a command), ``$ROBOT_JAR``, or ``robot`` on PATH."""
    if os.environ.get("ROBOT"):
        return shlex.split(os.environ["ROBOT"])
    jar = os.environ.get("ROBOT_JAR")
    if jar and os.path.isfile(jar):
        return ["java", "-jar", jar]
    exe = shutil.which("robot")
    return [exe] if exe else None


def require_java():
    if shutil.which("java") is None:
        raise ToolError("Java is not installed; the audit's reasoning stages need Java 11 or later.")


def require_robot():
    cmd = robot_command()
    if cmd is None:
        raise ToolError("ROBOT is not installed. Put robot on PATH or set ROBOT_JAR to robot.jar.")
    return cmd


def robot_version():
    cmd = robot_command()
    if cmd is None:
        return None
    try:
        out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip()
    return text.rsplit(" ", 1)[-1] if text else None


def _pkg(name):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:  # noqa: BLE001 - not installed
        return None


def versions(owltester_version):
    """The ``tool`` block of the record."""
    owlready = _pkg("owlready2")
    return {"owltester": owltester_version,
            "image": os.environ.get("OWLTESTER_IMAGE") or None,
            "robot": robot_version(),
            "hermit": f"bundled with owlready2 {owlready}" if owlready else None,
            "pyshacl": _pkg("pyshacl"), "rdflib": _pkg("rdflib")}
