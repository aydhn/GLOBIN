"""Whether the environment a lock describes could be built from local bytes.

Four questions this package answers and one it refuses. It answers whether the
declared target has an artefact at all, whether that artefact is in the local
wheelhouse, whether its bytes are the bytes the lock names, and whether a
throwaway environment can be built from it. It refuses to fetch anything in the
offline path: `plan.py` imports no networking module, so a network fallback is
unreachable rather than merely un-taken.

Two subcommands do reach an index -- `fetch` and `cleanroom` -- and they are
outside `python -m tools.quality full` for the reason ADR-0052 gives about the
wheel probe: `full` runs before every commit and must work on an aeroplane.
"""

from tools.quality.materialize.gate import run_materialize

__all__ = ["run_materialize"]
