"""The precision policy document and the precision module say the same thing.

``docs/PRECISION_POLICY.md`` is where a contributor reads which rounding modes
exist and what each is for. The code is where the answer comes from, and two
statements of one rule diverge unless something compares them.

The dangerous direction here is a documented *mode*. A table listing a mode the
code does not implement is read by somebody who then writes a call around it; a
mode the code implements and the table omits is one nobody argued for. Both
directions are checked.

The bounds table is compared by value, not by name, because
:data:`~globin.domain.precision.EXACT_PRECISION` is derived from the value types'
own limits and a document stating the old number after a widening would be worse
than one stating none.

What this file does not do is restate the rules. Whether the module behaves is
``tests/unit/test_precision.py`` and
``tests/property/test_precision_properties.py``; whether the ambient context is
reachable is ``tests/architecture/test_precision_discipline.py``.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from globin.domain import precision
from globin.domain.precision import Rounding
from tests.support import markdown_prose

POLICY_RELATIVE_PATH: Final[str] = "docs/PRECISION_POLICY.md"

#: A row of the bounds table: a backticked SCREAMING_SNAKE name and its value.
CONSTANT_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<name>[A-Z][A-Z0-9_]+)` \| `(?P<value>[^`]+)` \|$",
    re.MULTILINE,
)

#: A row of the rounding table: four cells, the first a backticked member name.
#: The trailing cells are what keep this from matching the bounds table.
MODE_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<mode>[A-Z_]+)` \| (?P<equivalent>[^|]+) \| (?P<purpose>[^|]+) \|$",
    re.MULTILINE,
)

#: The phases the document must still name, so that a reader who arrives with a
#: question this policy does not answer is sent somewhere rather than left to
#: infer an answer from silence.
DEFERRED_PHASES: Final[tuple[str, ...]] = ("009", "011", "012", "082", "148", "242")

#: Every public bound the module publishes, read off the code rather than the
#: document. Uppercase names only, and only the scalar ones a table can carry.
PUBLISHED_BOUNDS: Final[dict[str, str]] = {
    name: str(value)
    for name in dir(precision)
    if name.isupper() and isinstance(value := getattr(precision, name), str | int)
}


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> str:
    """The policy document, read once."""
    return (repo_root / POLICY_RELATIVE_PATH).read_text(encoding="utf-8")


def test_every_published_bound_is_documented(policy: str) -> None:
    """The bounds table names every constant the module publishes, and no other.

    A constant added without a row is one a reader cannot discover; a row without
    a constant is a promise the code does not keep.
    """
    documented = {match.group("name") for match in CONSTANT_ROW_RE.finditer(policy)}
    assert documented == set(PUBLISHED_BOUNDS), (
        f"documented but not published: {sorted(documented - set(PUBLISHED_BOUNDS))}; "
        f"published but not documented: {sorted(set(PUBLISHED_BOUNDS) - documented)}"
    )


def test_every_documented_bound_states_the_value_the_code_holds(policy: str) -> None:
    """The strong form: the number in the table is the number in the module.

    This is what kills the mutant that increments a constant. Without it,
    ``EXACT_PRECISION = 129`` would pass every test in the suite.
    """
    for match in CONSTANT_ROW_RE.finditer(policy):
        name = match.group("name")
        assert match.group("value") == PUBLISHED_BOUNDS[name], name


def test_every_rounding_mode_is_documented(policy: str) -> None:
    """The mode table and the enum agree in both directions."""
    documented = {match.group("mode") for match in MODE_ROW_RE.finditer(policy)}
    assert documented == {member.name for member in Rounding}


def test_the_document_states_what_each_mode_is_for(policy: str) -> None:
    """A mode with no stated purpose is one that will be chosen by proximity.

    The purpose cell is what a reader consults when deciding between `FLOOR` and
    `CEILING`, so an empty or placeholder one defeats the table.
    """
    for match in MODE_ROW_RE.finditer(policy):
        purpose = match.group("purpose").strip()
        assert len(purpose) > 20, f"{match.group('mode')} has no stated purpose"


def test_the_document_names_the_phases_it_defers_to(policy: str) -> None:
    """Silence must not be mistaken for an answer.

    ``AGENTS.md``: "If a fact is not yet established, state that explicitly and
    name the phase responsible for establishing it."
    """
    prose = markdown_prose(policy)
    missing = [phase for phase in DEFERRED_PHASES if phase not in prose]
    assert not missing, f"the policy no longer names the phases owning: {missing}"


def test_the_document_states_the_boundary_with_the_time_phase(policy: str) -> None:
    """The Phase 009 collision is the one a reader is most likely to raise.

    ``TIME_POLICY.md`` carries the mirror of this sentence, and
    ``test_clock_contract.py`` asserts it from the other side. Both must survive
    an editorial pass, so both are pinned.
    """
    lowered = policy.lower()
    assert "coordinate" in lowered
    assert "magnitude" in lowered


def test_the_document_records_that_the_copied_bounds_are_a_tripwire(policy: str) -> None:
    """A copy without a stated reason is indistinguishable from a duplication.

    ``SOURCE_OF_TRUTH.md`` permits restating a value only when a test compares
    the copies. The document has to say so, or the next reader deletes one.
    """
    prose = markdown_prose(policy)
    assert "tripwire" in prose.lower()
    assert "SOURCE_OF_TRUTH.md" in policy
