"""Entry point for ``python -m tools.quality.lock``.

Exercised by a subprocess test rather than annotated with a coverage pragma, on
the reasoning ``docs/engineering/QUALITY_GATES.md`` gives about the other module
guards: a line excluded from measurement is a line nobody is measuring.
"""

import sys

from tools.quality.lock.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
