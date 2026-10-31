#!/usr/bin/env python3
"""Validate Turtle (.ttl) files by parsing them with rdflib.

Examples:
  python scripts/validate_ttl.py            # check all files in data/ (non-recursive)
  python scripts/validate_ttl.py -r         # check files recursively
  python scripts/validate_ttl.py -i file.ttl # check a single file
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from rdflib import Graph


ROOT = os.path.dirname(os.path.dirname(__file__))
DEFAULT_DATA_DIR = os.path.join(ROOT, 'data')


def find_ttl_files(path: str, recursive: bool = False):
    """Yield absolute paths to .ttl files under `path`.
    If `path` is a file, yield it directly (if it ends with .ttl).
    """
    path = os.path.abspath(path)
    if os.path.isfile(path):
        if path.lower().endswith('.ttl'):
            yield path
        return

    if not os.path.isdir(path):
        return

    if recursive:
        for root, _dirs, files in os.walk(path):
            for fn in files:
                if fn.lower().endswith('.ttl'):
                    yield os.path.join(root, fn)
    else:
        for fn in os.listdir(path):
            full = os.path.join(path, fn)
            if os.path.isfile(full) and fn.lower().endswith('.ttl'):
                yield full


def validate_file(path: str, verbose: bool = False) -> tuple[bool, str]:
    """Attempt to parse a Turtle file. Returns (is_valid, message).
    We read bytes and decode to avoid rdflib treating Windows paths as URIs.
    """
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
        try:
            data = raw.decode('utf-8')
        except Exception:
            data = raw.decode('utf-8', errors='replace')

        g = Graph()
        g.parse(data=data, format='turtle')
        if verbose:
            return True, f'OK: {path} ({len(g)} triples)'
        return True, f'OK: {path}'
    except Exception as exc:
        tb = traceback.format_exc()
        return False, f'ERROR parsing {path}: {exc}\n{tb}'


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Validate Turtle (.ttl) files in the data/ folder')
    p.add_argument('-d', '--dir', default=DEFAULT_DATA_DIR, help='Directory (or single file) to check')
    p.add_argument('-r', '--recursive', action='store_true', help='Search directories recursively')
    p.add_argument('-i', '--input', help='Alias for --dir (single file or directory)')
    p.add_argument('-v', '--verbose', action='store_true', help='Show extra info for each file')
    p.add_argument('--fail-fast', action='store_true', help='Exit on first parse error')
    args = p.parse_args(argv)

    target = args.input or args.dir
    files = list(find_ttl_files(target, recursive=args.recursive))

    if not files:
        print(f'No .ttl files found in: {target}')
        return 2

    total = len(files)
    valid_count = 0
    invalid_count = 0

    for path in sorted(files):
        ok, msg = validate_file(path, verbose=args.verbose)
        if ok:
            valid_count += 1
            print(msg)
        else:
            invalid_count += 1
            print(msg)
            if args.fail_fast:
                print('Fail-fast enabled — exiting early')
                return 1

    print('\nSummary:')
    print(f'  Checked: {total}')
    print(f'  Valid:   {valid_count} ')
    print(f'  Invalid: {invalid_count} ')

    return 1 if invalid_count else 0


if __name__ == '__main__':
    sys.exit(main())
