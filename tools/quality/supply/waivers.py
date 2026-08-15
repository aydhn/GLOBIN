"""Accepting a known vulnerability, for a stated reason, until a stated date.

A gate with no way to say "yes, and we are accepting that" is a gate somebody
eventually switches off. A gate whose exceptions never expire is a gate that
becomes a list of things nobody has looked at since. This module is the middle:
every waiver names an owner, a reason, a compensating control and a date after
which it stops working.

**Expiry is measured against the commit, not the clock.** The question a waiver
answers is "was this acceptable for the tree being judged", and the tree has a
date of its own. Reading the wall clock would also make the manifest
non-deterministic, which
[ADR-0040](../../../docs/adr/0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md)
rules out for evidence. Using the commit date means the same commit gets the same
verdict on any machine on any day — and since a commit under test is by
definition recent, an expired waiver is still caught the moment it expires.

**A waiver hides nothing.** It changes a finding's disposition from ``open`` to
``waived``; it does not remove it from the report or from the count. The whole
point is to be able to read, later, what was accepted and by whom.

**No wildcards.** ``affected = "*"`` would waive a package's entire future,
including the vulnerability nobody has published yet. The affected range must be
written out, and :func:`load` refuses the file if one is not.
"""

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

from tools.quality.supply.inventory import SupplyChainError

WAIVERS: Final[str] = "docs/engineering/vulnerability-waivers.toml"

SCHEMA: Final[int] = 1
"""Bumped when the shape of a waiver changes, and refused when unknown — the
same contract ``docs/SERIALIZATION_POLICY.md`` states for every other document
this repository reads back."""

REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "vulnerability",
    "package",
    "ecosystem",
    "affected",
    "reason",
    "owner",
    "created",
    "expires",
    "compensating_control",
    "reference",
)
"""Every field a waiver must carry.

Ten of them, which is deliberately more than is convenient. A waiver is a
decision to run with a known defect, and the cost of recording one should be
high enough that it is worth doing properly. ``compensating_control`` is the
field people most want to omit and the one most worth demanding: a waiver with
no answer to "so what stops this hurting us" is not a decision, it is a shrug.
"""

FORBIDDEN_RANGES: Final[frozenset[str]] = frozenset({"*", "", "any", "all"})
"""Spellings of "everything", refused so that a waiver cannot outlive its subject."""

OPEN: Final[str] = "open"
WAIVED: Final[str] = "waived"
"""A finding's disposition. Never ``resolved``: this module does not fix anything."""


@dataclass(frozen=True, slots=True)
class Waiver:
    """One accepted vulnerability.

    Args:
        vulnerability: The advisory identifier, such as a GHSA or CVE.
        package: The distribution the advisory is about.
        ecosystem: Which ecosystem that name belongs to.
        affected: The exact version or explicit range being waived.
        reason: Why running with it is acceptable.
        owner: Who decided. A person, so the decision has an address.
        created: When it was decided.
        expires: When it stops working, whatever anybody thinks then.
        compensating_control: What reduces the risk in the meantime.
        reference: Where to read more.
    """

    vulnerability: str
    package: str
    ecosystem: str
    affected: str
    reason: str
    owner: str
    created: date
    expires: date
    compensating_control: str
    reference: str

    def covers(self, vulnerability: str, package: str) -> bool:
        """Whether this waiver is about a given finding.

        Args:
            vulnerability: The advisory identifier the audit reported.
            package: The distribution the audit reported it against.

        Returns:
            ``True`` when both match, case-insensitively on the package name
            because index names are case-insensitive and advisory identifiers
            are not.
        """
        return self.vulnerability == vulnerability and self.package.lower() == package.lower()

    def expired(self, on: date) -> bool:
        """Whether this waiver has run out.

        Args:
            on: The date being judged — the commit's, not today's.

        Returns:
            ``True`` on the day after :attr:`expires`. The expiry date itself is
            still covered, because a date range written by a human reads as
            inclusive and a gate that disagreed would surprise them once.
        """
        return on > self.expires


def load(repo_root: Path) -> tuple[Waiver, ...]:
    """Read the waiver register, refusing anything malformed.

    Args:
        repo_root: The repository root.

    Returns:
        Every waiver, in file order. An absent file is not an error and yields
        none: a repository with nothing waived is the normal case and should not
        need a file to say so.

    Raises:
        SupplyChainError: If the file is not valid TOML, declares a schema
            version this reader does not implement, omits a required field, or
            waives an unbounded range.

    Fail-closed throughout. Every refusal here stops the gate rather than
    dropping the offending entry, because a dropped waiver silently becomes an
    un-waived finding — which fails loudly — while a dropped *field* would
    silently become a waiver that never expires.
    """
    path = repo_root / WAIVERS
    if not path.is_file():
        return ()

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as fault:
        msg = f"{WAIVERS} is not valid TOML: {fault}"
        raise SupplyChainError(msg) from fault

    declared = document.get("schema")
    if declared != SCHEMA:
        msg = (
            f"{WAIVERS} declares schema {declared!r}; this reader implements "
            f"{SCHEMA} and will not guess at another"
        )
        raise SupplyChainError(msg)

    return tuple(_waiver(entry, index) for index, entry in enumerate(document.get("waiver", [])))


def _waiver(entry: object, index: int) -> Waiver:
    """Turn one table into a waiver, or refuse it.

    Args:
        entry: The parsed ``[[waiver]]`` table.
        index: Its position, used to name it in an error before its identifier
            is known to be present.

    Returns:
        The waiver.

    Raises:
        SupplyChainError: If a field is missing, empty, or waives everything.
    """
    where = f"{WAIVERS} waiver #{index + 1}"
    if not isinstance(entry, dict):
        msg = f"{where} is {type(entry).__name__}, not a table"
        raise SupplyChainError(msg)

    missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
    if missing:
        msg = f"{where} omits {', '.join(missing)}; every field is required"
        raise SupplyChainError(msg)

    affected = str(entry["affected"]).strip()
    if affected.lower() in FORBIDDEN_RANGES:
        msg = (
            f"{where} waives {affected!r}, which is every version there will ever "
            f"be. Write the affected range out"
        )
        raise SupplyChainError(msg)

    created = _date(entry["created"], where, "created")
    expires = _date(entry["expires"], where, "expires")
    if expires < created:
        msg = f"{where} expires ({expires}) before it was created ({created})"
        raise SupplyChainError(msg)

    return Waiver(
        vulnerability=str(entry["vulnerability"]),
        package=str(entry["package"]),
        ecosystem=str(entry["ecosystem"]),
        affected=affected,
        reason=str(entry["reason"]),
        owner=str(entry["owner"]),
        created=created,
        expires=expires,
        compensating_control=str(entry["compensating_control"]),
        reference=str(entry["reference"]),
    )


def _date(value: object, where: str, field: str) -> date:
    """Read a date, accepting what TOML gives and refusing what it does not.

    Args:
        value: Whatever the parser produced. TOML has a native date type, so a
            bare ``2026-11-15`` arrives already parsed.
        where: The waiver being read, for the error message.
        field: Which field, for the same reason.

    Returns:
        The date.

    Raises:
        SupplyChainError: If the value is a quoted string or anything else. The
            refusal is deliberate: a quoted date is a string that looks like a
            date, and the difference is invisible until something compares two of
            them and gets the wrong answer.
    """
    if isinstance(value, date):
        return value
    msg = (
        f"{where} writes {field} as {value!r}. Write it as a bare TOML date "
        f"(2026-11-15), not as a string — a quoted date does not compare as one"
    )
    raise SupplyChainError(msg)


def expired(waivers: tuple[Waiver, ...], *, on: date) -> tuple[Waiver, ...]:
    """Every waiver that has run out.

    Args:
        waivers: The register.
        on: The date being judged.

    Returns:
        The expired ones. A non-empty result fails the gate — that is the whole
        mechanism by which a waiver is temporary rather than permanent.
    """
    return tuple(waiver for waiver in waivers if waiver.expired(on))
