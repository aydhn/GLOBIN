"""The dependency lock, and every claim in it recomputed from its own evidence.

``python -m tools.quality lock`` reads ``pylock.dev.toml`` and the declaration in
``docs/engineering/lock-policy.toml``, and decides — offline, opening no socket —
whether the lock says what it claims to say: that every artefact carries a hash in
a permitted algorithm, that every artefact is served over HTTPS from the declared
host, that at least one recorded wheel's PEP 425 tags serve the interpreter
``docs/engineering/runtime-contract.toml`` pins, and that the lock and the three
declaration registers agree about one version each.

**Why the verdict is recomputed rather than read.** ``pip`` writes the lock, and
validating it with ``pip``'s own reader would establish only that pip agrees with
itself — on a feature pip labels experimental. So the file is parsed here with
``tomllib`` alone, and the answer is derived from the filenames, URLs and digests
recorded in it. This is ADR-0052's pattern applied to a second kind of record:
evidence is written down so that a claim can be checked instead of believed.

**What the lock covers, and what it deliberately does not.** The toolchain is
locked; the runtime is not, because ``project.dependencies`` is empty and a lock
of an empty set is refused outright by ``pip-audit --locked``. That asymmetry is
not left to memory: ``LOCK_RUNTIME_UNLOCKED`` fails the moment a runtime
dependency is declared without the lock that must accompany it, which is Phase
021's to add.

**Four subcommands, split by whether they reach the index.**

``check`` recomputes the lock offline and is the default. ``installed`` adds a
comparison against this environment, using one read of the interpreter's own
metadata. ``relock`` and ``upgrade`` re-resolve and rewrite the lock, and those
**reach PyPI** — the same split ``runtime bootstrap`` and ``wheels probe`` make,
for the reason ``full`` gives: a gate that runs before every commit must work on an
aeroplane.

Nothing here installs anything, and nothing here edits the declaration it reads.
Regenerating the lock names the declaration lines a person must update; writing
them is theirs, because a declaration a tool rewrites is a mirror rather than a
source.

Reasoning:
[ADR-0054](../../../docs/adr/0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md)
and ``docs/engineering/DEPENDENCY_LOCKING.md``.
"""

from tools.quality.lock.cli import main
from tools.quality.lock.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    declaration_of,
    lock_of,
    run_lock,
)
from tools.quality.lock.manifest import PHASE, REASONS, SCHEMA, SCHEMA_VERSION
from tools.quality.lock.plan import (
    CONFIGURATION_FILE,
    Declaration,
    Lock,
    LockedFile,
    LockedPackage,
    LockError,
    LockTarget,
    Policy,
    normalise,
    parse_declaration,
    parse_lock,
)

__all__ = [
    "CONFIGURATION_FILE",
    "EXIT_GATE_FAILED",
    "EXIT_OK",
    "EXIT_UNMEASURED",
    "PHASE",
    "REASONS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Declaration",
    "Lock",
    "LockError",
    "LockTarget",
    "LockedFile",
    "LockedPackage",
    "Policy",
    "declaration_of",
    "lock_of",
    "main",
    "normalise",
    "parse_declaration",
    "parse_lock",
    "run_lock",
]
