"""Whether this host is one GLOBIN has been verified on, and whether its environment is.

For sixteen phases this repository was developed against whichever ``python`` the
PATH happened to resolve first, with its toolchain installed at user level and no
virtual environment at all. That worked, and it was never evidence: the
development host carries two interpreters and two launchers on PATH, so "the tests
passed" named no interpreter, and nothing would have noticed the day it changed.

**So the runtime is declared, and the declaration is checked against the host.**
``docs/engineering/runtime-contract.toml`` is what a human decided — the
implementation, the minor line, the patch floor, the architecture, the Windows
release and the environment's one directory. This package compares it against the
real machine, and ``tests/contract/test_runtime_contract.py`` asserts the contract's
own shape offline as part of the ordinary suite.

**A floor, not an exact pin.** The contract names the oldest patch the tree has
been verified on and accepts anything later in the same line. An exact pin would
fail the build on the day a security patch was installed, which is the day it is
least welcome, and would be quietly re-derived from whatever was installed the
first time that became inconvenient.

**Read-only by default, and never on the host.** ``check`` creates nothing and
installs nothing; ``bootstrap`` writes only inside the repository. Neither edits
the registry, the PATH, the execution policy, or any interpreter outside ``.venv``.
Where a host setting is wrong — long paths disabled, no install manager — the gate
records the state and names the official remedy, because a tool that reconfigures
the machine it is diagnosing has destroyed the evidence it was run to collect
(ADR-0045).

**What is not decided here.** The run-level verdict belongs to
``tools/quality/workflow`` (ADR-0042); this gate reports its own. Which libraries
have wheels for the pinned interpreter is Phase 018. Locking the dependency set is
Phase 020. Runtime configuration and credential onboarding are Phases 021-032. The
reasoning behind the baseline is ``docs/engineering/RUNTIME_BASELINE.md`` and
ADR-0050, and this package restates neither — it asserts them.
"""

from tools.quality.runtime.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    run_runtime,
)
from tools.quality.runtime.manifest import REASONS, SCHEMA, SCHEMA_VERSION
from tools.quality.runtime.plan import (
    Contract,
    Environment,
    Host,
    Interpreter,
    Launcher,
    RuntimeBaselineError,
    Version,
)

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "REASONS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Contract",
    "Environment",
    "Host",
    "Interpreter",
    "Launcher",
    "RuntimeBaselineError",
    "Version",
    "run_runtime",
]
