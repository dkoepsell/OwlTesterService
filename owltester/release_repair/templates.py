"""Fixed text templates for ``write_text`` (spec section 3.3 and 7).

User input fills named slots only, and every slot is checked here: paths must be
plain relative paths, reasons and notes are single-line text. No template can
produce a shell command from free text.
"""

import re

from .ops import OpError

PATH = re.compile(r"^[A-Za-z0-9._@+/-]+$")
GLOB = re.compile(r"^[A-Za-z0-9._@+/*?-]+$")
CODE = re.compile(r"^[A-Z][A-Z0-9_]+$")
ROBOT_URL = "https://github.com/ontodev/robot/releases/download/v1.9.6/robot.jar"


def _path(p):
    p = str(p or "")
    if not PATH.match(p) or ".." in p.split("/") or p.startswith("/"):
        raise OpError(f"not a plain relative path: {p!r}")
    return p


def _glob(p):
    p = str(p or "")
    if not GLOB.match(p) or ".." in p.split("/") or p.startswith("/"):
        raise OpError(f"not a plain relative path or glob: {p!r}")
    return p


def _line(text, limit=500):
    text = " ".join(str(text or "").split())
    return text[:limit]


def _yaml_str(text):
    return '"' + _line(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


# -- CI ----------------------------------------------------------------------------------

def ci_commands(kind, slots):
    """The shell lines for one CI check, built from validated paths only."""
    if kind == "shacl":
        shapes = [_path(p) for p in slots.get("shapes") or []]
        onto = [_path(p) for p in slots.get("ontology") or []][:1]
        data = [_glob(p) for p in slots.get("data") or []]
        if not shapes or not data:
            raise OpError("a SHACL step needs shapes and data files")
        ext = f" -e {onto[0]}" if onto else ""
        lines = ["pip install pyshacl"]
        for s in shapes:
            lines.append(f"for f in {' '.join(data)}; do pyshacl -s {s}{ext} -i rdfs \"$f\" || exit 1; done")
        return lines
    if kind == "reasoner":
        onto = [_path(p) for p in slots.get("ontology") or []]
        if not onto:
            raise OpError("a reasoner step needs an ontology file")
        return [f"wget -q {ROBOT_URL}"] + \
            [f"java -jar robot.jar reason --reasoner HermiT --input {o}" for o in onto]
    raise OpError(f"unknown CI check: {kind!r}")


def _github_steps(lines, indent):
    pad = " " * indent
    return "".join(f"{pad}- run: {line}\n" for line in lines)


def _insert_github_steps(text, lines):
    """Append run steps to the first job's ``steps:`` list, at its indentation."""
    rows = text.splitlines(keepends=True)
    start = next((i for i, r in enumerate(rows) if re.match(r"^\s*steps:\s*$", r)), None)
    if start is None:
        raise OpError("the workflow has no steps: list to extend")
    base = len(rows[start]) - len(rows[start].lstrip())
    item_indent, end = None, start + 1
    for i in range(start + 1, len(rows)):
        r = rows[i]
        if not r.strip() or r.lstrip().startswith("#"):
            continue
        ind = len(r) - len(r.lstrip())
        if ind <= base:
            break
        if item_indent is None and r.lstrip().startswith("- "):
            item_indent = ind
        end = i + 1
    item_indent = item_indent if item_indent is not None else base + 2
    if end > 0 and not rows[end - 1].endswith("\n"):
        rows[end - 1] += "\n"
    rows.insert(end, _github_steps(lines, item_indent))
    return "".join(rows)


def _new_github_workflow(lines):
    return ("name: release checks\n"
            "on: [push, pull_request]\n"
            "jobs:\n"
            "  check:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-python@v5\n"
            "        with:\n"
            "          python-version: '3.11'\n"
            "      - uses: actions/setup-java@v4\n"
            "        with:\n"
            "          distribution: temurin\n"
            "          java-version: '21'\n"
            + _github_steps(lines, 6))


def _gitlab_job(text, kind, lines):
    name = "shacl" if kind == "shacl" else "reasoner"
    image = "python:3.11" if kind == "shacl" else "eclipse-temurin:21"
    job = (f"\nrelease-check-{name}:\n  image: {image}\n  script:\n"
           + "".join(f"    - {line}\n" for line in lines))
    return (text or "").rstrip("\n") + "\n" + job


# -- CHANGELOG and audit.yaml --------------------------------------------------------------

def _changelog(current, slots):
    heading = _line(slots.get("heading") or "Unreleased", 80)
    items = [_line(x, 300) for x in slots.get("items") or [] if _line(x)]
    if not items:
        raise OpError("a changelog entry needs at least one line")
    entry = f"## {heading}\n\n" + "".join(f"- {x}\n" for x in items) + "\n"
    if not current:
        return "# Changelog\n\n" + entry
    rows = current.splitlines(keepends=True)
    at = next((i for i, r in enumerate(rows) if r.startswith("## ")), len(rows))
    if at == len(rows):
        return current.rstrip("\n") + "\n\n" + entry
    return "".join(rows[:at]) + entry + "".join(rows[at:])


def _expected_entries(slots):
    out = []
    for e in slots.get("entries") or []:
        code = str(e.get("code", ""))
        if not CODE.match(code):
            raise OpError(f"not a finding code: {code!r}")
        reason = _line(e.get("reason"))
        if not reason:
            raise OpError("declaring an outcome expected needs a written reason")
        row = f"  - finding: {code}\n"
        if e.get("file"):
            glob = str(e["file"])
            if not re.match(r"^[A-Za-z0-9._@+/*?\[\]-]+$", glob):
                raise OpError(f"not a file glob: {glob!r}")
            row += f"    file: {_yaml_str(glob)}\n"
        if e.get("stage"):
            if not re.match(r"^R\d+b?$", str(e["stage"])):
                raise OpError(f"not a stage: {e['stage']!r}")
            row += f"    stage: {e['stage']}\n"
        row += f"    reason: {_yaml_str(reason)}\n"
        out.append(row)
    if not out:
        raise OpError("no expected entries to write")
    return out


def _audit_yaml_expected(current, slots):
    rows = _expected_entries(slots)
    text = current or ""
    lines = text.splitlines(keepends=True)
    at = next((i for i, r in enumerate(lines) if re.match(r"^expected:\s*$", r)), None)
    if at is None:
        if re.search(r"^expected:", text, re.M):
            raise OpError("audit.yaml writes 'expected' inline; add the entries by hand")
        return text.rstrip("\n") + ("\n\n" if text.strip() else "") + \
            "# Outcomes this release declares by design (written by guided release repair)\n" \
            "expected:\n" + "".join(rows)
    end = at + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in (" ", "\t", "-")
                                or lines[end].lstrip().startswith("#")):
        end += 1
    while end > at + 1 and not lines[end - 1].strip():
        end -= 1
    return "".join(lines[:end]) + "".join(rows) + "".join(lines[end:])


def _audit_yaml_drop(current, slots):
    """Remove the ``expected`` entries with the given codes (and files, if named)."""
    if not current:
        raise OpError("there is no audit.yaml to correct")
    drop = [(str(e.get("code")), e.get("file")) for e in slots.get("entries") or []]
    lines = current.splitlines(keepends=True)
    at = next((i for i, r in enumerate(lines) if re.match(r"^expected:\s*$", r)), None)
    if at is None:
        raise OpError("audit.yaml has no block 'expected:' list to correct")
    out, i, removed = lines[:at + 1], at + 1, 0
    while i < len(lines):
        r = lines[i]
        if r.strip() and not r[:1].isspace() and not r.startswith("-"):
            break
        if re.match(r"^\s*-\s", r):
            j = i + 1
            ind = len(r) - len(r.lstrip())
            while j < len(lines) and lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) > ind:
                j += 1
            block = "".join(lines[i:j])
            code = re.search(r"(?:finding|code):\s*['\"]?([A-Z][A-Z0-9_]+)", block)
            glob = re.search(r"file:\s*['\"]?([^'\"\n]+)", block)
            hit = code and any(code.group(1) == c and (f is None or (glob and glob.group(1).strip() == f))
                               for c, f in drop)
            if hit:
                removed += 1
            else:
                out.extend(lines[i:j])
            i = j
            continue
        out.append(r)
        i += 1
    if not removed:
        raise OpError("none of the entries to remove were found in audit.yaml")
    return "".join(out + lines[i:])


def _audit_json_expected(current, slots):
    import json
    _expected_entries(slots)          # validates codes, globs, stages and reasons
    try:
        data = json.loads(current) if current and current.strip() else {}
    except ValueError:
        raise OpError("audit.json is not valid JSON; correct it by hand first")
    if not isinstance(data, dict):
        raise OpError("audit.json must be an object")
    exp = data.get("expected") or []
    if isinstance(exp, dict):
        exp = [exp]
    for e in slots.get("entries") or []:
        row = {"finding": str(e["code"]), "reason": _line(e.get("reason"))}
        if e.get("file"):
            row["file"] = str(e["file"])
        if e.get("stage"):
            row["stage"] = str(e["stage"])
        exp.append(row)
    data["expected"] = exp
    return json.dumps(data, indent=2) + "\n"


def render_text(template, slots, current):
    """New file text for ``template`` given the file's current text (or None)."""
    if template == "ci_github_steps":
        if current is None:
            raise OpError("the workflow to extend is not in the release")
        return _insert_github_steps(current, ci_commands(slots.get("kind"), slots))
    if template == "ci_github_workflow":
        lines = []
        for kind in slots.get("kinds") or [slots.get("kind")]:
            lines += ci_commands(kind, slots)
        if current is not None:
            return _insert_github_steps(current, lines)
        return _new_github_workflow(lines)
    if template == "gitlab_job":
        return _gitlab_job(current, slots.get("kind"), ci_commands(slots.get("kind"), slots))
    if template == "changelog_entry":
        return _changelog(current, slots)
    if template == "audit_yaml_expected":
        return _audit_yaml_expected(current, slots)
    if template == "audit_json_expected":
        return _audit_json_expected(current, slots)
    if template == "audit_yaml_drop_expected":
        return _audit_yaml_drop(current, slots)
    raise OpError(f"unknown template: {template!r}")


TEMPLATES = ("ci_github_steps", "ci_github_workflow", "gitlab_job", "changelog_entry",
             "audit_yaml_expected", "audit_json_expected", "audit_yaml_drop_expected")
