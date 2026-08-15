"""The supply-chain gate: what this repository depends on, and what that costs.

Phase 014 owns dependency review, and eleven places in this repository defer to
it — ``pytest-xdist`` (ADR-0036), ``mutmut`` (ADR-0033) and a YAML parser
(ADR-0043) were each refused pending "Phase 014's review process, which does not
exist yet". This package is that process made executable.

**What it establishes, in order of how much it can be trusted.**

*What is declared.* :mod:`~tools.quality.supply.inventory` reads the three
manifests that name a dependency and reports where they disagree. It runs no
resolver and claims no transitive tree; that is Phase 020's subject.

*What that inventory is, as a document others can read.*
:mod:`~tools.quality.supply.sbom` renders it as CycloneDX 1.7 — deterministic,
digested, and generated here rather than by a tool, for the reason ADR-0033 gave
about the mutation harness: a generator that stamps a clock and a random serial
cannot produce the same bytes twice, and bytes that differ every run are not
evidence.

*What is known to be wrong with it.* :mod:`~tools.quality.supply.audit` runs
``pip-audit`` and refuses to read a collection failure or an unreachable advisory
service as "no vulnerabilities". :mod:`~tools.quality.supply.waivers` lets a
finding be accepted for a stated reason by a named owner until a stated date, and
not one day longer.

*What the platform will and will not do.*
:mod:`~tools.quality.supply.capability` records each GitHub-hosted control as a
state with the HTTP status that proved it. ``UNAVAILABLE`` is never reduced to
``PASS``; a control that is absent is absent, and saying so is the only honest
report available.

*What must never be committed.* :mod:`~tools.quality.supply.secrets` scans
content, where ``tests/contract/test_repository_contract.py`` scans filenames,
and reports fingerprints rather than matches — a secret scanner that prints what
it found has published it a second time.

**One verdict, not a second aggregate.** :mod:`~tools.quality.supply.gate`
reduces all of the above to the same :class:`~tools.quality.execution.plan.Verdict`
the rest of the tooling uses, and ``tools/quality/workflow`` reads it alongside
every other gate. ADR-0042 put the aggregate in one place; this adds a gate to
it rather than a rival to it.
"""

from tools.quality.supply.gate import EXIT_GATE_FAILED, EXIT_OK, EXIT_UNMEASURED, run_supply
from tools.quality.supply.inventory import Dependency, SupplyChainError, collect, drift
from tools.quality.supply.manifest import SCHEMA, SCHEMA_VERSION

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Dependency",
    "SupplyChainError",
    "collect",
    "drift",
    "run_supply",
]
