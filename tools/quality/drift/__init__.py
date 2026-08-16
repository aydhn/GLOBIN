"""Whether this host is still the host the gates were measured on, and what to do when it is not.

Phase 017 declared a runtime contract and built an environment to satisfy it, and
``tools/quality/runtime/`` checks the host against that contract on demand. That
answers an absolute question: *is this machine acceptable?* It cannot answer the
question this package exists for, because that one needs two measurements: *is
this machine what it was?*

The difference is not academic. The contract declares a patch **floor**, so an
interpreter that quietly went backwards inside the contracted line still satisfies
it — ``runtime`` passes, correctly, and nothing notices that somebody changed the
machine. A ``PIP_INDEX_URL`` appearing in the environment redirects every install
this project makes and violates no contract at all. Drift is the class of change
that is invisible to a rule and obvious in hindsight.

**A baseline is accepted, never assumed.** ``check`` reads the host and compares
it against a baseline a person recorded with ``accept``; it never writes one
itself. A check that recorded whatever it found would certify its own observation,
and drift would be undetectable by construction. With no baseline the verdict is
*unmeasured* rather than *clean* — ``docs/DEPENDENCY_POLICY.md`` prohibits
conflating "could not look" with "found nothing", and this is that distinction
applied to a machine.

**The classification is declared, and it is obeyed.**
``docs/engineering/drift-policy.toml`` says, per observation key, how serious a
change is and what would put it right. The gate reads ``repair`` from that file
and refuses to act on anything it does not mark ``in-place``, so the file changes
what the tool does rather than describing what it already did. Every recorded
verdict is recomputed from the evidence beside it, on ADR-0052's pattern: an entry
claiming a fault is repairable in place must say what the repair does and where it
writes, and one that does not agree with itself fails offline.

**Repair is bounded, and the boundary is the point of the phase.** Today
``RUNTIME_BASELINE.md`` answers five distinct environment faults with the same
destructive remedy. One of them does not deserve it: ``pyvenv.cfg`` is read at
interpreter start-up, so an environment that has gained access to the machine's
global packages is corrected by rewriting one key rather than by being destroyed
and rebuilt. That is the whole of what this tool writes. Everything else names
what a person should run — ``bootstrap.ps1``, with or without ``-Recreate`` — or
names something outside the repository that ADR-0050 forbids this tooling from
touching at all, and reports it instead.

**What this does not decide.** Which distributions this project depends on, and in
what versions — that is ``docs/DEPENDENCY_POLICY.md`` and Phase 021 onwards.
Resolution and locking are Phase 020's, and nothing here runs a resolver, writes a
lockfile or claims a transitive tree: it compares the installed version of a tool
this repository already declares against the pin it already declares. Where
configuration files live and which sources are consulted in what order remain
Phases 026 and 027's.
"""

from tools.quality.drift.gate import (
    ACCEPT,
    CHECK,
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    REPAIR,
    REPAIRS,
    observe,
    run_drift,
    write_problems,
)
from tools.quality.drift.manifest import REASONS, SCHEMA, SCHEMA_VERSION, DriftManifestError
from tools.quality.drift.plan import (
    Difference,
    DriftClass,
    DriftPolicyError,
    Judgement,
    Policy,
    classify,
    compare,
    parse_declaration,
    policy_problems,
)

__all__ = [
    "ACCEPT",
    "CHECK",
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "REASONS",
    "REPAIR",
    "REPAIRS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Difference",
    "DriftClass",
    "DriftManifestError",
    "DriftPolicyError",
    "Judgement",
    "Policy",
    "classify",
    "compare",
    "observe",
    "parse_declaration",
    "policy_problems",
    "run_drift",
    "write_problems",
]
