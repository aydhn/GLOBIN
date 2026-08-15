"""Accepting a vulnerability, and the rules that stop an acceptance becoming permanent.

Every refusal here is fail-closed: a malformed register stops the gate rather
than being read past. That direction matters. A dropped waiver becomes an
un-waived finding, which fails loudly; a dropped *field* would become a waiver
that never expires, which fails never.
"""

from datetime import date
from pathlib import Path

import pytest

from tools.quality.supply import waivers
from tools.quality.supply.inventory import SupplyChainError

COMPLETE = """\
schema = 1

[[waiver]]
vulnerability = "GHSA-aaaa-bbbb-cccc"
package = "example"
ecosystem = "pypi"
affected = "==1.2.3"
reason = "No code path in GLOBIN reaches the affected parser."
owner = "aydhn"
created = 2026-08-15
expires = 2026-11-15
compensating_control = "The dependency is development-only and never runs in CI."
reference = "https://github.com/advisories/GHSA-aaaa-bbbb-cccc"
"""


def _register(root: Path, text: str) -> Path:
    """Write a waiver register where :func:`waivers.load` will find it.

    Args:
        root: A temporary repository root.
        text: The file's contents.

    Returns:
        The root, for chaining.
    """
    path = root / waivers.WAIVERS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return root


def test_a_complete_waiver_is_read(tmp_path: Path) -> None:
    """The shape the policy requires, so the negatives below mean something."""
    (entry,) = waivers.load(_register(tmp_path, COMPLETE))
    assert entry.vulnerability == "GHSA-aaaa-bbbb-cccc"
    assert entry.owner == "aydhn"
    assert entry.expires == date(2026, 11, 15)


def test_an_absent_register_is_not_an_error(tmp_path: Path) -> None:
    """A repository with nothing waived is the normal case and needs no file to say so."""
    assert waivers.load(tmp_path) == ()


@pytest.mark.parametrize("field", sorted(waivers.REQUIRED_FIELDS))
def test_every_field_is_required(tmp_path: Path, field: str) -> None:
    """Ten fields, deliberately more than is convenient.

    A waiver is a decision to run with a known defect, and the cost of recording
    one should be high enough that it is worth doing properly.
    """
    without = "\n".join(line for line in COMPLETE.splitlines() if not line.startswith(f"{field} "))
    with pytest.raises(SupplyChainError, match=field):
        waivers.load(_register(tmp_path, without))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param('"*"', "every version", id="star"),
        pytest.param('"any"', "every version", id="any"),
        pytest.param('"ALL"', "every version", id="all, shouted"),
        pytest.param('"  *  "', "every version", id="star with whitespace"),
        pytest.param('""', "omits affected", id="empty"),
    ],
)
def test_a_waiver_covering_every_version_is_refused(
    tmp_path: Path, value: str, expected: str
) -> None:
    """``affected = "*"`` waives a package's entire future.

    Including the vulnerability nobody has published yet, which is not a decision
    anybody is in a position to make. An empty string is caught one step earlier,
    by the required-field check, and the two messages are asserted separately so
    that neither silently starts doing the other's job.
    """
    text = COMPLETE.replace('affected = "==1.2.3"', f"affected = {value}")
    with pytest.raises(SupplyChainError, match=expected):
        waivers.load(_register(tmp_path, text))


def test_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    """Refused rather than read, exactly as ``docs/SERIALIZATION_POLICY.md`` requires."""
    with pytest.raises(SupplyChainError, match="implements 1"):
        waivers.load(_register(tmp_path, COMPLETE.replace("schema = 1", "schema = 2")))


def test_a_quoted_date_is_refused(tmp_path: Path) -> None:
    """A quoted date is a string that looks like one.

    The difference is invisible until something compares two of them and gets the
    wrong answer, which for an expiry check is the wrong answer that matters.
    """
    text = COMPLETE.replace("expires = 2026-11-15", 'expires = "2026-11-15"')
    with pytest.raises(SupplyChainError, match="bare TOML date"):
        waivers.load(_register(tmp_path, text))


def test_a_waiver_that_expires_before_it_was_created_is_refused(tmp_path: Path) -> None:
    """Nonsense, and the kind a typo in a year produces."""
    text = COMPLETE.replace("expires = 2026-11-15", "expires = 2025-11-15")
    with pytest.raises(SupplyChainError, match=r"expires .* before it was created"):
        waivers.load(_register(tmp_path, text))


def test_malformed_toml_is_refused(tmp_path: Path) -> None:
    """An unreadable register produces an error, never an empty one.

    An empty register is indistinguishable from a repository with nothing waived,
    and would be reported as clean.
    """
    with pytest.raises(SupplyChainError, match="not valid TOML"):
        waivers.load(_register(tmp_path, "schema = 1\n[[waiver]\n"))


@pytest.mark.parametrize(
    ("today", "expired"),
    [
        pytest.param(date(2026, 11, 14), False, id="the day before"),
        pytest.param(date(2026, 11, 15), False, id="the expiry day itself"),
        pytest.param(date(2026, 11, 16), True, id="the day after"),
    ],
)
def test_expiry_is_inclusive_of_its_own_date(tmp_path: Path, today: date, expired: bool) -> None:
    """A date range written by a human reads as inclusive.

    A gate that disagreed would surprise somebody exactly once, on the day their
    waiver stopped working a day early.
    """
    register = waivers.load(_register(tmp_path, COMPLETE))
    assert bool(waivers.expired(register, on=today)) is expired


def test_a_waiver_marks_a_finding_rather_than_removing_it(tmp_path: Path) -> None:
    """The disposition changes; the finding survives.

    The point of a register is to be able to read later what was accepted and by
    whom, which is impossible if accepting something deletes it.
    """
    (entry,) = waivers.load(_register(tmp_path, COMPLETE))
    assert entry.covers("GHSA-aaaa-bbbb-cccc", "example")
    assert entry.covers("GHSA-aaaa-bbbb-cccc", "EXAMPLE"), "index names are case-insensitive"
    assert not entry.covers("GHSA-aaaa-bbbb-cccc", "different")
    assert not entry.covers("CVE-2026-0001", "example")
