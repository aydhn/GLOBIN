"""The contract for reading what the venue documents.

One protocol, one method, returning ``None`` rather than raising when the registry
cannot be read at all. That distinction is the same one
:mod:`globin.ports.degradation` draws: ``None`` means *the declaration was not
readable*, which a caller reports as unmeasured, while a
:class:`~globin.errors.ValidationError` means *the committed document is wrong*,
which is a defect in this repository rather than a property of the host.
"""

from typing import Protocol

from globin.domain.api_reality import ApiRealitySnapshot


class ApiRealitySource(Protocol):
    """Something that can produce the registry.

    Implemented by :class:`globin.adapters.api_reality.TomlApiRealitySource`, and
    by a hand-written double in the tests. Nothing here reaches a network: the
    registry is a committed document, and refreshing it from the venue is a
    repository-maintenance act performed from outside this package.
    """

    def snapshot(self) -> ApiRealitySnapshot | None:
        """The registry, or nothing.

        Returns:
            The parsed snapshot, or ``None`` if the declaration is absent or
            unreadable. Never a partially populated snapshot: a registry read
            halfway would report capabilities as absent that are merely unread.
        """
        ...
