"""`TELEMETRY_POLICY.md` and the code declare the same metrics, in both directions.

A document restating something the code knows is a second place for it to be
wrong, and `MEMORY.md`'s standing rule is that such a restatement arrives with the
comparison that binds it. This is that comparison.
"""

import re
from pathlib import Path
from typing import Final

from globin.domain.metrics import descriptor_for, metric_names, metrics
from globin.domain.telemetry import HIGH_CARDINALITY_KEY_FRAGMENTS

POLICY: Final[str] = "docs/TELEMETRY_POLICY.md"
"""The document this compares against."""

REGISTER_ROW: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*`(?P<name>globin\.[a-z0-9_.]+)`\s*\|\s*(?P<kind>\w+)\s*\|\s*(?P<unit>\w+)\s*\|"
    r"\s*(?P<attributes>[^|]*)\|\s*$",
    re.MULTILINE,
)
"""A row of the metric register: name, kind, unit, attributes."""


def _rows(repo_root: Path) -> list[re.Match[str]]:
    """Every register row in the policy document.

    Args:
        repo_root: The repository root.

    Returns:
        The matches, in document order.
    """
    return list(REGISTER_ROW.finditer((repo_root / POLICY).read_text(encoding="utf-8")))


def test_the_row_parser_finds_rows(repo_root: Path) -> None:
    """Guard the guard: a parser matching nothing would make every check below pass.

    That is the failure mode a tripwire has, and it is why this exists.
    """
    assert len(_rows(repo_root)) == len(metrics())


def test_the_document_names_every_declared_metric(repo_root: Path) -> None:
    """A metric nobody documented is one nobody can be told not to misuse."""
    documented = [match.group("name") for match in _rows(repo_root)]
    assert tuple(documented) == metric_names()


def test_every_documented_kind_and_unit_is_the_one_declared(repo_root: Path) -> None:
    """The two halves of a metric's meaning, compared rather than trusted."""
    for match in _rows(repo_root):
        descriptor = descriptor_for(match.group("name"))
        assert match.group("kind") == descriptor.kind.value, descriptor.name
        assert match.group("unit") == descriptor.unit.value, descriptor.name


def test_every_documented_attribute_is_one_the_metric_declares(repo_root: Path) -> None:
    """An attribute in the document and not in the code is a label nobody may set."""
    for match in _rows(repo_root):
        descriptor = descriptor_for(match.group("name"))
        cell = match.group("attributes").strip()
        documented = (
            () if cell in {"", "—"} else tuple(sorted(part.strip(" `") for part in cell.split(",")))
        )
        assert documented == tuple(sorted(descriptor.keys())), descriptor.name


def test_the_document_lists_every_unbounded_fragment(repo_root: Path) -> None:
    """The denylist a reader is told about must be the one that runs.

    A fragment enforced by the code and absent from the document is a refusal
    nobody could have predicted; one in the document and not the code is a promise
    nothing keeps.
    """
    text = (repo_root / POLICY).read_text(encoding="utf-8")
    for fragment in HIGH_CARDINALITY_KEY_FRAGMENTS:
        assert f"`{fragment}`" in text, fragment


def test_the_document_defers_only_to_phases_that_have_not_shipped(repo_root: Path) -> None:
    """Its own "what this does not cover" table, held to the same rule as the rest.

    `test_documentation_contract.py` parametrizes over a hand-written list of
    documents, and a new policy silently escaping that list is the failure this
    guards until somebody adds it there.
    """
    text = (repo_root / POLICY).read_text(encoding="utf-8")
    section = text.split("## What this does not cover", 1)[1]
    phases = [int(number) for number in re.findall(r"\|\s*(\d{3})\s*(?:onwards\s*)?\|", section)]
    assert phases
    assert all(phase > 26 for phase in phases), phases
