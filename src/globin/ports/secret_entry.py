"""How GLOBIN asks a person for a credential.

One method, one argument, and no flag. The absence of the flag is the design:
:meth:`SecretEntry.collect` always confirms by asking twice, and there is no
parameter a caller could pass to switch that off. A security control a caller can
weaken is not a control.

Structural, like every port here, so the console implementation does not import
this module and the dependency still points inward from the adapter.
"""

from typing import Protocol

from globin.domain.secrets import SecretEntryOutcome


class SecretEntry(Protocol):
    """Collects secret material from a person, or explains why it could not."""

    def collect(self, prompt: str) -> SecretEntryOutcome:
        """Ask for a secret, twice, and return what was collected.

        Args:
            prompt: What to show before the first entry. Never contains material.

        Returns:
            An outcome carrying either a
            :class:`~globin.domain.secrets.SecretValue` or a bounded
            :class:`~globin.domain.secrets.EntryFault`.

        **Never raises for an expected refusal.** A non-interactive terminal, a
        platform that cannot suppress echo, an operator pressing Ctrl-C and two
        entries that differ are all *answers*, and each arrives as a value. An
        implementation that raised would push the classification out to every
        caller, which is where it would be got wrong -- the same argument
        ADR-0045 makes for a platform capability.

        **The confirmation is unconditional.** There is no ``confirm`` argument,
        because a caller able to pass ``False`` is a caller able to store a
        mistyped credential that nothing will detect until it is used against a
        venue.
        """
        ...
