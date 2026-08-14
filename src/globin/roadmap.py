"""The fixed structure of the GLOBIN 320-phase roadmap.

``ROADMAP.md`` is the human-readable roadmap. This module is the machine-
readable statement of its *skeleton* — the twenty immutable sixteen-phase
bands defined by the project charter.

Encoding the bands in code rather than parsing them out of prose is what makes
``tests/contract/test_roadmap_contract.py`` a meaningful test instead of a snapshot. The
test checks ``ROADMAP.md`` **against this module**, so the document and the
contract cannot drift apart silently: editing one without the other fails the
suite.

Only the band skeleton lives here. The 320 individual phase titles live in
``ROADMAP.md`` alone — duplicating 320 strings in two places would create
exactly the drift this design is meant to prevent.
"""

from dataclasses import dataclass
from typing import Final

from globin.project_contract import ROADMAP_TOTAL_PHASES

PHASE_BAND_WIDTH: Final[int] = 16
"""Every band spans exactly this many phases. Asserted by the contract tests."""


@dataclass(frozen=True, slots=True)
class PhaseBand:
    """A contiguous, immutable band of roadmap phases.

    Args:
        start: First phase number in the band (inclusive, 1-based).
        end: Last phase number in the band (inclusive).
        title: Short name for the band's theme.
    """

    start: int
    end: int
    title: str

    @property
    def width(self) -> int:
        """Number of phases in this band."""
        return self.end - self.start + 1

    def contains(self, phase: int) -> bool:
        """Return whether ``phase`` falls inside this band."""
        return self.start <= phase <= self.end


PHASE_BANDS: Final[tuple[PhaseBand, ...]] = (
    PhaseBand(1, 16, "Repository Foundation and Engineering Contract"),
    PhaseBand(17, 32, "Windows Environment, Dependencies and Bootstrap"),
    PhaseBand(33, 48, "Binance API Reality Map and Capability Matrix"),
    PhaseBand(49, 64, "Market Data Acquisition and Instrument Registry"),
    PhaseBand(65, 80, "Account and Product Adapters"),
    PhaseBand(81, 96, "Order Lifecycle and Execution Engine"),
    PhaseBand(97, 112, "Point-in-Time Data Platform"),
    PhaseBand(113, 128, "Technical Analysis and Feature Factory"),
    PhaseBand(129, 144, "Strategy Registry and Signal Composition"),
    PhaseBand(145, 160, "Event-Driven Backtesting and Benchmarking"),
    PhaseBand(161, 176, "Research Validation and Leakage Control"),
    PhaseBand(177, 192, "Supervised Machine Learning"),
    PhaseBand(193, 208, "Reinforcement Learning"),
    PhaseBand(209, 224, "Optimization and Parameter Governance"),
    PhaseBand(225, 240, "Continual and Autonomous Learning"),
    PhaseBand(241, 256, "Portfolio and Risk Management"),
    PhaseBand(257, 272, "Autonomous Orchestration"),
    PhaseBand(273, 288, "Telegram Interface and Operations"),
    PhaseBand(289, 304, "Windows Launchers and System Integration"),
    PhaseBand(305, 320, "Live Readiness and Staged Activation"),
)
"""The twenty immutable phase bands. Ranges are fixed by the project charter."""


def band_for_phase(phase: int) -> PhaseBand:
    """Return the band containing ``phase``.

    Args:
        phase: A 1-based phase number.

    Returns:
        The :class:`PhaseBand` containing ``phase``.

    Raises:
        ValueError: If ``phase`` is outside 1..``ROADMAP_TOTAL_PHASES``.
    """
    for band in PHASE_BANDS:
        if band.contains(phase):
            return band
    msg = f"phase must be in 1..{ROADMAP_TOTAL_PHASES}, got {phase}"
    raise ValueError(msg)
