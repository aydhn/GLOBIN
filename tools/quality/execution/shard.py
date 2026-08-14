"""Splitting a manifest into shards, deterministically.

The contract, in three lines:

    union(shards) == the manifest
    shard_i ∩ shard_j == ∅   for i != j
    the same (manifest, count, seed) always gives the same mapping

**Python's builtin :func:`hash` is forbidden here** and appears nowhere. Hash
randomisation makes it differ between processes, so a partition built on it
would be stable within one run and meaningless between two — which is the exact
opposite of what a shard mapping is for. A unit test proves the mapping survives
two interpreters started with different ``PYTHONHASHSEED`` values, because that
is the only way to observe the difference.

**Why a seeded deal rather than the obvious alternatives.**

*Contiguous slices of the sorted list* are perfectly balanced and land every
module intact in one shard. That last property sounds like a feature — it is
what ``pytest-xdist``'s ``loadfile`` buys — but it makes the partition useless
as an order probe: within a module the order never varies, whatever the seed.

*Digest modulo the shard count* is deterministic and varies with a seed, but its
balance is only statistical, and on a small selection it can leave a shard
**empty**. An empty shard is pytest exit 5, which is the trap this repository's
mutation harness already exists to avoid.

What is used instead: sort the IDs by a seeded digest, then deal them round
robin. Deterministic, exactly balanced for every seed, and it varies the order
*within* a shard, which is what makes ``soak`` able to find an order-dependent
test with no plugin at all.
"""

import hashlib
from typing import Final

DOMAIN: Final[str] = "globin.execution.shard"
"""Separates this hash's inputs from the manifest digest's.

Two hashes over related data with no separator is how a value computed for one
purpose silently becomes valid for another.
"""

ALGORITHM_VERSION: Final[int] = 1
"""Inside the hashed payload, so changing the deal changes every mapping."""


class ShardError(Exception):
    """A partition was asked for that cannot exist."""


def validate(*, total: int, shard_count: int, shard_index: int | None = None) -> None:
    """Refuse a partition that cannot be honoured.

    Args:
        total: How many tests there are.
        shard_count: How many shards were asked for.
        shard_index: Which shard, when only one is wanted.

    Raises:
        ShardError: If the count is not positive, if it exceeds the number of
            tests, or if the index is outside it.

    ``shard_count > total`` is refused rather than allowed to produce an empty
    shard. pytest exits 5 for "no tests collected", and a run that reads 5 as
    success reports a shard that measured nothing as a shard that passed.
    """
    if shard_count < 1:
        msg = f"shard count must be at least 1, got {shard_count}"
        raise ShardError(msg)
    if shard_count > total:
        msg = (
            f"cannot split {total} tests into {shard_count} shards: at least one would "
            f"be empty, and an empty shard is pytest exit 5 rather than a pass"
        )
        raise ShardError(msg)
    if shard_index is not None and not 0 <= shard_index < shard_count:
        msg = f"shard index must be in 0..{shard_count - 1}, got {shard_index}"
        raise ShardError(msg)


def _key(node_id: str, *, seed: int) -> bytes:
    """The sort key one node ID gets under one seed."""
    payload = f"{DOMAIN}\n{ALGORITHM_VERSION}\n{seed}\n{node_id}\n"
    return hashlib.sha256(payload.encode("utf-8")).digest()


def partition(
    node_ids: tuple[str, ...], *, shard_count: int, seed: int
) -> tuple[tuple[str, ...], ...]:
    """Split node IDs into shards.

    Args:
        node_ids: The manifest's tests, in any order.
        shard_count: How many shards to produce.
        seed: Varies the deal. The same seed always gives the same deal.

    Returns:
        One tuple per shard, in shard order.

    Raises:
        ShardError: If the partition cannot exist — see :func:`validate`.

    The tie-break is the node ID itself, stated rather than left implicit. A
    sha256 collision will not happen; an *unstated* tie-break is a
    machine-dependent order waiting for the day it does.

    Sizes differ by at most one, for every seed, because dealing round robin
    from a fully ordered list cannot do anything else.
    """
    validate(total=len(node_ids), shard_count=shard_count)
    ordered = sorted(node_ids, key=lambda node_id: (_key(node_id, seed=seed), node_id))
    return tuple(tuple(ordered[index::shard_count]) for index in range(shard_count))
