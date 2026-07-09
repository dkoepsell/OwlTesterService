"""Shared pytest fixtures for the BFO coherence foundation tests."""

import os
import tempfile

import pytest

# The app module is a process-wide singleton that binds its database engine at
# import time; every test file that imports `app` shares that one binding, and
# whichever file imports it FIRST decides the database for the whole run.
# Point the suite at a scratch database here — conftest imports before any test
# module — so no collection order can bind the tests to the developer's real
# owl_tester.db (whose schema may be stale) or to a per-test path that later
# files silently miss.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(prefix="owltester-tests-"), "suite.db")

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture_path(name):
    """Absolute path to a fixture OWL file under tests/fixtures/."""
    return os.path.join(FIXTURES_DIR, name)


@pytest.fixture(scope="session")
def catalog():
    """The vendored BFO 2020 catalog, loaded once per test session."""
    from bfo import load_catalog
    return load_catalog()


@pytest.fixture(scope="session")
def straddle_owl():
    return fixture_path("quality_disposition_straddle.owl")


@pytest.fixture(scope="session")
def coherent_owl():
    return fixture_path("coherent_tiny.owl")


def _java_available():
    """True if a Java runtime is on PATH (Pellet needs it)."""
    from shutil import which
    return which("java") is not None


requires_java = pytest.mark.skipif(
    not _java_available(), reason="Pellet requires a Java runtime"
)
