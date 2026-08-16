"""What this machine's GPU actually is, measured rather than assumed.

``ROADMAP.md`` gives Phase 023 one job: *detect GPU presence, driver version,
compute capability and CUDA availability **without assuming any of them***. The
emphasis is the roadmap's own, and the band it sits in says the same thing again —
"honest verification of GPU capability rather than assumption".

This package is that detection, made repeatable.

**Absence is a state, not a failure.** ADR-0045 settled that a platform capability
is a recorded state rather than a pass, because collapsing *we asked and it is
there*, *we asked and it is not*, *we could not ask* and *asking failed* into one
bit throws away exactly the distinction a later phase needs. Hardware is that
question with a different subject. A host with no NVIDIA device produces a
manifest full of ``ABSENT`` and exits zero, which is what lets this run on the
GPU-less machine continuous integration uses.

**The contract declares an interface, not a baseline.** ``gpu-contract.toml``
records no driver version and no device name. A driver updates on its own
schedule, and a file pinning one would go red on a Tuesday for a reason nobody in
this programme decided — then be bumped without being read. What is declared is
which documented fields may be asked, which must never be, and who answers for an
absence.

**The forbidden-field table is the reason this phase is not trivial.** Every entry
in it was measured on the target host rather than remembered. ``nvidia-smi``
refuses ``cuda_version`` as a query field outright, and answers two of its own
``--version`` labels — ``DRIVER version`` and ``CUDA version`` — with the word
*Deprecated* and a pointer elsewhere. A detector reading either would publish a
sentence where a version belongs, and nothing downstream could tell it from a
measurement. That is what "without assuming any of them" is guarding against, and
it is recorded in ``docs/research/phase_023_sources.md`` with the output it came
from.

**A runtime is not a toolkit.** The driver-side CUDA runtime and an installed
CUDA compiler are asked separately and neither is derived from the other, because
a host can have either without the other — and the target host has the first
without the second. That distinction is the difference between *a prebuilt CUDA
wheel would run here* and *CUDA source could be built here*, which is precisely
what Phase 024 will need when it asks which workloads benefit.

**What this does not decide.** Whether any workload should use a GPU is Phase
024's, and nothing here times anything. Which libraries GLOBIN adopts is
``docs/DEPENDENCY_POLICY.md`` and one written review at a time. Recording that a
device exists is not recommending it, in the same way Phase 018 surveying a wheel
was not adopting it.
"""

from tools.quality.gpu.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    declaration_of,
    run_gpu,
)
from tools.quality.gpu.manifest import REASONS, SCHEMA, SCHEMA_VERSION
from tools.quality.gpu.plan import (
    Capability,
    Declaration,
    ForbiddenField,
    GpuContractError,
    Interface,
    Observation,
    Reading,
    State,
    Target,
    classify,
    parse_declaration,
)

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "REASONS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Capability",
    "Declaration",
    "ForbiddenField",
    "GpuContractError",
    "Interface",
    "Observation",
    "Reading",
    "State",
    "Target",
    "classify",
    "declaration_of",
    "parse_declaration",
    "run_gpu",
]
