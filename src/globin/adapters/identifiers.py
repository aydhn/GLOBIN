"""Minting identifiers: the only place a canonical name is generated rather than read.

:mod:`globin.domain.identifiers` decides what an identifier may look like. This
module produces one, and it sits out here for the reason ADR-0026 gives about
correlation identifiers: generating a value reads a source of randomness, which
is ambient nondeterminism, and the domain layer is where GLOBIN keeps the things
that behave the same way twice.

**Only run identifiers are minted.** GLOBIN originates a run; it does not
originate the others. A product name and an environment name are given by the
venue or by an operator, a symbol is a pair of currencies, an order identifier is
Phases 081-096 to produce and Phases 033-048 to reconcile with the venue, and a
model identifier is Phases 097 and beyond. Minting a kind nobody can yet create
would be a guess wearing a function signature.
"""

from uuid import uuid4

from globin.domain.identifiers import RunId


def new_run_id() -> RunId:
    """Return a fresh run identifier.

    Returns:
        A run identifier carrying 32 lowercase hexadecimal characters.

    Built through :class:`~globin.domain.identifiers.RunId` rather than returned
    as text, so that the one producer of this kind is also the first thing to be
    held to its own rules. A test that needs a stable identifier passes its own,
    exactly as ADR-0026 requires of a correlation identifier.
    """
    return RunId(text=uuid4().hex)
