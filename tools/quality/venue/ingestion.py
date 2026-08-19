"""The cadence, the change journal and the acknowledgement ledger, read by the gate.

Phase 033 gave the venue gate a refresh and a classified diff. What it deliberately
did not give it, and what ``scope-amendments.toml`` recorded as absent by design,
was *a cadence*, *an accumulated change log across runs*, and *a review workflow for
a breaking drift*. This module is all three.

**A second reader, and that is the point.** ``src/globin/adapters/ingestion.py``
parses the same policy document and shares no code with this one, so the two can be
compared rather than assumed to agree —
``tests/contract/test_ingestion_contract.py`` does the comparing. The package reads
``[default]`` and ``[cadence]``, because staleness is what the transport fails
closed on; this reads ``[review]`` as well, because acknowledging a change is a
repository act rather than a runtime one.

**Ageing does not fail this gate.** A stale source is recorded and reported, and it
refuses a REST resolution inside GLOBIN. It does not turn the repository red,
because a gate that goes red on a calendar — on a machine that may have no network
to clear it with — is a gate people learn to re-run rather than read. What *does*
fail is an unacknowledged change: somebody has to write down what a moved document
means before the gate goes green again.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from tools.quality.venue.plan import Source

POLICY_PATH: Final[str] = "docs/engineering/ingestion-policy.toml"
"""Where the declared cadence lives, relative to the repository root."""

ACKNOWLEDGEMENTS_PATH: Final[str] = "docs/engineering/venue-acknowledgements.toml"
"""Where a person writes down what a changed document meant."""

JOURNAL_NAME: Final[str] = "venue-journal.jsonl"
"""The accumulated change log, one JSON object per line, appended never rewritten."""

REASON_SOURCE_STALE: Final[str] = "API_REALITY_SOURCE_STALE"
"""A source is past the re-check interval its regime declares.

Reported, never failing. See this module's docstring.
"""

REASON_DRIFT_UNACKNOWLEDGED: Final[str] = "API_REALITY_DRIFT_UNACKNOWLEDGED"
"""A finding the policy says needs a written acknowledgement does not have one."""

REASON_ACKNOWLEDGEMENT_STALE: Final[str] = "API_REALITY_ACKNOWLEDGEMENT_STALE"
"""An acknowledgement names a finding that no longer occurs.

The other direction, and the one that keeps the ledger honest. An acknowledgement
that outlived its finding is a standing permission nobody re-examined — the same
failure ``test_the_named_reader_still_reads_it`` guards against elsewhere, and the
same bargain ``wheel-survey.toml`` strikes: an owned gap is fine until the gap
closes, and then the record must go.
"""


class PolicyError(Exception):
    """The cadence or the acknowledgement ledger is unreadable or contradicts itself."""


@dataclass(frozen=True, slots=True)
class Cadence:
    """How often one regime of source must be re-read."""

    regime: str
    recheck_days: int


@dataclass(frozen=True, slots=True)
class Policy:
    """The declared cadence, and which findings need a written acknowledgement."""

    rules: tuple[Cadence, ...]
    default_days: int
    acknowledged_reasons: tuple[str, ...]

    def days_for(self, regime: str) -> int:
        """How long a source of one regime may go un-re-read.

        Args:
            regime: The regime's spelling.

        Returns:
            The declared interval, or the default when no rule names the regime.
        """
        return next(
            (item.recheck_days for item in self.rules if item.regime == regime),
            self.default_days,
        )


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """One written decision about a finding somebody looked at."""

    finding: str
    subject: str
    phase: int
    decided_on: str
    note: str

    @property
    def identity(self) -> tuple[str, str]:
        """What this acknowledgement covers."""
        return (self.finding, self.subject)


@dataclass(frozen=True, slots=True)
class SourceAge:
    """One source, how old its record is, and whether that is still acceptable."""

    identifier: str
    regime: str
    accessed: str
    age_days: int
    allowed_days: int
    stale: bool

    def as_record(self) -> dict[str, object]:
        """This age as plain JSON-safe values."""
        return {
            "identifier": self.identifier,
            "regime": self.regime,
            "accessed": self.accessed,
            "age_days": self.age_days,
            "allowed_days": self.allowed_days,
            "stale": self.stale,
        }


def read_policy(root: Path) -> Policy | None:
    """The declared cadence, or nothing.

    Args:
        root: The repository root.

    Returns:
        The policy, or ``None`` when the document is absent.

    Raises:
        PolicyError: If the document is present and malformed.
    """
    path = root / POLICY_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        document = tomllib.loads(text)
    except (ValueError, TypeError) as fault:
        msg = f"{POLICY_PATH} is not valid TOML: {fault}"
        raise PolicyError(msg) from fault
    default = document.get("default")
    review = document.get("review")
    if not isinstance(default, dict) or not isinstance(review, dict):
        msg = f"{POLICY_PATH} declares no [default] or no [review] table"
        raise PolicyError(msg)
    rows = document.get("cadence", [])
    if not isinstance(rows, list):
        msg = f"'cadence' in {POLICY_PATH} is not an array of tables"
        raise PolicyError(msg)
    rules: list[Cadence] = []
    for row in rows:
        if not isinstance(row, dict):
            msg = f"a 'cadence' entry in {POLICY_PATH} is not a table"
            raise PolicyError(msg)
        regime = row.get("regime")
        days = row.get("recheck_days")
        if not isinstance(regime, str) or not isinstance(days, int) or isinstance(days, bool):
            msg = f"a 'cadence' entry in {POLICY_PATH} is missing a regime or an interval"
            raise PolicyError(msg)
        rules.append(Cadence(regime=regime, recheck_days=days))
    fallback = default.get("recheck_days")
    reasons = review.get("acknowledged_reasons")
    if not isinstance(fallback, int) or isinstance(fallback, bool):
        msg = f"{POLICY_PATH} declares no default re-check interval"
        raise PolicyError(msg)
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        msg = (
            f"{POLICY_PATH} declares no acknowledged_reasons list. An empty list is a "
            "policy saying no finding needs a written decision, and is legitimate; a "
            "missing key is a typo, and defaulting it would turn one into permission."
        )
        raise PolicyError(msg)
    return Policy(
        rules=tuple(rules),
        default_days=fallback,
        acknowledged_reasons=tuple(str(item) for item in reasons),
    )


def read_acknowledgements(root: Path) -> tuple[Acknowledgement, ...]:
    """Every written decision, or none.

    Args:
        root: The repository root.

    Returns:
        The acknowledgements. An absent ledger is an empty one — which fails
        anything that needed acknowledging, rather than passing it.

    Raises:
        PolicyError: If the ledger is present and malformed.
    """
    path = root / ACKNOWLEDGEMENTS_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    try:
        document = tomllib.loads(text)
    except (ValueError, TypeError) as fault:
        msg = f"{ACKNOWLEDGEMENTS_PATH} is not valid TOML: {fault}"
        raise PolicyError(msg) from fault
    rows = document.get("acknowledgement", [])
    if not isinstance(rows, list):
        msg = f"'acknowledgement' in {ACKNOWLEDGEMENTS_PATH} is not an array of tables"
        raise PolicyError(msg)
    found: list[Acknowledgement] = []
    for row in rows:
        if not isinstance(row, dict):
            msg = f"an 'acknowledgement' entry in {ACKNOWLEDGEMENTS_PATH} is not a table"
            raise PolicyError(msg)
        try:
            found.append(
                Acknowledgement(
                    finding=str(row["finding"]),
                    subject=str(row["subject"]),
                    phase=int(row["phase"]),
                    decided_on=str(row["decided_on"]),
                    note=str(row["note"]),
                )
            )
        except (KeyError, TypeError, ValueError) as fault:
            msg = f"an 'acknowledgement' entry in {ACKNOWLEDGEMENTS_PATH} is incomplete: {fault}"
            raise PolicyError(msg) from fault
    return tuple(found)


def ages(sources: Iterable[Source], policy: Policy, *, as_of: str) -> tuple[SourceAge, ...]:
    """How old every recorded source is, as of one date.

    Args:
        sources: The declared sources.
        policy: The declared cadence.
        as_of: The date to compare against, as an ISO date.

    Returns:
        One age per source, in identifier order.

    Raises:
        PolicyError: If a date is not an ISO calendar date.

    **Strictly greater than, not greater or equal**, matching
    :func:`globin.domain.ingestion.assess` — a source read exactly
    ``recheck_days`` ago is still fresh and goes stale the following day. The two
    implementations are compared by a contract test, and an off-by-one that made
    them disagree is exactly what that test is for.
    """
    found: list[SourceAge] = []
    for source in sorted(sources, key=lambda item: item.identifier):
        allowed = policy.days_for(source.regime)
        try:
            days = (date.fromisoformat(as_of) - date.fromisoformat(source.accessed)).days
        except ValueError as fault:
            msg = (
                f"source {source.identifier!r} carries {source.accessed!r} where an ISO "
                f"date belongs: {fault}"
            )
            raise PolicyError(msg) from fault
        found.append(
            SourceAge(
                identifier=source.identifier,
                regime=source.regime,
                accessed=source.accessed,
                age_days=days,
                allowed_days=allowed,
                stale=days > allowed,
            )
        )
    return tuple(found)


def today() -> str:
    """The current date in UTC, as an ISO date.

    Returns:
        The date.

    In the gate rather than in the ageing function, so that :func:`ages` stays pure
    and a test can ask what the registry looks like in two years.
    """
    return datetime.now(UTC).date().isoformat()


def unacknowledged(
    findings: Sequence[tuple[str, str]], policy: Policy, ledger: Sequence[Acknowledgement]
) -> tuple[tuple[str, str], ...]:
    """Every finding that needs a written decision and does not have one.

    Args:
        findings: The gate's findings, as ``(reason, subject)`` pairs.
        policy: The declared cadence, which names the reasons that need one.
        ledger: The written decisions.

    Returns:
        The pairs, sorted.
    """
    covered = {item.identity for item in ledger}
    return tuple(
        sorted(
            pair
            for pair in findings
            if pair[0] in policy.acknowledged_reasons and pair not in covered
        )
    )


def superseded(
    findings: Sequence[tuple[str, str]], ledger: Sequence[Acknowledgement]
) -> tuple[Acknowledgement, ...]:
    """Every acknowledgement whose finding no longer occurs.

    Args:
        findings: The gate's findings, as ``(reason, subject)`` pairs.
        ledger: The written decisions.

    Returns:
        The acknowledgements, in ledger order.

    Only meaningful on a run that actually looked. A ``check`` run reaches nothing,
    so it produces no source-changed findings and would report every acknowledgement
    as superseded; the caller passes this only after a refresh.
    """
    occurring = set(findings)
    return tuple(item for item in ledger if item.identity not in occurring)


def append_journal(directory: Path, record: dict[str, object]) -> Path:
    """Append one run's findings to the accumulated change log.

    Args:
        directory: Where the log lives.
        record: What this run concluded.

    Returns:
        The path written.

    **Append-only, and a run that found nothing appends nothing.** Two runs over an
    unchanged venue therefore leave the journal byte-identical, which is what makes
    it readable: every line in it is a moment something moved.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / JOURNAL_NAME
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    return target


def read_journal(directory: Path) -> tuple[dict[str, object], ...]:
    """Every recorded run, oldest first.

    Args:
        directory: Where the log lives.

    Returns:
        The records. An absent or empty log is an empty tuple — nothing has moved,
        or nothing has looked.

    Raises:
        PolicyError: If a line is not JSON. A corrupt journal is reported rather
            than skipped: silently dropping a line would lose exactly the record
            somebody is looking for.
    """
    target = directory / JOURNAL_NAME
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return ()
    found: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError as fault:
            msg = f"{JOURNAL_NAME} line {number} is not JSON: {fault}"
            raise PolicyError(msg) from fault
        if not isinstance(parsed, dict):
            msg = f"{JOURNAL_NAME} line {number} is not an object"
            raise PolicyError(msg)
        found.append(parsed)
    return tuple(found)
