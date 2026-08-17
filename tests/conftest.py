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

import ipaddress
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

#: Markers whose tests are permitted to open *any* connection. The external level
#: does not exist until Phases 033-048, and ``network``'s own registration says it
#: is "never permitted below the external level" — so the only test carrying either
#: today is the one in ``tests/contract/test_isolation_contract.py`` that proves the
#: door works. The opt-out was written before anything needed it so that the guard
#: had a documented door rather than acquiring an undocumented one later.
NETWORK_PERMITTED_MARKERS: Final[frozenset[str]] = frozenset({"external", "network"})

#: The marker whose tests may connect to loopback, and to nothing else.
#:
#: Added in Phase 027, which built a loopback HTTP surface and therefore needed
#: tests that make a real request to it. The guard already permitted ``bind`` and
#: ``listen``; what it refused was the client half, so an end-to-end test of a local
#: server was impossible without opting out of the guard entirely.
#:
#: **Narrowing rather than opting out is the whole point.** ``network`` would have
#: removed the guarantee for those tests, and its own registered description forbids
#: it below the external level anyway. This keeps the guarantee that matters — no
#: test reaches another machine — while permitting the one thing a local surface
#: needs. A ``loopback``-marked test that tried to reach a real service still fails.
LOOPBACK_PERMITTED_MARKER: Final[str] = "loopback"

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

    **``bind`` and ``listen`` were never blocked, and Phase 027 is when that
    mattered.** The guard defends against reaching *out*; a test that opens a
    listening socket on this machine reaches nothing. What it could not previously
    do was connect to its own listener, which made an end-to-end test of a local
    HTTP surface impossible. The ``loopback`` marker permits exactly that and
    nothing more: a marked test connecting to anything that is not a loopback
    address still fails, so the guarantee is narrowed rather than lifted.

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
    markers = {mark.name for mark in request.node.iter_markers()}
    if NETWORK_PERMITTED_MARKERS.intersection(markers):
        yield
        return
    permit_loopback = LOOPBACK_PERMITTED_MARKER in markers

    def refuse(target: object) -> NoReturn:
        pytest.fail(
            f"this test tried to connect to {target!r}, which the default test suite "
            "forbids (docs/TESTING_STRATEGY.md). Represent the remote side with a "
            "local test double, mark the test `loopback` if the target really is this "
            "machine, or mark it `external`.",
            pytrace=False,
        )

    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    create_connection = socket.create_connection

    def guarded(original: object) -> object:
        """Wrap a bound-method connector so loopback may pass and nothing else may."""

        def call(self: object, address: object, *args: object, **kwargs: object) -> object:
            if permit_loopback and _is_loopback(address):
                return original(self, address, *args, **kwargs)  # type: ignore[operator]
            refuse(address)

        return call

    def guarded_create(address: object, *args: object, **kwargs: object) -> object:
        """Wrap :func:`socket.create_connection`, whose first argument is the target."""
        if permit_loopback and _is_loopback(address):
            return create_connection(address, *args, **kwargs)  # type: ignore[arg-type]
        refuse(address)

    socket.socket.connect = guarded(connect)  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = guarded(connect_ex)  # type: ignore[method-assign,assignment]
    socket.create_connection = guarded_create  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.create_connection = create_connection


def _is_loopback(address: object) -> bool:
    """Whether a connect target is on this machine.

    Args:
        address: Whatever was passed to a connector.

    Returns:
        Whether it is a loopback address.

    **The host is parsed, not compared.** Reusing
    :func:`~globin.domain.diagnostics_http.address_problems` would import the product
    into the guard, so this parses directly — but for the same reason: a denylist of
    spellings has to be complete, and ``is_loopback`` is a property of the parsed
    address. A target this cannot make sense of is **not** loopback, so an unfamiliar
    address family is refused rather than waved through.
    """
    if not isinstance(address, tuple) or not address:
        return False
    try:
        return ipaddress.ip_address(str(address[0])).is_loopback
    except ValueError:
        return False


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
