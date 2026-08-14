"""GLOBIN's error taxonomy: one root, and one class per kind of fault.

Every fault GLOBIN raises deliberately descends from :class:`GlobinError`, so a
caller can distinguish "GLOBIN refused" from "something else went wrong" with a
single ``except``. Below the root, faults are separated by **who has to act**
rather than by where the ``raise`` happens to sit.

That axis is the whole design, and it is chosen because the obvious alternative
fails. A hierarchy named after modules or layers grows a class per subsystem,
tells the reader nothing the traceback did not already show, and leaves the
question a caller actually has — *can I retry this, or must a human change
something?* — unanswered. Naming the responsible party answers it directly:
:class:`ConfigurationError` means the operator edits a file,
:class:`ValidationError` means the caller sends different input,
:class:`TransportError` means the network misbehaved, :class:`ExchangeError`
means the venue said no, and :class:`InternalError` means GLOBIN has a bug.

Three consequences worth stating, because each was a decision rather than an
accident.

*Nothing here inherits from a builtin exception type.* Making
:class:`ValidationError` a subclass of :exc:`ValueError` would smooth the
migration from the ad-hoc scheme this module replaces, at the cost of the
property that makes the taxonomy worth having: ``except ValueError`` in
unrelated code would silently begin catching GLOBIN faults it knows nothing
about. ``globin.adapters.architecture`` deliberately raised a single ad-hoc
scheme so that this phase would have *one* thing to replace rather than two
(ADR-0022); replacing it with a hybrid would recreate the problem.

*All five categories are defined now, including the two with no call sites.*
:class:`TransportError` and :class:`ExchangeError` acquire callers in Phases
033-048, when there is an exchange to talk to. They are defined here because the
roadmap makes designing the whole separation this phase's deliverable, and
because a taxonomy discovered one class at a time under delivery pressure is how
overlapping categories appear. They are not stubs: each is complete, and
:class:`FaultDomain` makes the separation assertable rather than merely
intended.

*Retryability is not modelled.* It is tempting to hang a boolean off
:class:`TransportError`, and it would be wrong here. Whether a timed-out request
may be retried depends on whether it was idempotent, which is a Phase 083
question, and ``MEMORY.md`` records that a timeout or 5XX does not prove an
order failed. Phase 086 owns that decision with the evidence to make it.

This module imports nothing from GLOBIN and performs no I/O, which is what lets
every layer read it. It is registered in the ``[shared]`` table of
``docs/architecture/dependency-rules.toml`` alongside
:mod:`globin.project_contract` and :mod:`globin.roadmap`, and
``tests/architecture/test_architecture_contract.py`` holds it to the one-way
rule that shared modules import no layer.
"""

from enum import StrEnum
from typing import ClassVar


class FaultDomain(StrEnum):
    """The kinds of fault GLOBIN distinguishes, by who must act on them.

    One member per concrete subclass of :class:`GlobinError`, and the
    correspondence is exact in both directions — asserted by
    ``tests/contract/test_error_taxonomy_contract.py``. A sixth kind of fault
    therefore cannot be added by quietly subclassing an existing error; it
    requires a member here, which is a visible change to a type.
    """

    CONFIGURATION = "configuration"
    VALIDATION = "validation"
    TRANSPORT = "transport"
    EXCHANGE = "exchange"
    INTERNAL = "internal"


class GlobinError(Exception):
    """Base class for every fault GLOBIN raises deliberately.

    Catch this to mean "GLOBIN itself refused or failed". Do not raise it: it
    declares no :attr:`fault`, because a fault with no category is exactly the
    uncategorised error this module exists to eliminate. The annotation below is
    deliberately unassigned, so ``hasattr(GlobinError, "fault")`` is ``False``
    and the omission is observable rather than a matter of etiquette.
    """

    fault: ClassVar[FaultDomain]


class ConfigurationError(GlobinError):
    """The configuration GLOBIN was given is missing, malformed or inconsistent.

    The operator must change a file or a setting. Retrying cannot help, because
    nothing about the request was wrong — the environment it ran in was.
    """

    fault: ClassVar[FaultDomain] = FaultDomain.CONFIGURATION


class ValidationError(GlobinError):
    """Input crossing a boundary does not satisfy the contract for that boundary.

    The caller must send something different. This covers arguments, parsed
    documents and any other data GLOBIN accepts from outside the function that
    rejects it; it does not cover a venue rejecting an otherwise well-formed
    request, which is an :class:`ExchangeError`.
    """

    fault: ClassVar[FaultDomain] = FaultDomain.VALIDATION


class TransportError(GlobinError):
    """A request could not be completed at the transport level.

    Connection failures, timeouts and protocol-level faults belong here: GLOBIN
    never learned what the other side thought. Distinguishing this from
    :class:`ExchangeError` is load-bearing rather than tidy — an answer that
    never arrived is not the same as a refusal, and treating the two alike is
    how a system convinces itself an order failed when it did not.

    Phases 033-048 introduce the callers.
    """

    fault: ClassVar[FaultDomain] = FaultDomain.TRANSPORT


class ExchangeError(GlobinError):
    """The venue answered, and the answer was a refusal or an error.

    The exchange is authoritative about its own state, so this reports what it
    said rather than what GLOBIN expected. Phases 033-048 introduce the callers.
    """

    fault: ClassVar[FaultDomain] = FaultDomain.EXCHANGE


class InternalError(GlobinError):
    """A GLOBIN invariant that should hold has not held.

    Always a defect in GLOBIN, never an expected outcome, and never the right
    way to report bad input — that is a :class:`ValidationError`. Raise it where
    a state is unreachable unless an earlier guarantee was broken, so that the
    breach surfaces at the point it is detected instead of becoming a confusing
    failure somewhere downstream.
    """

    fault: ClassVar[FaultDomain] = FaultDomain.INTERNAL
