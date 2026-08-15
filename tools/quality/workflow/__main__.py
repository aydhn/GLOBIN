"""Entry point: ``python -m tools.quality.workflow``."""

import sys

from tools.quality.workflow.cli import main

raise SystemExit(main(sys.argv[1:]))
