"""Whether the installed numerical and dataframe stack computes what GLOBIN assumes.

Phase 021 declared `numpy` and `pandas`, reviewed each, pinned both in
`pylock.toml`, and said in ADR-0055 that it made "no claim about numerical
correctness". Phase 018 established, in ADR-0052, that a published wheel filename
is a claim about **availability** and not about behaviour, and filed "whether each
wheel, once installed, actually works on this host" against Phase 022 by name.

This package is that measurement.

**The obvious implementation is the wrong one.** A check concluding "the stack is
installed" because ``import numpy`` did not raise proves that a file was found,
which the lock already guaranteed. It says nothing about whether ``float64`` on
this host is the type every later phase's arithmetic assumes it is — which is
assumption wearing verification's clothes, and precisely what the roadmap's
"confirming correctness rather than assuming it" refuses.

**Four registers name a version, and the first job is to compare them.**
`pyproject.toml` bounds it, `pylock.toml` pins it, the installed `.dist-info`
records what actually landed, and `docs/engineering/stack-contract.toml` declares
what GLOBIN's assumptions were established against. A fourth register is only
worth adding because something checks all four agree.

**Provenance is read from the artefact, not from the lock.** The digest in the
lock says what *should* have been fetched; the `Tag` in the installed
`.dist-info/WHEEL` says what is actually unpacked. That is what catches a wheel
built for another ABI — a free-threaded build, another minor line, another
architecture — as a wrong artefact rather than as a mysterious failure later.

**A probe defends a written assumption, or it does not belong.** Each declared
probe carries a `because` field naming the GLOBIN document whose rule would be
violated if it failed. Seven behaviours are not the whole of two large libraries,
and this package does not pretend otherwise: what it establishes is that *the
specific assumptions GLOBIN has written down* hold here. ADR-0058 records why
`numpy.test()` is deliberately not run.

**This is verification, not adoption.** Nothing under `src/globin` imports either
library, and `tests/architecture/test_stack_discipline.py` fails if anything
starts. `docs/PRECISION_POLICY.md` rule 1 is a one-way door, and it is far cheaper
to hold before the first import than after the tenth.

**What this does not decide.** The numeric type indicators and models use is
Phases 113-128; bit-identical reproducibility across hosts is Phase 158; whether a
GPU helps is Phases 023-024; the native TA-Lib library is Phase 025; which storage
engine persists a frame is Phase 097. Each is named in the declaration's deferral
table so that silence does not read as a gap.
"""

from tools.quality.stack.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    declaration_of,
    run_stack,
)
from tools.quality.stack.manifest import REASONS, SCHEMA, SCHEMA_VERSION
from tools.quality.stack.plan import (
    Declaration,
    Deferral,
    Library,
    ProbeSpec,
    StackError,
    Target,
    implemented_probes,
    parse_declaration,
)

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "REASONS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Declaration",
    "Deferral",
    "Library",
    "ProbeSpec",
    "StackError",
    "Target",
    "declaration_of",
    "implemented_probes",
    "parse_declaration",
    "run_stack",
]
