"""Deterministic multi-process test execution, with no plugin.

Collect once into a digested manifest, partition it by a seeded hash, run each
shard as its own pytest process, and account for every test exactly once.

**Why this exists rather than `pytest-xdist`.** ADR-0032 permits verification
tooling outside phase scope under six conditions, and the third is that it adds
no dependency. `pytest-xdist` would be one, and ADR-0032 is explicit about where
that leads: anything arriving as a dependency needs Phase 014's review process,
which does not exist yet. So the parts of the job that need a scheduler are not
done here, and the parts that need only a stable partition are. ADR-0036 records
which is which.

Modules are split by purity, exactly as `tools/quality/mutation` is:
`manifest`, `shard` and `plan` are pure; `workspace` alone touches disk or
process; `gate` orchestrates and takes its runner as an argument.
"""

from tools.quality.execution.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    EXIT_USAGE,
    run_shards,
)

__all__ = [
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "EXIT_USAGE",
    "run_shards",
]
