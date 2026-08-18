"""Asking a person for a credential at a console, and refusing when it is unsafe.

The one module in GLOBIN that reads secret material from a human being. Three
refusals happen before any material exists, and the order of them is the design
rather than an implementation detail.

**A non-interactive stdin refuses first, and ``getpass`` is never called.**
``SECRET_STORE_CONTRACT.md`` section 5 permits collection by "interactive entry
only". Reading a pipe would make a shell one-liner that feeds a key into this
command work, which puts the material in shell history and in the writing
process command line -- both prohibited by ``SECURITY_BASELINE.md`` section 2.

**A platform that cannot suppress echo aborts before anything is typed.** Section
5 requires that ``GetPassWarning`` abort collection rather than be printed. The
implementation reads ``getpass``'s own source: ``fallback_getpass`` calls
``warnings.warn`` *before* it prints its notice and *before* it reads. Turning
that warning into an error therefore aborts while the operator has typed nothing
-- so the value never exists, rather than existing and being discarded. That is
stronger than the contract asks for.

**The confirmation is unconditional and constant-time by inheritance.** The
material is asked for twice and compared through
:meth:`~globin.domain.secrets.SecretValue.__eq__`, which is already
``hmac.compare_digest``. No new comparison is written here, and there is no
argument that could switch the second entry off.

Two platform facts worth stating rather than rediscovering. ``echo_char`` is not
passed: it is 3.13 and later only, and CI runs 3.12, and masking with a character
echoes the *length*, which is information. And on Windows ``win_getpass`` writes
its prompt with ``msvcrt.putwch``, **ignoring the stream it is handed** -- so the
prompt reaches the console rather than the injected stream. It never reaches
standard output, so the ``--json`` contract holds, but the injection is not the
guarantee it looks like on that platform.
"""

import getpass
import warnings
from dataclasses import dataclass
from typing import Protocol, TextIO

from globin.domain.secrets import (
    EntryFault,
    SecretEntryOutcome,
    SecretValue,
    entry_problems,
)

CONFIRM_SUFFIX: str = " (again): "
"""What the second prompt ends with, so the two entries are distinguishable."""


class TerminalQuestion(Protocol):
    """The one question this adapter asks of standard input.

    Narrower than :class:`~typing.TextIO` deliberately. This adapter never
    *reads* from standard input -- ``getpass`` does that, from the terminal --
    so a field typed as a full text stream would claim a capability the code
    does not use and cannot be given by a test double honestly.
    """

    def isatty(self) -> bool:
        """Whether this stream is a terminal."""
        ...


@dataclass(frozen=True, slots=True)
class ConsoleSecretEntry:
    """Collects a secret from a real terminal.

    Args:
        stream: Where the prompt is written. Standard error, so that a command
            rendering a document to standard output stays machine-readable.
        stdin: Asked only whether it is a terminal, which is why it is typed
            as :class:`TerminalQuestion` rather than as a stream. Never read
            from directly: ``getpass`` reads the terminal itself.
    """

    stream: TextIO
    stdin: TerminalQuestion

    def collect(self, prompt: str) -> SecretEntryOutcome:
        """Ask for a secret twice and return what was collected.

        Args:
            prompt: What to show before the first entry.

        Returns:
            An outcome carrying a value or a bounded fault. Never raises.

        The malformed-second-entry case is the subtle one: it reports
        :attr:`~globin.domain.secrets.EntryFault.MISMATCH` rather than
        :attr:`~globin.domain.secrets.EntryFault.REFUSED_FORMAT`, because
        reporting the second entry's shape would disclose something about what
        was typed the second time. All the operator needs to know is that the two
        differed.
        """
        if not self._interactive():
            return SecretEntryOutcome(fault=EntryFault.NOT_INTERACTIVE)

        first = self._read(prompt)
        if isinstance(first, EntryFault):
            return SecretEntryOutcome(fault=first)

        problems = entry_problems(first)
        if problems:
            return SecretEntryOutcome(fault=EntryFault.REFUSED_FORMAT, problems=problems)

        second = self._read(prompt.rstrip(": ") + CONFIRM_SUFFIX)
        if isinstance(second, EntryFault):
            return SecretEntryOutcome(fault=second)

        if entry_problems(second) or SecretValue(first) != SecretValue(second):
            return SecretEntryOutcome(fault=EntryFault.MISMATCH)

        return SecretEntryOutcome(value=SecretValue(first))

    def _interactive(self) -> bool:
        """Whether standard input is a terminal.

        Returns:
            Whether entry may be attempted at all.

        A stream that raises when asked is treated as not a terminal, which is
        the refusing direction.
        """
        try:
            return bool(self.stdin.isatty())
        except (OSError, ValueError):
            return False

    def _read(self, prompt: str) -> str | EntryFault:
        """Read one entry with echo suppressed, or say why it could not be.

        Args:
            prompt: What to show.

        Returns:
            The material, or the fault that stopped it.

        ``catch_warnings`` with ``action="error"`` is what converts
        ``GetPassWarning`` into the abort section 5 requires, and it is scoped to
        this call so that no other warning behaviour in the process changes.
        """
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                return getpass.getpass(prompt, stream=self.stream)
        except getpass.GetPassWarning:
            return EntryFault.ECHO_UNAVAILABLE
        except (EOFError, KeyboardInterrupt):
            return EntryFault.CANCELLED
        except (OSError, ValueError):
            return EntryFault.ENTRY_UNAVAILABLE
