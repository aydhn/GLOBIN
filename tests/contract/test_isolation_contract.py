"""The suite's offline and isolation guarantees, exercised rather than asserted.

``docs/TESTING_STRATEGY.md`` has said since Phase 004 that no test may touch the
network or depend on execution order. Phase 005 turned both from rules people
remember into fixtures that enforce them, and a fixture nobody has watched refuse
anything is indistinguishable from one that cannot refuse.

So each guard here is used the way a violating test would use it, and asserted to
complain. Where the guard has an opt-out, the opt-out is exercised too — a check
that can only ever say no is as broken as one that can only ever say yes, and
the failure mode is that someone deletes it when it gets in the way.
"""

import os
import socket
from pathlib import Path

import pytest

from tests.support import process_state_drift

#: Captured while this module is imported, which happens during collection and
#: therefore before any fixture has patched anything. This is the real
#: :meth:`socket.socket.connect`, and comparing against it is how a test can tell
#: whether the guard is currently installed.
PRISTINE_CONNECT = socket.socket.connect

#: An address that must never be reached. TEST-NET-1 (RFC 5737) is reserved for
#: documentation and is not routable, so if the guard ever failed open this would
#: time out rather than contact anyone.
UNREACHABLE = ("192.0.2.1", 9)


# --------------------------------------------------------------------------
# The network guard
# --------------------------------------------------------------------------


def test_opening_a_connection_is_refused() -> None:
    """The failing case for the offline guarantee.

    ``pytest.fail`` raises ``Failed``, which derives from ``BaseException`` so
    that no ``except Exception`` in production code can absorb it. That is why
    this catches ``BaseException`` and pins the identity with ``match`` instead
    of naming a pytest-internal type.
    """
    with pytest.raises(BaseException, match="tried to connect to") as refused:
        socket.create_connection(UNREACHABLE, timeout=0.001)

    assert type(refused.value).__name__ == "Failed"


def test_connecting_a_socket_directly_is_refused() -> None:
    """Not only the convenience function: the method underneath it is patched too.

    ``create_connection`` is the obvious route and the easy one to guard. A
    caller that builds its own socket would bypass a guard that stopped there,
    and the code most likely to do that is exactly the transport code Phases
    033-048 will add.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(BaseException, match="tried to connect to"):
            sock.connect(UNREACHABLE)

        with pytest.raises(BaseException, match="tried to connect to"):
            sock.connect_ex(UNREACHABLE)


def test_the_guard_is_installed_for_an_ordinary_test() -> None:
    """The positive control: the patch really is in place during a normal test.

    Without this, the two tests above would still pass if ``connect`` raised for
    some entirely different reason.
    """
    assert socket.socket.connect is not PRISTINE_CONNECT


@pytest.mark.network
def test_a_test_marked_network_keeps_the_real_socket() -> None:
    """The opt-out works, so the guard has a door rather than a wall.

    Nothing connects here — there is nothing to connect to, and a test that
    reached the network would not be deterministic. What is asserted is that the
    marker restores the real implementation, which is what Phases 033-048 will
    rely on when the external level acquires its first test.
    """
    assert socket.socket.connect is PRISTINE_CONNECT


# --------------------------------------------------------------------------
# The process-state guard
# --------------------------------------------------------------------------


def test_drift_detection_is_quiet_when_nothing_moved() -> None:
    """The control case. A detector that always fires is a broken detector."""
    environment = {"PATH": "/usr/bin", "HOME": "/home/globin"}
    here = Path("/repo")

    assert (
        process_state_drift(
            environment_before=environment,
            environment_after=dict(environment),
            directory_before=here,
            directory_after=here,
        )
        == ()
    )


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        ({"PATH": "/usr/bin", "NEW": "1"}, "+NEW"),
        ({}, "-PATH"),
        ({"PATH": "/somewhere/else"}, "~PATH"),
    ],
    ids=["added", "removed", "altered"],
)
def test_every_kind_of_environment_change_is_reported(after: dict[str, str], expected: str) -> None:
    """Added, removed and altered are three separate ways to poison a later test.

    Reporting only the added ones would be the easy mistake — comparing key sets
    catches two of the three and looks complete.
    """
    here = Path("/repo")

    drift = process_state_drift(
        environment_before={"PATH": "/usr/bin"},
        environment_after=after,
        directory_before=here,
        directory_after=here,
    )

    assert len(drift) == 1
    assert expected in drift[0]


def test_a_changed_working_directory_is_reported() -> None:
    """Relative paths resolve differently afterwards, so this must not pass silently."""
    environment = {"PATH": "/usr/bin"}

    drift = process_state_drift(
        environment_before=environment,
        environment_after=environment,
        directory_before=Path("/repo"),
        directory_after=Path("/somewhere/else"),
    )

    assert len(drift) == 1
    assert "working directory" in drift[0]


def test_a_deleted_working_directory_is_reported_without_crashing() -> None:
    """A test that removes the directory it stands in must not break the detector.

    ``Path.cwd()`` raises in that state. Letting the exception escape teardown
    would replace a clear message about the leak with a confusing one about the
    guard.
    """
    environment = {"PATH": "/usr/bin"}

    drift = process_state_drift(
        environment_before=environment,
        environment_after=environment,
        directory_before=Path("/repo"),
        directory_after=None,
    )

    assert len(drift) == 1
    assert "no longer exists" in drift[0]


def test_both_kinds_of_drift_are_reported_together() -> None:
    """One line each, so a test that leaked twice is diagnosed once."""
    drift = process_state_drift(
        environment_before={"PATH": "/usr/bin"},
        environment_after={"PATH": "/usr/bin", "LEAKED": "1"},
        directory_before=Path("/repo"),
        directory_after=Path("/somewhere/else"),
    )

    assert len(drift) == 2


def test_monkeypatch_undoes_its_own_environment_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """The supported way to change the environment, and the reason the net is rarely hit.

    If this ever failed, every test using ``monkeypatch.setenv`` would start
    failing in teardown, which is a considerably better outcome than the silent
    order-dependence it replaces.
    """
    assert "GLOBIN_ISOLATION_PROBE" not in os.environ

    monkeypatch.setenv("GLOBIN_ISOLATION_PROBE", "set-by-this-test")

    assert os.environ["GLOBIN_ISOLATION_PROBE"] == "set-by-this-test"
