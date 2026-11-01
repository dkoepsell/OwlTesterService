"""The release builder's answers (SPEC-release.md, sections 9 and 13).

The same answers drive the web pages and ``owltester build --answers build.yaml``,
so a build is repeatable without the pages. Every value that reaches a generated
file is validated here; templates only ever see validated fields.
"""

import datetime
import re

NAME = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:rc|alpha|beta)\.?\d+)?$")
IRI = re.compile(r"^https?://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9._~%!$&'()*+,;=:@/#-]*)?$")
ORCID = re.compile(r"^(?:https://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")
REPO_URL = re.compile(r"^https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})$")
PROJECT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERSON = re.compile(r"^[^\x00-\x1f<>\"\\`$|]{1,120}$")

LICENSES = {
    "CC-BY-4.0": ("Creative Commons Attribution 4.0 International",
                  "https://creativecommons.org/licenses/by/4.0/"),
    "CC0-1.0": ("Creative Commons Zero 1.0 Universal (public domain dedication)",
                "http://creativecommons.org/publicdomain/zero/1.0/"),
    "CC-BY-SA-4.0": ("Creative Commons Attribution-ShareAlike 4.0 International",
                     "https://creativecommons.org/licenses/by-sa/4.0/"),
    "MIT": ("MIT License", "https://opensource.org/licenses/MIT"),
    "Apache-2.0": ("Apache License 2.0", "https://www.apache.org/licenses/LICENSE-2.0"),
}
BFO_MODES = ("none", "full", "module")
FORMATS = ("ofn", "jsonld")
PROFILES = ("general", "bfo", "sool")
FAIL_ON = ("critical", "major", "minor")
SHAPES_MODES = ("draft", "include", "off")


class AnswersError(ValueError):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def _people(raw, field, problems):
    out = []
    for i, p in enumerate(raw or []):
        if isinstance(p, str):
            p = {"name": p}
        if not isinstance(p, dict):
            problems.append(f"{field}[{i}]: give a name, and optionally an orcid")
            continue
        name = str(p.get("name", "")).strip()
        if not PERSON.match(name):
            problems.append(f"{field}[{i}]: a name of 1 to 120 plain characters is required")
            continue
        orcid = str(p.get("orcid") or "").strip()
        if orcid:
            m = ORCID.match(orcid)
            if not m:
                problems.append(f"{field}[{i}]: {orcid} is not an ORCID iD (0000-0000-0000-0000)")
                continue
            orcid = m.group(1)
        out.append({"name": name, "orcid": orcid or None})
    return out


def _text(value, field, problems, limit, required=True):
    v = " ".join(str(value or "").split()) if field == "title" else str(value or "").strip()
    if required and not v:
        problems.append(f"{field} is required")
    if len(v) > limit:
        problems.append(f"{field} is longer than {limit} characters")
    if "\x00" in v:
        problems.append(f"{field} contains a NUL character")
    return v


def validate(raw):
    """A clean answers dict, or AnswersError listing every problem."""
    raw = dict(raw or {})
    p = []
    name = str(raw.get("name", "")).strip()
    if not NAME.match(name):
        p.append("name must be 3 to 64 lowercase letters, digits and hyphens, starting with a letter")
    a = {"name": name,
         "title": _text(raw.get("title"), "title", p, 300),
         "description": _text(raw.get("description"), "description", p, 5000)}
    iri = str(raw.get("ontology_iri", "")).strip()
    if not IRI.match(iri):
        p.append("ontology_iri must be an http(s) IRI")
    a["ontology_iri"] = iri
    base = str(raw.get("base") or "").strip().rstrip("/")
    if not base and IRI.match(iri):
        base = re.sub(r"(\.owl|\.ttl|\.rdf)?[#/]?$", "", iri)
    if base and not IRI.match(base):
        p.append("base must be an http(s) IRI")
    a["base"] = base
    version = str(raw.get("version", "")).strip().lstrip("v")
    if not SEMVER.match(version):
        p.append("version must be a semantic version such as 1.0.0")
    a["version"] = version
    lic = str(raw.get("license") or "CC-BY-4.0")
    if lic not in LICENSES:
        p.append(f"license must be one of {', '.join(LICENSES)}")
    a["license"] = lic
    a["creators"] = _people(raw.get("creators"), "creators", p)
    if not a["creators"]:
        p.append("at least one creator is required")
    a["contributors"] = _people(raw.get("contributors"), "contributors", p)
    prior = str(raw.get("prior_version") or "").strip()
    if prior and not IRI.match(prior):
        p.append("prior_version must be an http(s) IRI")
    a["prior_version"] = prior or None
    bfo = str(raw.get("bfo") or "none")
    if bfo not in BFO_MODES:
        p.append(f"bfo must be one of {', '.join(BFO_MODES)}")
    a["bfo"] = bfo
    formats = sorted({str(f) for f in raw.get("formats") or []})
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        p.append(f"formats may only list {', '.join(FORMATS)} (Turtle is always written)")
    a["formats"] = formats
    a["profile"] = str(raw.get("profile") or ("bfo" if bfo != "none" else "general"))
    if a["profile"] not in PROFILES:
        p.append(f"profile must be one of {', '.join(PROFILES)}")
    a["fail_on"] = str(raw.get("fail_on") or "major")
    if a["fail_on"] not in FAIL_ON:
        p.append(f"fail_on must be one of {', '.join(FAIL_ON)}")
    repo = str(raw.get("repository") or "").strip().rstrip("/")
    if repo and not REPO_URL.match(repo):
        p.append("repository must be https://github.com/<owner>/<name>")
    a["repository"] = repo or None
    project = str(raw.get("w3id_project") or "").strip()
    if project and not PROJECT.match(project):
        p.append("w3id_project must be a short lowercase name")
    if not project and base.startswith("https://w3id.org/"):
        project = base[len("https://w3id.org/"):].split("/")[0]
    a["w3id_project"] = project or None
    date = str(raw.get("release_date") or datetime.date.today().isoformat())
    if not DATE.match(date):
        p.append("release_date must be YYYY-MM-DD")
    a["release_date"] = date
    shapes = str(raw.get("shapes_scaffold") or "draft")
    if shapes not in SHAPES_MODES:
        p.append(f"shapes_scaffold must be one of {', '.join(SHAPES_MODES)}")
    a["shapes_scaffold"] = shapes
    a["keywords"] = [k for k in (_text(k, "keyword", p, 60, False) for k in raw.get("keywords") or []) if k]
    expected = []
    for i, e in enumerate(raw.get("expected") or []):
        if not isinstance(e, dict) or not re.match(r"^[A-Z][A-Z0-9_]{2,40}$", str(e.get("finding", ""))) \
                or not str(e.get("reason", "")).strip():
            p.append(f"expected[{i}]: needs finding (a code) and reason")
            continue
        item = {"finding": e["finding"], "reason": " ".join(str(e["reason"]).split())[:500]}
        if e.get("file"):
            item["file"] = str(e["file"])
        expected.append(item)
    a["expected"] = expected
    if p:
        raise AnswersError(p)
    return a


def load(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise AnswersError([f"{path}: the answers must be a mapping"])
    return validate(data)


def version_iri(a, filename=None):
    return f"{a['base']}/releases/{a['version']}/{filename or a['name'] + '.owl'}"


def base_iri(a):
    return f"{a['base']}/{a['name']}-base.owl"
