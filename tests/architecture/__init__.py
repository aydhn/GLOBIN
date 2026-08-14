"""Architecture tests: the layer contract, enforced against the real import graph.

These read ``docs/architecture/dependency-rules.toml`` — the canonical matrix,
never a second copy of it — and check the package's actual imports against it:
forbidden cross-layer imports, inward dependency direction, I/O reaching an
inner layer, import cycles, and work performed at import time.

Imports are read from the syntax tree rather than by importing, because
importing would execute the modules and one of the rules under test is that
importing executes nothing.
"""
