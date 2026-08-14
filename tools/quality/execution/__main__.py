"""Entry point for ``python -m tools.quality.execution``.

Thin on purpose. Everything the gate does lives in
:mod:`tools.quality.execution.gate`, where it takes its repository root and its
way of starting a child as arguments and can therefore be tested. The guard
below is the one statement in this package no test executes, exercised instead
by a contract test running the module in a subprocess — the same trade
``tools/quality/mutation/__main__.py`` already makes.
"""

import sys

from tools.quality.execution.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
