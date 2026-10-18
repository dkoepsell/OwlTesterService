"""Layer-by-layer reasoning for multi-file ontology bundles.

For each module of a bundle, bottom-up, reason over that module plus its import
closure (with the vendored BFO attached, as for any analysis) and record whether
it is consistent and which classes are unsatisfiable. Unsatisfiable classes that
did not already fail in the module's imports are attributed to that layer, so the
report answers "which layer first breaks the stack?".

The result lives in a JSON sidecar (``<stored file>.layers.json``) so every
gunicorn worker sees the same state; a 'running' marker guards against
stacking reasoner runs.
"""

import datetime
import json
import logging
import os
import tempfile

from ontology_bundle import load_manifest, module_closure_graph, modules_dir_for

logger = logging.getLogger(__name__)

STALE_SECONDS = 15 * 60
LAYER_BUDGET_SECONDS = 60


def layers_path(file_path):
    return file_path + '.layers.json'


def read_layers(file_path):
    """Stored layer report, with a stranded 'running' marker reported as 'stale'."""
    path = layers_path(file_path)
    if not os.path.exists(path):
        return {'status': 'none'}
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {'status': 'none'}
    if data.get('status') == 'running':
        try:
            started = datetime.datetime.fromisoformat(data['started_at'])
            if (datetime.datetime.utcnow() - started).total_seconds() > STALE_SECONDS:
                data['status'] = 'stale'
        except (KeyError, TypeError, ValueError):
            data['status'] = 'stale'
    return data


def _write(file_path, data):
    tmp = layers_path(file_path) + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh)
    os.replace(tmp, layers_path(file_path))


def mark_running(file_path):
    """Store and return a 'running' marker, or None if a fresh run is in flight."""
    if read_layers(file_path).get('status') == 'running':
        return None
    marker = {'status': 'running', 'started_at': datetime.datetime.utcnow().isoformat()}
    _write(file_path, marker)
    return marker


def _reason_layer(tester, graph, budget):
    """(status, unsatisfiable [{name,label,iri}], note) for one merged closure."""
    fd, tmp = tempfile.mkstemp(suffix='.owl')
    os.close(fd)
    try:
        graph.serialize(destination=tmp, format='xml')
        info = tester.load_ontology_from_file(tmp)
        if not info.get('loaded'):
            return 'unknown', [], info.get('error', 'could not load')
        _, extras, _, _, skipped, unsat = tester._try_reasoner_with_budget(
            info['ontology'], budget_seconds=budget)
        if skipped == 'inconsistent':
            return 'inconsistent', [], extras.get('inconsistency_reason')
        if skipped:
            return 'unknown', [], extras.get('reasoner_skipped', skipped)
        return ('incoherent' if unsat else 'ok'), unsat, None
    finally:
        os.remove(tmp)


def check_layers(file_path, tester=None, budget=LAYER_BUDGET_SECONDS):
    """Reason over each module's import closure, bottom-up. Returns the report."""
    if tester is None:
        from owl_tester import OwlTester
        tester = OwlTester()
    manifest = load_manifest(file_path)
    if not manifest:
        return {'status': 'done', 'error': 'not a multi-file bundle', 'layers': []}
    modules_dir = modules_dir_for(file_path)
    by_name = {m['name']: m for m in manifest['modules']}
    owner = manifest.get('entity_module', {})

    results, unsat_by_module, first_break = [], {}, None
    for name in manifest['order']:
        graph, closure = module_closure_graph(modules_dir, manifest, name)
        status, unsat, note = _reason_layer(tester, graph, budget)
        inherited = set()
        for dep in closure:
            if dep != name:
                inherited |= unsat_by_module.get(dep, set())
        iris = {c.get('iri') for c in unsat}
        unsat_by_module[name] = iris
        introduced = [dict(c, module=owner.get(c.get('iri'))) for c in unsat
                      if c.get('iri') not in inherited]
        deps_ok = all(r['status'] in ('ok', 'incoherent') for r in results
                      if r['module'] in closure and r['module'] != name)
        breaks = (status == 'inconsistent' and deps_ok) or bool(introduced)
        if breaks and first_break is None:
            first_break = name
        results.append({
            'module': name,
            'title': by_name[name].get('title'),
            'layer': by_name[name].get('layer'),
            'closure': closure,
            'status': status,
            'unsatisfiable': unsat,
            'introduced_unsatisfiable': introduced,
            'breaks_here': breaks,
            'note': note,
        })
    return {'status': 'done', 'layers': results, 'first_break': first_break,
            'finished_at': datetime.datetime.utcnow().isoformat()}


def run_and_store(file_path):
    """Thread body: run the layer check and persist the result (never raises)."""
    try:
        result = check_layers(file_path)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Layer check failed for {file_path}: {e}")
        result = {'status': 'done', 'error': f"{type(e).__name__}: {e}", 'layers': []}
    try:
        _write(file_path, result)
    except OSError as e:
        logger.error(f"Could not store layer check for {file_path}: {e}")
