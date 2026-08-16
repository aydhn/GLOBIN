"""Invariants of the bootstrap that hold over generated input, not chosen examples.

Two properties earn a place here. **A path from outside the project never appears
in what is recorded**, whatever that path is — the example-based tests pick a
plausible one, and this picks thousands nobody thought of. And **the exit code is
a total function of the report**, so no combination of statuses produces a
success by accident.
"""

import string

from hypothesis import given
from hypothesis import strategies as st

from globin.domain.bootstrap import (
    BootstrapReport,
    CheckOutcome,
    CheckStatus,
    DependencyReadiness,
    ExitCode,
    HostFacts,
    InterpreterFacts,
    ProjectIdentity,
    check_identifiers,
    context_fingerprint,
    exit_code_for,
    fingerprint_of,
    recorded_inside,
    recorded_outside,
)

SEGMENT_ALPHABET = string.ascii_letters + string.digits + "-_. "

segments = st.text(alphabet=SEGMENT_ALPHABET, min_size=1, max_size=12).filter(
    lambda text: text.strip(" .") != "" and text == text.strip()
)
"""One path component. Windows refuses a trailing space or dot, so neither is
generated — a value the platform cannot represent is not a case worth covering.
"""

absolute_paths = st.builds(
    lambda drive, parts: f"{drive}:\\Users\\" + "\\".join(parts),
    st.sampled_from("CDE"),
    st.lists(segments, min_size=1, max_size=4),
)

statuses = st.sampled_from(list(CheckStatus))

FORBIDDEN_FRAGMENTS = ("C:", "D:", "Users", "AppData", "/home/", "Program Files")


@given(absolute_paths)
def test_a_path_from_outside_the_project_never_appears_in_what_is_recorded(
    outside: str,
) -> None:
    """The privacy invariant. Whatever the path is, the record does not contain it."""
    recorded = recorded_outside(outside)
    rendered = str(recorded.as_record())
    assert outside not in rendered
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in rendered


@given(absolute_paths)
def test_a_fingerprint_is_hexadecimal_and_of_a_fixed_width(outside: str) -> None:
    """Fixed width, so a reader cannot infer the length of what produced it."""
    digest = fingerprint_of(outside)
    assert len(digest) == len(fingerprint_of(""))
    assert all(character in string.hexdigits for character in digest)


@given(absolute_paths, absolute_paths)
def test_two_different_paths_fingerprint_differently(first: str, second: str) -> None:
    """Otherwise "the same interpreter as last time" would not be answerable."""
    if first != second:
        assert fingerprint_of(first) != fingerprint_of(second)


@given(st.lists(statuses, min_size=1, max_size=len(check_identifiers())))
def test_the_exit_code_is_a_total_function_of_the_statuses(
    chosen: list[CheckStatus],
) -> None:
    """No combination produces a success by accident, and none raises.

    Three rules, in this order: an unmeasured check outranks a failed one; a
    failed check yields the earliest failing check's own code; and everything
    else — which is only passes and warnings — is success.
    """
    outcomes = tuple(
        CheckOutcome(
            identifier=identifier,
            status=status,
            summary="generated",
            remediation="" if status is CheckStatus.PASS else "act on this",
        )
        for identifier, status in zip(check_identifiers(), chosen, strict=False)
    )
    code = exit_code_for(BootstrapReport(outcomes=outcomes))

    if CheckStatus.UNMEASURED in chosen:
        assert code is ExitCode.UNMEASURED
    elif CheckStatus.FAIL in chosen:
        first = next(check for check in outcomes if check.status is CheckStatus.FAIL)
        assert code is first.exit_code
    else:
        assert code is ExitCode.OK


#: Letters a hexadecimal digest cannot contain. Generating a name from `abcdef`
#: would make the assertion below fail by coincidence rather than by leakage,
#: which is a property test asserting the wrong thing.
NON_HEX_LETTERS = "ghijklmnopqrstuvwxyz"


@given(st.text(alphabet=NON_HEX_LETTERS, min_size=3, max_size=8), st.integers(0, 1))
def test_the_context_fingerprint_never_carries_a_path_it_was_given(name: str, count: int) -> None:
    """Only the recorded form participates, so the real one cannot leak through."""
    outside = "C:\\Users\\" + name
    digest = context_fingerprint(
        identity=ProjectIdentity(name="globin", version="0.1.0", source="metadata"),
        host=HostFacts(system="Windows", release="11", machine="AMD64", pointer_bits=64),
        interpreter=InterpreterFacts(
            implementation="cpython",
            version="3.14.5",
            release_level="final",
            free_threaded=False,
            executable=recorded_inside(".venv/Scripts/python.exe"),
            prefix=recorded_inside(".venv"),
            base_prefix=recorded_outside(outside),
            in_virtual_environment=True,
        ),
        dependencies=DependencyReadiness(declared=("numpy",)[:count], locked=True),
    )
    assert name not in digest
    assert digest.startswith("sha256:")


@given(absolute_paths, st.lists(segments, min_size=1, max_size=4))
def test_a_recorded_path_carries_exactly_one_of_the_two_fields(
    outside: str, parts: list[str]
) -> None:
    """The type invariant, over every value the two factories can produce.

    An example-based test picks one path each way; this asserts that no input
    reaches a state carrying both a spelling and a fingerprint, which is the
    state that would put an absolute path into the evidence.
    """
    for recorded in (recorded_inside("/".join(parts)), recorded_outside(outside)):
        assert (recorded.path is None) != (recorded.fingerprint is None)
