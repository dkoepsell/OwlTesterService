"""``audit.yaml`` / ``audit.json``: optional overrides at the archive root.

PyYAML is used when installed; otherwise a small reader handles the documented
shape (scalars, inline ``[a, b]`` lists, block ``- item`` lists and one level of
nested mappings), which is all the file needs.
"""

import json
import os

CONFIG_NAMES = ("audit.yaml", "audit.yml", "audit.json")
KNOWN_KEYS = {"ontology", "vocabularies", "shapes", "data_sets", "ignore", "profile",
              "legacy", "published", "placeholder_hosts", "budget", "max_explanations",
              "expected"}


class ConfigError(ValueError):
    pass


def _scalar(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        return text


def _inline(text):
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(x) for x in inner.split(",") if x.strip()] if inner else []
    return _scalar(text)


def _strip_comment(line):
    out, quote = [], None
    for ch in line:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _lines(text):
    out = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if line.strip():
            out.append((len(line) - len(line.lstrip()), line.strip(), raw))
    return out


def _parse_block(lines, i, indent):
    """Parse the block whose lines sit at ``indent``; return (value, next index)."""
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        items = []
        while i < len(lines) and lines[i][0] == indent:
            ind, body, raw = lines[i]
            if not (body.startswith("- ") or body == "-"):
                raise ConfigError(f"mixed list and mapping at {raw!r}")
            rest = body[1:].strip()
            if not rest:                                    # "-" then a nested block
                if i + 1 < len(lines) and lines[i + 1][0] > indent:
                    val, i = _parse_block(lines, i + 1, lines[i + 1][0])
                else:
                    val, i = None, i + 1
                items.append(val)
                continue
            key, sep, value = rest.partition(":")
            is_map = sep and not rest.startswith(("'", '"', "[")) and (not value or value[0] == " ")
            if not is_map:                                  # "- scalar"
                items.append(_inline(rest))
                i += 1
                continue
            # "- key: value" opens a mapping; its other keys sit at the item's
            # content column (indent + 2), as YAML writes them.
            col = indent + (len(body) - len(rest))
            synthetic = [(col, rest, raw)]
            j = i + 1
            while j < len(lines) and lines[j][0] > indent:
                synthetic.append(lines[j])
                j += 1
            val, k = _parse_block(synthetic, 0, col)
            if k != len(synthetic):
                raise ConfigError(f"bad indentation near {synthetic[k][2]!r}")
            items.append(val)
            i = j
        return items, i
    mapping = {}
    while i < len(lines) and lines[i][0] == indent:
        ind, body, raw = lines[i]
        if body.startswith("- "):
            raise ConfigError(f"mixed list and mapping at {raw!r}")
        if ":" not in body:
            raise ConfigError(f"expected 'key: value': {raw!r}")
        key, _, value = body.partition(":")
        key = key.strip()
        if value.strip():
            mapping[key] = _inline(value)
            i += 1
        elif i + 1 < len(lines) and lines[i + 1][0] > indent:
            mapping[key], i = _parse_block(lines, i + 1, lines[i + 1][0])
        elif i + 1 < len(lines) and lines[i + 1][0] == indent and lines[i + 1][1].startswith("- "):
            mapping[key], i = _parse_block(lines, i + 1, indent)   # list not indented under its key
        else:
            mapping[key] = None
            i += 1
    if i < len(lines) and lines[i][0] > indent:
        raise ConfigError(f"bad indentation near {lines[i][2]!r}")
    return mapping, i


def parse_simple_yaml(text):
    """Parse the block-YAML subset audit configs use into a dict: scalars, inline
    ``[a, b]`` lists, block lists of scalars or of mappings, and nested mappings
    to any depth. Anchors, multi-line strings and flow mappings are not supported."""
    lines = _lines(text)
    if not lines:
        return {}
    value, i = _parse_block(lines, 0, lines[0][0])
    if i != len(lines):
        raise ConfigError(f"bad indentation near {lines[i][2]!r}")
    if not isinstance(value, dict):
        raise ConfigError("the file must be a mapping of keys to values")
    return value


def load_config(path):
    """Read an audit config file. Unknown keys are kept but reported."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ConfigError(f"{os.path.basename(path)} is not valid JSON: {e}")
    else:
        try:
            import yaml  # noqa: PLC0415
            data = yaml.safe_load(text)
        except ImportError:
            data = parse_simple_yaml(text)
        except Exception as e:  # noqa: BLE001 - yaml.YAMLError and friends
            raise ConfigError(f"{os.path.basename(path)} is not valid YAML: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{os.path.basename(path)} must be a mapping of keys to values")
    for key in ("ontology", "vocabularies", "shapes", "ignore", "legacy", "published",
                "placeholder_hosts"):
        if isinstance(data.get(key), str):
            data[key] = [data[key]]
    if data.get("data_sets") is not None and not isinstance(data["data_sets"], dict):
        raise ConfigError("data_sets must map a data-set name to a list of globs")
    for name, globs in (data.get("data_sets") or {}).items():
        if isinstance(globs, str):
            data["data_sets"][name] = [globs]
    data["expected"] = _expected(data.get("expected"))
    data["_unknown_keys"] = sorted(set(data) - KNOWN_KEYS - {"_unknown_keys"})
    return data


def _expected(value):
    """Normalize ``expected``: designed outcomes the release itself declares.

    Each entry names a finding code (``finding`` or ``code``) and optionally a
    ``file`` glob, a ``stage`` and a ``reason``. A matching finding stays in the
    report, marked expected, and does not count toward the verdict.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise ConfigError("expected must be a list of {finding, file, reason} entries")
    out = []
    for e in value:
        if isinstance(e, str):
            e = {"finding": e}
        if not isinstance(e, dict) or not (e.get("finding") or e.get("code")):
            raise ConfigError(f"each expected entry needs a finding code: {e!r}")
        out.append({"code": str(e.get("finding") or e.get("code")),
                    "file": e.get("file"), "stage": e.get("stage"),
                    "reason": str(e.get("reason") or "declared expected by the release")})
    return out


def find_config(root):
    for name in CONFIG_NAMES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return None
