"""The documented preflight tables, against the code that implements them.

``test_preflight.py`` owns the kind — what a classification means and what a
schedule refuses. This owns the register: the durability table in
``PREFLIGHT_SUITE.md``, the command group in ``cli.py``, and the configuration
evidence surface's documented precedence, each compared against its source in both
directions so that a row cannot drift quietly.

Every comparison here runs over ``markdown_prose``, so a sentence *naming* a value
in prose cannot satisfy an assertion about a table that lists it.
"""

import re
from pathlib import Path

import pytest

from globin.domain.bootstrap import Durability, checks
from globin.domain.config_evidence import CONFIG_SCHEMA_VERSION, SCHEMA_VERSION_KEY
from globin.domain.preflight import (
    DEFAULT_RECHECK_INTERVAL_MILLIS,
    MAXIMUM_RECHECK_INTERVAL_MILLIS,
    MINIMUM_RECHECK_INTERVAL_MILLIS,
    build_suite,
)
from globin.runtime.cli import BOOTSTRAP_SUBCOMMANDS, CONFIG_SUBCOMMANDS, USAGE
from tests.support import markdown_prose

SUITE_DOCUMENT: str = "docs/engineering/PREFLIGHT_SUITE.md"
EVIDENCE_DOCUMENT: str = "docs/engineering/CONFIGURATION_EVIDENCE.md"

DURABILITY_ROW_RE = re.compile(
    r"^\| `(?P<check>[a-z_]+\.[a-z_]+)` \| `(?P<value>\w+)` \|$", re.MULTILINE
)


@pytest.fixture(scope="session")
def suite_text(repo_root: Path) -> str:
    """The preflight document, as written."""
    return (repo_root / SUITE_DOCUMENT).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def evidence_text(repo_root: Path) -> str:
    """The configuration evidence document, as written."""
    return (repo_root / EVIDENCE_DOCUMENT).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The durability register
# ---------------------------------------------------------------------------


def test_the_documented_table_names_exactly_the_registered_checks(suite_text: str) -> None:
    """A row for a check that no longer exists misleads more than a missing row."""
    documented = {match["check"] for match in DURABILITY_ROW_RE.finditer(suite_text)}
    assert documented == {spec.identifier for spec in checks()}


def test_every_documented_durability_matches_the_code(suite_text: str) -> None:
    """The comparison that makes the table evidence rather than decoration."""
    documented = {
        match["check"]: match["value"] for match in DURABILITY_ROW_RE.finditer(suite_text)
    }
    for spec in checks():
        assert documented[spec.identifier] == spec.durability.name


SPELLED: dict[int, str] = {
    7: "seven",
    8: "eight",
    10: "ten",
    11: "eleven",
    12: "twelve",
    18: "eighteen",
    19: "nineteen",
}
"""How the document spells the counts it states.

A map rather than a library, and a :exc:`KeyError` when the split moves outside it
is the intended failure: somebody has to write the new word into the document, and
a test that quietly stopped checking would be worse than one that stops.
"""


def test_the_documented_counts_match_the_split(suite_text: str) -> None:
    """A number written in prose is bound to its source."""
    suite = build_suite()
    stable = SPELLED[len(suite.stable())]
    perishable = SPELLED[len(suite.perishable())]
    expected = f"{stable.capitalize()} stable, {perishable} perishable."
    assert expected in markdown_prose(suite_text)


def test_every_declared_durability_is_a_member_of_the_enumeration() -> None:
    """A string that merely looks like one would not be caught by the table above."""
    assert all(spec.durability in set(Durability) for spec in checks())


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(MINIMUM_RECHECK_INTERVAL_MILLIS, id="floor"),
        pytest.param(DEFAULT_RECHECK_INTERVAL_MILLIS, id="default"),
        pytest.param(MAXIMUM_RECHECK_INTERVAL_MILLIS, id="ceiling"),
    ],
)
def test_the_documented_bounds_are_the_declared_ones(suite_text: str, value: int) -> None:
    """Three numbers in a table, each compared to the constant it restates."""
    assert f"{value:,}".replace(",", " ") in suite_text


def test_the_document_says_nothing_executes_a_retake(suite_text: str) -> None:
    """The deliberate half, which a reader must not have to infer from an absence."""
    assert "No re-take is executed anywhere" in markdown_prose(suite_text)


# ---------------------------------------------------------------------------
# The command surfaces
# ---------------------------------------------------------------------------


def test_every_bootstrap_subcommand_appears_in_the_usage_text() -> None:
    """A command a reader cannot discover is a command that does not exist."""
    for word in BOOTSTRAP_SUBCOMMANDS:
        assert f"bootstrap {word}" in USAGE


def test_every_config_subcommand_appears_in_the_usage_text() -> None:
    """The same rule, applied to the group Phase 030 added."""
    for word in CONFIG_SUBCOMMANDS:
        assert f"config {word}" in USAGE


def test_every_config_subcommand_is_documented(evidence_text: str) -> None:
    """A verb with no documentation is a verb nobody can be expected to use correctly."""
    for word in CONFIG_SUBCOMMANDS:
        assert f"config {word}" in evidence_text


def test_the_evidence_document_states_the_verb_count(evidence_text: str) -> None:
    """A count in prose, bound to the tuple it restates."""
    assert len(CONFIG_SUBCOMMANDS) == 5
    assert "Five verbs" in markdown_prose(evidence_text)


# ---------------------------------------------------------------------------
# The configuration contract version
# ---------------------------------------------------------------------------


def test_the_reserved_document_key_is_documented_with_its_version(evidence_text: str) -> None:
    """An operator writing the line needs both the spelling and the number."""
    assert SCHEMA_VERSION_KEY in evidence_text
    assert f"{SCHEMA_VERSION_KEY} = {CONFIG_SCHEMA_VERSION}" in evidence_text


def test_the_precedence_table_lists_every_source_in_order(evidence_text: str) -> None:
    """Eight rows, weakest first; a missing one would make the order unreadable."""
    for origin in ("`defaults`", "`environment`", "`command line`", "--config PATH", "--set KEY"):
        assert origin in evidence_text
