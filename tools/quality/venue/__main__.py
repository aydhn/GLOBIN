"""Entry point, so the package can be started with ``python -m``.

Nothing but the wiring. Exercised by a subprocess test rather than annotated with
a coverage pragma, for the reason ``QUALITY_GATES.md`` gives: a pragma asserts that
a line does not need testing, and starting the module is the only way to find out
whether it works.
"""

import sys

from tools.quality.venue.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
