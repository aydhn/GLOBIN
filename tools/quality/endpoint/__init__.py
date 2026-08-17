"""Whether the diagnostics endpoint's declared contract is the one the source implements.

Phase 027 built a loopback HTTP surface and wrote down what it promises. This package
is the second half of that: it recomputes every claim against `src/globin` rather than
believing it, and publishes the result as evidence a reader can compare between two
commits.

**It reaches nothing.** No socket is opened, no server started and no question asked of
this host. Every verdict is a comparison between `docs/engineering/endpoint-contract.toml`
and the source beside it, which is why it runs identically on a developer's machine and
on a continuous-integration runner where the surface has never been enabled.

**The one check that earns the gate is arithmetic rather than comparison.** Every other
function here holds two statements of one value against each other, which catches
drift. `family_problems` instead multiplies the attribute vocabularies it recovered
*from the source* and refuses a declared budget that is not the product. So adding a
seventh route — which grows the `route` vocabulary — fails this gate until both the
affected budgets and the contract move in the same edit. That is the difference between
a number somebody wrote down and a number that has to be true.

**Why a contract file rather than an import.** `tools/` cannot import `globin`: a
verifier that imported the thing it verifies could not report on one too broken to
import, which is the rule `tools/quality/supply/workflows.py` states about itself. So
the values are declared in TOML and recovered from the source by inspection, exactly as
`gpu-contract.toml` and `wheel-survey.toml` are. That inspection is a **proxy** — a
constant assembled at run time, or a route table built by a loop, would defeat it — and
every detector has failing cases in both directions in
`tests/unit/test_endpoint_plan.py`.

**What this does not do.** It does not start the surface, time it, scrape it, or check
that it answers: those are the suite's business, and
`tests/integration/test_diagnostics_endpoint_end_to_end.py` does them over a real
socket. It does not decide whether the surface should be enabled, which is an
operator's. And it is kept out of `full` deliberately — the guarantees it checks are
already enforced by the architecture and unit suites on every commit, and what this
adds is the artefact rather than a second enforcement.
"""

from tools.quality.endpoint.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    declaration_of,
    run_endpoint,
)
from tools.quality.endpoint.manifest import REASONS, SCHEMA, SCHEMA_VERSION
from tools.quality.endpoint.plan import (
    Bound,
    Declaration,
    EndpointContractError,
    Exposition,
    Family,
    Route,
    binding_problems,
    bound_problems,
    contract_problems,
    exposition_problems,
    family_problems,
    loopback_problems,
    parse_declaration,
    route_problems,
    switch_problems,
    test_problems,
    vocabulary_problems,
    wildcard_problems,
)

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "REASONS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Bound",
    "Declaration",
    "EndpointContractError",
    "Exposition",
    "Family",
    "Route",
    "binding_problems",
    "bound_problems",
    "contract_problems",
    "declaration_of",
    "exposition_problems",
    "family_problems",
    "loopback_problems",
    "parse_declaration",
    "route_problems",
    "run_endpoint",
    "switch_problems",
    "test_problems",
    "vocabulary_problems",
    "wildcard_problems",
]
