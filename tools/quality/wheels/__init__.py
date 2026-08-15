"""Whether the libraries this programme schedules can actually run on the pinned interpreter.

Phase 017 declared a CPython minor line and built an environment from it. It did
that **before** anything checked that the planned stack publishes wheels for that
line, which is the order ``ROADMAP.md`` stated, reversed. ADR-0051 recorded the
inversion rather than glossing it, and said plainly what follows: if the survey
finds the planned stack cannot run on the pinned line, the contract Phase 017 wrote
is what changes.

This package is that survey, made repeatable.

**A declaration, not a snapshot.** ``docs/engineering/wheel-survey.toml`` is what a
person read and wrote down — one entry per library the roadmap or its Phase 001
source ledger names, carrying the version, the published ``Requires-Python``, and
the wheel filenames the index actually offers. Nothing generates it, for the reason
``action-pins.toml`` gives about itself: a file generated from the index could only
ever agree with the index, which is a mirror rather than a check.

**The verdict is recomputed, not trusted.** Because the filenames are recorded, the
gate can parse their PEP 425 tags offline and decide for itself whether any of them
serves the pinned interpreter. An entry claiming a wheel exists whose own evidence
does not support it fails without asking anything. ``probe`` closes the other
direction by asking the index whether the record is still true.

**A gap is recorded and owned, not treated as a failure.** The roadmap asks this
phase to record each gap rather than assume one, and a library whose upstream
publishes no wheel is not something a gate fixes by going red. What fails is an
*unowned* gap — recorded, then nobody's, then forgotten.

**One answer this package owes elsewhere.** ADR-0050 refused free-threaded builds
because Phase 018 had not yet surveyed whether the stack publishes for them. The
gate computes that second verdict from the same evidence and reports which
libraries would block the change, without failing on it: a gap there is the
refusal being correct.

**What this does not decide.** Which of these libraries GLOBIN adopts, in what
version, under whose review — that is ``docs/DEPENDENCY_POLICY.md`` and Phase 021
onwards, one written record at a time. Resolution and locking are Phase 020's.
Whether a wheel that exists also *works* on this host is a measurement, and
Phases 022-025 make it.
"""

from tools.quality.wheels.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    run_wheels,
)
from tools.quality.wheels.manifest import REASONS, SCHEMA, SCHEMA_VERSION
from tools.quality.wheels.plan import (
    Declaration,
    Library,
    Target,
    Wheel,
    WheelSurveyError,
    parse_wheel_filename,
    satisfies,
)

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "REASONS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Declaration",
    "Library",
    "Target",
    "Wheel",
    "WheelSurveyError",
    "parse_wheel_filename",
    "run_wheels",
    "satisfies",
]
