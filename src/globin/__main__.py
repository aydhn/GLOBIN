"""Entry point for ``python -m globin``.

Three lines, and deliberately no more. Everything this could usefully do lives in
:func:`globin.runtime.cli.main`, so that ``python -m globin`` and the ``globin``
console script reach the same code rather than two implementations that agree
today.

Exercised by a subprocess test rather than annotated with a coverage pragma, on
the reasoning ``docs/engineering/QUALITY_GATES.md`` gives about the other module
guards: a line excluded from measurement is a line nobody is measuring.
"""

import sys

from globin.runtime.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
