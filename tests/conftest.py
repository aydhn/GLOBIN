"""Session fixtures for the GLOBIN suite.

This file holds **only** fixtures. The helpers a test imports by name live in
``tests/support.py``; see that module for why the two are separated.

Scope discipline matters here more than it looks. A ``conftest.py`` at the root
of ``tests/`` applies to every test in every subdirectory, so anything added
here is paid for by the whole suite. Fixtures belong at the narrowest scope that
serves them: a fixture used by one module is declared in that module, a fixture
used across one taxonomy level belongs in that level's ``conftest.py``, and only
genuinely repository-wide facts belong here.

The repository-state fixtures below are ``scope="session"`` because each reads
immutable repository state. Re-reading ``ROADMAP.md`` once per test would be
slower and could not produce a different answer.

The two autouse fixtures are the exception to "keep this file small", and they
are here because they can only work here: a guarantee that holds for most of the
suite is not a guarantee. They are deliberately two rather than one, because
they defend different things and one of them has an opt-out the other must not
share. Nothing else in this file is autouse.

Hypothesis's settings profiles are registered here too. ``conftest.py`` is where
the upstream documentation puts them, and registering both profiles in one place
is what lets ``tests/contract/test_quality_contract.py`` assert that the CI
profile is actually reproducible instead of trusting a comment.
"""

import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Final, NoReturn

import pytest
from hypothesis import settings

from tests.support import (
    REPO_ROOT,
    RoadmapRow,
    git_committable_files,
    parse_roadmap,
    process_state_drift,
    taxonomy_level,
)

#: Markers whose tests are permitted to open a socket. Both are empty today:
#: no test carries either, and the external level does not exist until Phases
#: 033-048. The opt-out is written now so that the guard has a documented door
#: rather than acquiring an undocumented one later, under deadline.
NETWORK_PERMITTED_MARKERS: Final[frozenset[str]] = frozenset({"external", "network"})

#: Environment variables pytest maintains itself, which therefore change during
#: a test without any test having changed them. ``PYTEST_CURRENT_TEST`` is
#: rewritten at every phase — setup, call, teardown — so comparing it would
#: report a leak on every test in the suite.
PYTEST_OWNED_ENVIRONMENT: Final[frozenset[str]] = frozenset({"PYTEST_CURRENT_TEST"})

settings.register_profile("dev", max_examples=100, deadline=None, print_blob=True)
settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
    print_blob=True,
    # Seed from a hash of the test function, so the same code examines the same
    # inputs on every run. Without it a CI failure may not reproduce on rerun,
    # and an intermittent red build teaches people to press the retry button.
    derandomize=True,
    # No example database. On an ephemeral runner it would never be read back,
    # and a shared one would make a run depend on the run before it.
    database=None,
)
settings.load_profile("dev")


def _readable_environment() -> dict[str, str]:
    """The environment minus the variables pytest maintains for its own use."""
    return {
        name: value for name, value in os.environ.items() if name not in PYTEST_OWNED_ENVIRONMENT
    }


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply each test's taxonomy marker from the directory it lives in.

    Deriving the marker rather than writing it means ``pytest -m unit`` cannot
    disagree with the directory layout, and a moved file cannot keep a stale
    label. The alternative — a decorator on every test — is 187 opportunities to
    forget, and nothing would notice a mistake.

    A file the taxonomy does not describe is left unmarked on purpose. The
    contract suite fails on it by name, which is a better diagnosis than an
    exception thrown during collection.
    """
    for item in items:
        level = taxonomy_level(item.path)
        if level is not None:
            item.add_marker(level)


@pytest.fixture(autouse=True)
def isolate_process_state() -> Iterator[None]:
    """Restore the environment and working directory, and fail if a test moved them.

    Both are process-global, so a test that changes one changes it for every
    test that runs afterwards. That is the classic route to a suite which passes
    in one order and fails in another, and the symptom appears in the *victim*
    rather than in the culprit.

    Restoring and failing are both necessary and do different jobs. Restoring
    alone would keep the suite green while the leak stayed; failing alone would
    name the culprit and then let the damage spread. Doing both names the culprit
    while the leak is still on screen and stops it reaching the next test.

    Teardown runs whether the test passed or failed, so a test that raises
    part-way through still cannot leave the process altered.

    Tests that need a different environment or directory should use
    ``monkeypatch.setenv`` and ``monkeypatch.chdir``, which undo themselves. This
    fixture is the net beneath them, not a substitute for them.
    """
    environment = _readable_environment()
    directory = Path.cwd()

    yield

    try:
        finished_in: Path | None = Path.cwd()
    except OSError:
        # The test deleted the directory it was standing in.
        finished_in = None

    drift = process_state_drift(
        environment_before=environment,
        environment_after=_readable_environment(),
        directory_before=directory,
        directory_after=finished_in,
    )
    if not drift:
        return

    # Repair before reporting. Failing without repairing would name the culprit
    # and then let the damage reach every test that runs afterwards.
    reserved = {
        name: value for name, value in os.environ.items() if name in PYTEST_OWNED_ENVIRONMENT
    }
    os.environ.clear()
    os.environ.update(environment)
    os.environ.update(reserved)
    if finished_in != directory:
        os.chdir(directory)

    pytest.fail("test leaked process state:\n  " + "\n  ".join(drift), pytrace=False)


@pytest.fixture(autouse=True)
def block_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """Refuse every outbound socket connection for the duration of a test.

    ``docs/TESTING_STRATEGY.md`` states that no test at any level existing today
    may touch the network. Until now that was a rule people had to remember. It
    is a guarantee only if something enforces it, because the failure it prevents
    is not "a test fails" but "a test passes on a developer's machine, reaches a
    real service, and fails in CI or against a rate limit" — and, once GLOBIN has
    credentials, worse than that.

    The refusal is a :func:`pytest.fail`, not an :exc:`OSError`. A realistic
    connection error is exactly what retry and backoff code is written to
    swallow, so as soon as such code exists it would quietly absorb the guard and
    the suite would go on looking offline while doing nothing of the kind.
    ``Failed`` derives from :exc:`BaseException`, so no ``except Exception``
    reaches it.

    Name resolution is left alone. Nothing can act on an address without then
    connecting, so blocking the connection is sufficient and blocking DNS as well
    would only produce a less specific message.

    Subprocesses are unaffected — this patches sockets in this interpreter only.
    Nothing in the suite spawns a process that wants the network, and a test that
    did would be an integration or external test rather than one of these.

    **This fixture must not use ``monkeypatch``, tempting though it is.** pytest
    hoists an autouse fixture's dependencies to the front of the fixture closure,
    so requesting ``monkeypatch`` here would make it the *first* fixture set up
    and therefore the *last* torn down — after ``isolate_process_state`` has
    already inspected the environment. Every test calling ``monkeypatch.setenv``
    would then be reported as leaking a variable that ``monkeypatch`` was about
    to remove. Saving and restoring by hand keeps ``monkeypatch`` out of the
    autouse chain, so it stays where a test put it and unwinds first.
    """
    if NETWORK_PERMITTED_MARKERS.intersection(mark.name for mark in request.node.iter_markers()):
        yield
        return

    def refuse(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail(
            "this test tried to open a network connection, which the default "
            "test suite forbids (docs/TESTING_STRATEGY.md). Represent the remote "
            "side with a local test double, or mark the test `external`.",
            pytrace=False,
        )

    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    create_connection = socket.create_connection
    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse
    try:
        yield
    finally:
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.create_connection = create_connection


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def roadmap_text() -> str:
    """Raw text of ``ROADMAP.md``."""
    return (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def roadmap_rows(roadmap_text: str) -> list[RoadmapRow]:
    """Every phase row parsed from ``ROADMAP.md``."""
    return parse_roadmap(roadmap_text)


@pytest.fixture(scope="session")
def committable_files() -> tuple[str, ...]:
    """Repository-relative, POSIX-separated paths Git would commit from this tree."""
    return git_committable_files()


@pytest.fixture(scope="session")
def committable_markdown(committable_files: tuple[str, ...]) -> tuple[str, ...]:
    """Repository-relative paths of every committable Markdown document."""
    return tuple(path for path in committable_files if path.endswith(".md"))
