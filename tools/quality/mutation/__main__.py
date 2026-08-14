"""Entry point for ``python -m tools.quality.mutation``.

Three lines, on purpose. Everything the gate does lives in
:mod:`tools.quality.mutation.gate`, where it takes its repository root and its
way of starting a child as arguments and can therefore be tested. The guard below
is the one statement in this package no test executes, exercised instead by
``tests/contract/test_mutation_contract.py`` running the module in a subprocess —
the same trade ``tools/quality/__main__.py`` already makes, and for the same
reason: a ``pragma`` would claim coverage the repository does not have.
"""

from tools.quality.mutation.gate import REPO_ROOT, run

if __name__ == "__main__":
    raise SystemExit(run(REPO_ROOT))
