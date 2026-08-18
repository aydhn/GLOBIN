"""``python -m tools.quality.materialize``."""

import sys

from tools.quality.materialize.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
