"""Reading coverage.py's JSON report back into a summary.

Pure: takes text, returns values.

**Nothing here computes coverage.** coverage.py is the source of truth for its
own numbers, and a second implementation would eventually disagree with the tool
whose verdict actually gates the build. This reads what it published.

**The subtlety worth writing down.** With ``branch = true`` set — which
``pyproject.toml`` does — ``totals.percent_covered`` is *already* the combined
line-and-branch figure, and it is what ``fail_under`` compares against. So the
manifest records that number as the gate figure and carries the branch counts
beside it as detail. Deriving a second percentage from the branch counts would
produce a number that looks like coverage, is not the one the gate used, and
would be quoted by somebody as though it were.

Named ``coverage_report`` rather than ``coverage`` so that nothing in this
package shadows the distribution it reads, for a reader. Imports are absolute, so
the shadowing would not actually occur; the confusion would.
"""

import json
from dataclasses import dataclass
from typing import Final

from tools.quality.evidence.junit import EvidenceError

#: Keys `coverage json` always writes under `totals`, whatever the settings.
REQUIRED_TOTALS: Final[tuple[str, ...]] = (
    "covered_lines",
    "num_statements",
    "percent_covered",
)

#: Keys it adds only when branch coverage is enabled. Their absence is a
#: configuration answer, not a parse failure.
BRANCH_TOTALS: Final[tuple[str, ...]] = ("num_branches", "covered_branches")


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    """What coverage.py measured.

    Args:
        percent_covered: The figure the threshold is compared against. With
            branch coverage on, this already accounts for branches.
        covered_lines: Statements executed.
        num_statements: Statements measured.
        num_branches: Branches measured, or ``None`` when branch coverage was
            off.
        covered_branches: Branches taken, or ``None`` for the same reason.
        branch_enabled: Whether the report carried branch figures at all.
    """

    percent_covered: float
    covered_lines: int
    num_statements: int
    num_branches: int | None
    covered_branches: int | None
    branch_enabled: bool


def parse(text: str) -> CoverageSummary:
    """Read a ``coverage json`` report.

    Args:
        text: The whole document.

    Returns:
        The totals.

    Raises:
        EvidenceError: If the text is not JSON, is not an object, carries no
            ``totals`` object, or omits a key coverage.py always writes.

    A missing required key is refused rather than defaulted to zero. Zero
    coverage and unmeasured coverage are different situations, and the whole
    point of ``QUALITY_GATES.md``'s "there is no fourth state" is that the second
    must never be reported as though it were a number.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the coverage report is not valid JSON: {fault}"
        raise EvidenceError(msg) from fault

    if not isinstance(document, dict):
        msg = f"a coverage report must be a JSON object, found {type(document).__name__}"
        raise EvidenceError(msg)

    totals = document.get("totals")
    if not isinstance(totals, dict):
        msg = "the coverage report carries no 'totals' object, so nothing can be read from it"
        raise EvidenceError(msg)

    missing = [key for key in REQUIRED_TOTALS if key not in totals]
    if missing:
        msg = (
            f"the coverage report's totals omit {missing}; coverage.py always writes "
            f"these, so the file is truncated or was not produced by `coverage json`"
        )
        raise EvidenceError(msg)

    branch_enabled = all(key in totals for key in BRANCH_TOTALS)
    return CoverageSummary(
        percent_covered=float(totals["percent_covered"]),
        covered_lines=int(totals["covered_lines"]),
        num_statements=int(totals["num_statements"]),
        num_branches=int(totals["num_branches"]) if branch_enabled else None,
        covered_branches=int(totals["covered_branches"]) if branch_enabled else None,
        branch_enabled=branch_enabled,
    )
