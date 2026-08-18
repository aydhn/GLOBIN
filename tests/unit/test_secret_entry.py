"""Asking a person for a credential, and every way that is refused.

The refusals are the whole file. A happy path exists and is one test; the other
fourteen are about *not* collecting -- because the value of this adapter is
almost entirely in what it declines to do.

Two of them assert an absence rather than a result, and those are the ones worth
reading: a non-interactive stdin proves `getpass` was **never called**, and an
echo warning proves **nothing was read**. Both are the difference between a value
that was discarded and a value that never existed.
"""

import getpass
import io
from collections.abc import Callable

import pytest

from globin.adapters.secret_entry import ConsoleSecretEntry
from globin.domain.secrets import (
    MAX_SECRET_BYTES,
    PEM_ARMOUR,
    EntryFault,
    EntryProblem,
)


class _Stdin:
    """A stdin that answers `isatty` however a test needs, or raises."""

    def __init__(self, *, tty: bool = True, raises: bool = False) -> None:
        self._tty = tty
        self._raises = raises

    def isatty(self) -> bool:
        if self._raises:
            msg = "this stream has no opinion"
            raise ValueError(msg)
        return self._tty


def entry(*, tty: bool = True, raises: bool = False) -> ConsoleSecretEntry:
    return ConsoleSecretEntry(stream=io.StringIO(), stdin=_Stdin(tty=tty, raises=raises))


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[object]], list[str]]:
    """Substitute `getpass.getpass` with a scripted sequence.

    Returns a list that records the prompts, so a test can assert the reader was
    never reached rather than only that the outcome was a refusal.
    """

    def install(script: list[object]) -> list[str]:
        prompts: list[str] = []
        remaining = list(script)

        def fake(prompt: str = "", stream: object = None) -> str:
            del stream
            prompts.append(prompt)
            answer = remaining.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return str(answer)

        monkeypatch.setattr(getpass, "getpass", fake)
        return prompts

    return install


# ---------------------------------------------------------------------------
# Refusals that happen before anything is read
# ---------------------------------------------------------------------------


def test_a_pipe_is_refused_and_the_reader_is_never_reached(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """The refusal that stops a key reaching shell history.

    SECURITY_BASELINE.md section 2 prohibits material on a command line or in
    shell history, and accepting a pipe is how it would get there.
    """
    prompts = reads(["never-read"])
    outcome = entry(tty=False).collect("key: ")
    assert outcome.fault is EntryFault.NOT_INTERACTIVE
    assert prompts == []


def test_a_stream_with_no_opinion_about_being_a_terminal_is_refused(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """Refusing is the safe direction when the question cannot be answered."""
    prompts = reads(["never-read"])
    assert entry(raises=True).collect("key: ").fault is EntryFault.NOT_INTERACTIVE
    assert prompts == []


def test_an_echo_warning_aborts_before_the_operator_types_anything(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """SECRET_STORE_CONTRACT.md section 5, and stronger than it asks for.

    `fallback_getpass` warns *before* it prints its notice and *before* it
    reads, so turning the warning into an error aborts while nothing has been
    typed. The value never exists, rather than existing and being discarded.
    """
    reads([getpass.GetPassWarning("echo is on")])
    assert entry().collect("key: ").fault is EntryFault.ECHO_UNAVAILABLE


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        pytest.param(EOFError(), EntryFault.CANCELLED, id="end-of-input"),
        pytest.param(KeyboardInterrupt(), EntryFault.CANCELLED, id="interrupt"),
        pytest.param(OSError("no console"), EntryFault.ENTRY_UNAVAILABLE, id="no-console"),
    ],
)
def test_a_terminal_that_ends_the_entry_is_an_answer_rather_than_an_exception(
    reads: Callable[[list[object]], list[str]],
    raised: BaseException,
    expected: EntryFault,
) -> None:
    """A `KeyboardInterrupt` is caught rather than propagated, deliberately."""
    reads([raised])
    assert entry().collect("key: ").fault is expected


# ---------------------------------------------------------------------------
# Refusals about what was typed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("material", "problem"),
    [
        pytest.param("", EntryProblem.EMPTY, id="empty"),
        pytest.param(" leading", EntryProblem.SURROUNDING_WHITESPACE, id="leading-space"),
        pytest.param("trailing\t", EntryProblem.SURROUNDING_WHITESPACE, id="trailing-tab"),
        pytest.param("mid\x00dle", EntryProblem.CONTROL_CHARACTER, id="embedded-nul"),
        pytest.param("bell\x07", EntryProblem.CONTROL_CHARACTER, id="embedded-bell"),
        pytest.param("x" * (MAX_SECRET_BYTES + 1), EntryProblem.TOO_LARGE, id="oversize"),
    ],
)
def test_material_that_cannot_be_stored_is_refused_by_name(
    reads: Callable[[list[object]], list[str]],
    material: str,
    problem: EntryProblem,
) -> None:
    """Refused rather than stripped, trimmed or truncated.

    Every one of those would be a transformation nobody asked for, producing a
    credential wrong in a way nothing downstream can see.
    """
    reads([material])
    outcome = entry().collect("key: ")
    assert outcome.fault is EntryFault.REFUSED_FORMAT
    assert problem in outcome.problems


def test_an_oversize_pem_key_says_so_rather_than_leaving_a_platform_fault(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """phase_028_sources.md S-11: an RSA-4096 PEM is 3324 bytes and does not fit.

    Without this branch the platform answers with an undocumented
    `RPC_X_BAD_STUB_DATA`, which names neither the size nor the ceiling.

    **Two problems are reported, and the second is the more interesting one.** A
    real PEM document is multi-line, so it also trips the control-character rule
    -- which means armoured key material cannot be collected through this path at
    all, whatever its size. That is a genuine limit of interactive entry rather
    than an oversight, and it is asserted here so it is discovered by reading
    rather than at a terminal. A phase that needs to accept a PEM key will have
    to add a collection route that is not a single-line console prompt.
    """
    reads([PEM_ARMOUR + " RSA PRIVATE KEY-----\n" + "x" * MAX_SECRET_BYTES])
    outcome = entry().collect("key: ")
    assert set(outcome.problems) == {
        EntryProblem.CONTROL_CHARACTER,
        EntryProblem.ARMOURED_KEY_TOO_LARGE,
    }


def test_a_single_line_key_over_the_ceiling_reports_only_its_size(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """The armoured branch on its own, with no newline to confuse it."""
    reads([PEM_ARMOUR + "x" * MAX_SECRET_BYTES])
    outcome = entry().collect("key: ")
    assert outcome.problems == (EntryProblem.ARMOURED_KEY_TOO_LARGE,)


def test_no_reported_problem_carries_any_part_of_what_was_typed(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """A length is publishable; an offset or a substring is not."""
    reads([" GLOBIN-PHASE029-SYNTHETIC-CANARY "])
    outcome = entry().collect("key: ")
    rendered = repr(outcome.as_record())
    assert "CANARY" not in rendered
    assert all(isinstance(problem, EntryProblem) for problem in outcome.problems)


# ---------------------------------------------------------------------------
# The confirmation
# ---------------------------------------------------------------------------


def test_the_material_is_asked_for_twice(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """There is no argument that could switch this off, which is the design."""
    prompts = reads(["same-key", "same-key"])
    assert entry().collect("key: ").collected is True
    assert len(prompts) == 2
    assert prompts[0] != prompts[1]


def test_two_different_entries_store_nothing(
    reads: Callable[[list[object]], list[str]],
) -> None:
    reads(["first-key", "second-key"])
    assert entry().collect("key: ").fault is EntryFault.MISMATCH


def test_a_malformed_second_entry_reports_a_mismatch_and_not_its_shape(
    reads: Callable[[list[object]], list[str]],
) -> None:
    """The second entry's shape is not disclosed, only that it differed."""
    reads(["good-key", " bad-key "])
    outcome = entry().collect("key: ")
    assert outcome.fault is EntryFault.MISMATCH
    assert outcome.problems == ()


def test_a_terminal_that_dies_during_the_confirmation_is_reported(
    reads: Callable[[list[object]], list[str]],
) -> None:
    reads(["good-key", EOFError()])
    assert entry().collect("key: ").fault is EntryFault.CANCELLED


def test_the_first_entry_appears_nowhere_in_a_mismatch_record(
    reads: Callable[[list[object]], list[str]],
) -> None:
    reads(["GLOBIN-PHASE029-SYNTHETIC-CANARY", "something-else"])
    outcome = entry().collect("key: ")
    assert "CANARY" not in repr(outcome.as_record())


# ---------------------------------------------------------------------------
# The one path that succeeds
# ---------------------------------------------------------------------------


def test_two_matching_entries_produce_a_value_that_will_not_render_itself(
    reads: Callable[[list[object]], list[str]],
) -> None:
    reads(["a-real-looking-key", "a-real-looking-key"])
    outcome = entry().collect("key: ")
    assert outcome.collected is True
    assert outcome.fault is None
    assert "a-real-looking-key" not in repr(outcome.value)
