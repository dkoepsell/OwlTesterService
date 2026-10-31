"""``audit.yaml`` / ``audit.json``: optional overrides at the archive root.

PyYAML is used when installed; otherwise a small reader handles the documented
shape (scalars, inline ``[a, b]`` lists, block ``- item`` lists and one level of
nested mappings), which is all the file needs.
"""

import json
import os

CONFIG_NAMES = ("audit.yaml", "audit.yml", "audit.json")
KNOWN_KEYS = {"ontology", "vocabularies", "shapes", "data_sets", "ignore", "profile",
              "legacy", "published", "placeholder_hosts", "budget", "max_explanations"}


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


def parse_simple_yaml(text):
    """Parse the documented subset of YAML into a dict."""
    root = {}
    stack = [(-1, root, None)]   # (indent, owning dict, key whose value is open)
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        _, owner, open_key = stack[-1]
        if body.startswith("- "):
            if open_key is None:
                raise ConfigError(f"list item without a key: {raw!r}")
            if owner[open_key] is None:
                owner[open_key] = []
            if not isinstance(owner[open_key], list):
                raise ConfigError(f"mixed list and mapping under {open_key!r}")
            owner[open_key].append(_scalar(body[2:]))
            continue
        if ":" not in body:
            raise ConfigError(f"expected 'key: value': {raw!r}")
        key, _, value = body.partition(":")
        container = owner
        if open_key is not None:
            if owner[open_key] is None:
                owner[open_key] = {}
            if not isinstance(owner[open_key], dict):
                raise ConfigError(f"mixed list and mapping under {open_key!r}")
            container = owner[open_key]
        if value.strip():
            container[key.strip()] = _inline(value)
        else:
            container[key.strip()] = None
            stack.append((indent, container, key.strip()))
    return root


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
    data["_unknown_keys"] = sorted(set(data) - KNOWN_KEYS - {"_unknown_keys"})
    return data


def find_config(root):
    for name in CONFIG_NAMES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return None
