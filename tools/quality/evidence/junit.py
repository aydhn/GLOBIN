"""Reading pytest's JUnit XML back into counts and timings.

Pure: takes text, returns values. Nothing here opens a file or starts a process,
which is what lets the whole module be tested from literals — the same split
``tools/quality/execution`` and ``tools/quality/mutation`` both make.

**Why parse a file pytest already summarised on the terminal.** Because the
terminal summary is for a person watching, and this is for a machine reading six
months later. The XML carries per-test outcomes and durations in a documented
schema, so "which tests were slow in the run that failed" is answerable without
anybody having thought to capture it at the time.

**The parser is deliberately narrow.** It reads the ``testsuite`` element's
attributes and each ``testcase``'s name and time, and it ignores everything else.
A wider parser would be a second implementation of a schema pytest owns, and the
only thing this needs from it is arithmetic.

``xml.etree.ElementTree`` from the standard library, not ``defusedxml``: adding a
dependency is ADR-0032 condition 3, and the input here is a file this repository
produced seconds earlier in the same process tree, not hostile input from a
network. That reasoning is recorded rather than assumed because it is exactly the
sentence that stops being true if this parser is ever pointed at somebody else's
XML.
"""

from dataclasses import dataclass
from typing import Final
from xml.etree import ElementTree

#: The outcome elements JUnit nests inside a `testcase`, and the counter each
#: increments. A `testcase` with none of them passed.
OUTCOME_ELEMENTS: Final[tuple[str, ...]] = ("failure", "error", "skipped")


class EvidenceError(Exception):
    """Evidence could not be read, parsed or trusted.

    Local to this package rather than a :mod:`globin.errors` type, for the reason
    ``tools/quality/execution`` gives: a verifier that imports the package it
    verifies cannot report on one too broken to import.
    """


@dataclass(frozen=True, slots=True)
class Outcome:
    """How many tests ended each way, and how long they took.

    Args:
        collected: How many test cases the report describes.
        passed: How many recorded no failure, error or skip.
        failed: How many carried a ``failure`` element.
        errors: How many carried an ``error`` element.
        skipped: How many were skipped, including expected failures.
        duration_seconds: The suite's own reported total.
    """

    collected: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class TestDuration:
    """One test and what it cost.

    Args:
        node_id: The test's identity, rebuilt from the report's ``classname``
            and ``name`` attributes.
        seconds: Setup, call and teardown together — see the
            ``junit_duration_report`` comment in ``pyproject.toml``.
    """

    node_id: str
    seconds: float


def parse(text: str) -> tuple[Outcome, tuple[TestDuration, ...]]:
    """Read a JUnit XML report.

    Args:
        text: The whole document.

    Returns:
        The outcome counts, and every test's duration in the order the report
        lists them.

    Raises:
        EvidenceError: If the text is not well-formed XML, or carries no
            ``testsuite`` element.

    The counts are recomputed from the ``testcase`` elements rather than read
    from the ``testsuite`` attributes, so that a report whose header disagrees
    with its body is caught rather than believed. Only the duration is taken
    from the header, because it is the one figure the body cannot reproduce: a
    suite total includes time no individual test is charged for.
    """
    try:
        root = ElementTree.fromstring(text)  # noqa: S314 — see the module docstring
    except ElementTree.ParseError as fault:
        msg = f"the JUnit report is not well-formed XML: {fault}"
        raise EvidenceError(msg) from fault

    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        msg = (
            f"no <testsuite> element found in the JUnit report; the root is "
            f"<{root.tag}> and the report may not have come from pytest"
        )
        raise EvidenceError(msg)

    cases = suite.findall(".//testcase")
    counts = dict.fromkeys(OUTCOME_ELEMENTS, 0)
    durations: list[TestDuration] = []
    for case in cases:
        for name in OUTCOME_ELEMENTS:
            if case.find(name) is not None:
                counts[name] += 1
        durations.append(TestDuration(node_id=_node_id(case), seconds=_seconds(case.get("time"))))

    ended = sum(counts.values())
    outcome = Outcome(
        collected=len(cases),
        passed=len(cases) - ended,
        failed=counts["failure"],
        errors=counts["error"],
        skipped=counts["skipped"],
        duration_seconds=_seconds(suite.get("time")),
    )
    return outcome, tuple(durations)


def slowest(durations: tuple[TestDuration, ...], *, limit: int) -> tuple[TestDuration, ...]:
    """The tests that cost the most, in a deterministic order.

    Args:
        durations: Every test's duration.
        limit: How many to return. A limit at or below zero returns nothing.

    Returns:
        The slowest tests, longest first, ties broken by node ID.

    The tie-break is what makes this deterministic. Sorting on duration alone
    leaves two tests that took the same measured time in whatever order the
    report happened to list them, and a manifest that reorders between runs
    cannot be compared.
    """
    if limit <= 0:
        return ()
    ordered = sorted(durations, key=lambda item: (-item.seconds, item.node_id))
    return tuple(ordered[:limit])


def _node_id(case: ElementTree.Element) -> str:
    """Rebuild a test's identity from a ``testcase`` element.

    Args:
        case: The element.

    Returns:
        ``module::test`` where a classname is present, and the bare name
        otherwise. Not necessarily pytest's own node ID — a parametrised test's
        brackets survive, but the path separator does not — which is why this is
        used for reporting and never for the digest.
    """
    name = case.get("name", "")
    classname = case.get("classname", "")
    return f"{classname}::{name}" if classname else name


def _seconds(value: str | None) -> float:
    """Read a duration attribute, treating an unusable one as zero.

    Args:
        value: The attribute's text, or ``None`` when it is absent.

    Returns:
        The duration in seconds.

    A missing or malformed time is reported as zero rather than raising. The
    duration is diagnostic; refusing a whole report because one element lost its
    ``time`` attribute would discard the outcome counts, which are the part that
    decides whether the gate passed.
    """
    try:
        return float(value) if value is not None else 0.0
    except ValueError:
        return 0.0
