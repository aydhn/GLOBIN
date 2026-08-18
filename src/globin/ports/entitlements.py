"""Where GLOBIN keeps what an operator says a credential is permitted to do.

Two methods rather than one, because there is a single register read in two
directions and splitting it into two ports would make every test that needed to
write one also build a reader.

**Neither method raises for an expected absence.** A register that has never been
written is an empty tuple, not an exception; a write that could not land is
``False``, not an exception. What a caller does about either is a judgement, and
judgements live above this line.

**Nothing here holds material.** A :class:`~globin.domain.entitlements.GrantDeclaration`
carries a reference and a set of bounded enum members, so there is no field a
secret could occupy and no branch in which one could be written.
"""

from typing import Protocol

from globin.domain.entitlements import GrantDeclaration


class GrantRegister(Protocol):
    """Reads and writes what an operator declared about each credential."""

    def declarations(self) -> tuple[GrantDeclaration, ...]:
        """Every declaration the register holds.

        Returns:
            The declarations, in a deterministic order. Empty when the register
            has never been written, cannot be read, or holds a document this
            version does not recognise -- all three of which mean the same thing
            to a caller: nothing may be assumed about any credential.
        """
        ...

    def declare(self, declaration: GrantDeclaration) -> bool:
        """Record what a credential is permitted to do.

        Args:
            declaration: The reference and the grants an operator states it has.

        Returns:
            Whether the declaration was written. ``False`` when it could not be,
            which is a condition to report rather than to raise on -- the
            surrounding command has already collected nothing and changed
            nothing.

        Replaces any existing declaration for the same reference. A register with
        two answers for one credential could not be consulted.
        """
        ...
