"""The escalation, proved by a process that actually dies.

Every other test of the watchdog substitutes the terminator, and must: a test that
called ``os._exit`` would take the runner with it. That leaves one claim resting on
reasoning rather than execution — **that the real path ends a real process with
exit code 23** — and this is the test that pays it off.

A child interpreter arms a real watchdog over a component that never beats, with a
real :class:`~globin.adapters.watchdog.ImmediateProcessExit`. The parent waits, with
a deadline, and reads the status the operating system reports.

**Every wait is bounded and every child is killed in a ``finally``.** A hung child
would otherwise stall the suite rather than report a broken escalation. The child
reaches no network — it registers a component, fails to beat it, and exits — so the
offline guard, which does not cross a process boundary, is not being evaded.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode
from globin.domain.runtime_state import RuntimeArea, RuntimeLayout
from globin.runtime.composition import WATCHDOG_FILE
from tests.support import REPO_ROOT

DEADLINE_SECONDS: float = 60.0
"""How long the child may take before the test fails it.

Generously above the thresholds the child configures — roughly two seconds of
watching plus interpreter start-up — so a slow machine does not fail this and a
broken escalation still cannot hang the suite.
"""

STALLER = """
import sys, time
from pathlib import Path

from globin.adapters.watchdog import ImmediateProcessExit
from globin.domain.configuration import (
    DiagnosticsConfig,
    GlobinConfig,
    LoggingConfig,
    TelemetryConfig,
    WatchdogConfig,
)
from globin.domain.watchdog import Criticality
from globin.runtime.composition import (
    build_heartbeats,
    build_runtime_state,
    build_watchdog,
)

config = GlobinConfig(
    logging=LoggingConfig(),
    diagnostics=DiagnosticsConfig(),
    watchdog=WatchdogConfig(
        interval_millis=100,
        grace_millis=0,
        stall_millis=1000,
        escalate_millis=1000,
    ),
    telemetry=TelemetryConfig(),
)

state = build_runtime_state()
state.tree.prepare(state.layout)
beats = build_heartbeats()
beats.register("feed", Criticality.REQUIRED)

# The real terminator. Nothing is substituted here, which is the whole point of
# running this in a process of its own.
watchdog = build_watchdog(
    state,
    beats,
    run_id="fedcba9876543210fedcba9876543210",
    correlation_id="00112233445566778899aabbccddeeff",
    config=config,
    terminator=ImmediateProcessExit(),
)
watchdog.start()

# Never beat. The main thread waits well past the deadline the policy declares,
# and if the watchdog works it never finishes waiting.
Path(sys.argv[1]).write_text("armed", encoding="utf-8")
time.sleep(30)

# Only reached if the escalation did not happen. A distinct code, so the parent
# can tell "the watchdog did nothing" from "the watchdog ran and chose 23".
watchdog.stop()
sys.exit(70)
"""


@pytest.fixture
def runtime_root(tmp_path: Path) -> Path:
    """A runtime root in a temporary directory, never a real user profile."""
    return tmp_path


def _environment(root: Path) -> dict[str, str]:
    """The child's environment: this one's, plus the source tree and a private root.

    ``pythonpath = ["src"]`` is a pytest setting and does not reach a child, so the
    child is told where the package is rather than left to guess. ``LOCALAPPDATA``
    is redirected so the child's runtime tree is the temporary directory and never
    the developer's own.
    """
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    source = str(REPO_ROOT / "src")
    environment["PYTHONPATH"] = f"{source}{os.pathsep}{existing}" if existing else source
    environment["LOCALAPPDATA"] = str(root)
    return environment


def _state_area(root: Path) -> Path:
    """Where the child's runtime tree keeps its published documents."""
    layout = RuntimeLayout()
    return root / layout.namespace / layout.segment_for(RuntimeArea.STATE)


@pytest.mark.slow
def test_a_component_that_never_beats_ends_its_process_with_code_23(
    runtime_root: Path, tmp_path: Path
) -> None:
    """The one claim that cannot be made with a fake, made with a real process.

    A required component is registered and never beaten. The child does nothing
    else: it waits far longer than the deadline, so the only way it can end inside
    this test's own deadline is the watchdog ending it.
    """
    armed = tmp_path / "armed.txt"
    child = subprocess.Popen(  # noqa: S603 - the interpreter and script are this file's own
        [sys.executable, "-c", STALLER, str(armed)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(runtime_root),
        cwd=REPO_ROOT,
    )
    try:
        _stdout, stderr = child.communicate(timeout=DEADLINE_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        pytest.fail("the child outlived the watchdog's own deadline, so nothing ended it")
    finally:
        if child.poll() is None:  # pragma: no cover - only on an unexpected path
            child.kill()

    assert child.returncode == int(ExitCode.WATCHDOG_STALLED), stderr
    assert armed.exists(), "the child never got as far as arming its watchdog"


@pytest.mark.slow
def test_the_incident_survives_the_process_that_was_ended(
    runtime_root: Path, tmp_path: Path
) -> None:
    """`os._exit` runs no cleanup, so the record has to be durable *before* it.

    This is the property the ordering inside a confirmed stall exists to provide:
    claim, log, capture, **publish**, ask. If the incident were written on the way
    out it would not be here, because there is no way out.
    """
    armed = tmp_path / "armed.txt"
    child = subprocess.Popen(  # noqa: S603 - the interpreter and script are this file's own
        [sys.executable, "-c", STALLER, str(armed)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(runtime_root),
        cwd=REPO_ROOT,
    )
    try:
        child.communicate(timeout=DEADLINE_SECONDS)
    except subprocess.TimeoutExpired:  # pragma: no cover - the test above reports this
        child.kill()
        child.communicate()
        pytest.fail("the child outlived the watchdog's own deadline")
    finally:
        if child.poll() is None:  # pragma: no cover - only on an unexpected path
            child.kill()

    incident = _state_area(runtime_root) / WATCHDOG_FILE
    assert incident.exists(), "the process was ended and left no explanation"
    written = incident.read_text(encoding="utf-8")
    assert '"component":"feed"' in written
    assert '"escalated":true' in written
