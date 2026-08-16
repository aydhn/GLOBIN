"""Run the workload benefit gate as a module.

Exercised by a subprocess test rather than a coverage pragma, for the reason every
other gate's entry point is: a line marked as not covered is a line nobody has run.
"""

import sys

from tools.quality.benchmark.cli import main

raise SystemExit(main(sys.argv[1:]))
