"""The Binance API reality registry, recomputed and optionally re-checked.

Two verbs. ``check`` reads the committed declaration, recomputes every claim it
makes, and writes ``.globin/api_reality/api-reality-manifest.json``. It reaches
nothing. ``refresh`` adds the half that asks the venue whether the record still
holds, which is why it is a separate word and why neither is in ``full``.

**This package parses the registry independently of the one that ships.**
``globin.adapters.api_reality`` reads the same document, and nothing here imports
it -- so a registry the package would mis-read is caught by a reader sharing none
of its code. That is the two-reader discipline Phase 020 applied to the lock.

Reasoning: ``docs/engineering/BINANCE_API_REALITY.md`` and ADR-0087.
"""

from tools.quality.venue.gate import Outcome, describe, run_api_reality

__all__ = ["Outcome", "describe", "run_api_reality"]
