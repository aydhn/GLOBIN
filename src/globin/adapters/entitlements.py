"""Keeping what an operator declared about each credential, outside the tree.

The register lives in the Phase 022 runtime state area, which is user-local and
deliberately not ``.globin/``: that tree is evidence about this repository and CI
reads it, and this is state about this machine.

**The proof that this file can carry no secret is structural, not procedural.**
A :class:`~globin.domain.entitlements.GrantDeclaration` has two fields, one a
reference and one a set of bounded enum members. There is no field a value could
occupy, no branch that could write one, and
:class:`~globin.domain.secrets.SecretValue` is unhashable and has no encoder, so
it could not become a key or be serialised even by accident.

Three exception types are caught at each boundary rather than one, and the
third is the one worth naming: ``RuntimePersistenceError`` is a
``ConfigurationError``, not a ``ValidationError``, so an ``except`` that listed
only the obvious two let a store that could not be written escape as a
traceback. A unit test drives that path.

A document this version does not recognise is read as *nothing declared* rather
than raised on. That is the refusing direction: with no declaration,
:func:`~globin.domain.entitlements.verify` answers
:attr:`~globin.domain.entitlements.VerificationState.UNDECLARED` and use is
refused.
"""

from dataclasses import dataclass
from typing import Final

from globin.domain.entitlements import Grant, GrantDeclaration, GrantSet
from globin.domain.identifiers import EnvironmentId
from globin.domain.runtime_state import RuntimeArea, RuntimePersistenceError
from globin.domain.secrets import SecretKind, SecretReference
from globin.errors import ValidationError
from globin.ports.runtime_state import StateStore

SCHEMA: Final[str] = "globin.secrets.grants"
"""Identifies the document, so another one fed to this reader is refused by name."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped when the shape changes. A version this reader does not know is read as
nothing declared, which refuses rather than guesses."""

REGISTER_NAME: Final[str] = "secret-grants.json"
"""What the register is called inside the state area."""


@dataclass(frozen=True, slots=True)
class StateGrantRegister:
    """Stores grant declarations as one atomically published document.

    Args:
        store: The Phase 022 state store, which publishes atomically.
        name: The document's filename.
    """

    store: StateStore
    name: str = REGISTER_NAME

    def declarations(self) -> tuple[GrantDeclaration, ...]:
        """Every declaration the register holds.

        Returns:
            The declarations, sorted by reference. Empty when the register is
            absent, unreadable, or of a version this reader does not know.
        """
        try:
            document = self.store.read(RuntimeArea.STATE, self.name)
        except (ValidationError, RuntimePersistenceError, OSError):
            return ()
        if document is None:
            return ()
        if document.get("schema") != SCHEMA:
            return ()
        if document.get("schema_version") != SCHEMA_VERSION:
            return ()
        entries = document.get("declarations")
        if not isinstance(entries, list):
            return ()
        found = [
            declaration
            for entry in entries
            if (declaration := _declaration_from(entry)) is not None
        ]
        return tuple(sorted(found, key=lambda item: item.reference))

    def declare(self, declaration: GrantDeclaration) -> bool:
        """Record what a credential is permitted to do.

        Args:
            declaration: The reference and the declared grants.

        Returns:
            Whether it was written.

        Read-modify-write against the whole document, because the store publishes
        one document atomically and a per-reference file would multiply the
        number of things that can be half-written.
        """
        kept = [
            existing
            for existing in self.declarations()
            if existing.reference != declaration.reference
        ]
        kept.append(declaration)
        document = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "declarations": [
                item.as_record() for item in sorted(kept, key=lambda item: item.reference)
            ],
        }
        try:
            self.store.publish(RuntimeArea.STATE, self.name, document)
        except (ValidationError, RuntimePersistenceError, OSError):
            return False
        return True


def _declaration_from(entry: object) -> GrantDeclaration | None:
    """Rebuild one declaration from its record.

    Args:
        entry: One element of the stored list.

    Returns:
        The declaration, or ``None`` when the entry is malformed.

    A malformed entry is dropped rather than raised on, so that one bad record
    cannot make every other declaration unreadable. Dropping refuses; raising
    would take the whole register out.
    """
    if not isinstance(entry, dict):
        return None
    environment = entry.get("environment")
    name = entry.get("name")
    kind = entry.get("kind")
    declared = entry.get("declared")
    if not isinstance(environment, str) or not isinstance(name, str):
        return None
    if not isinstance(kind, str) or not isinstance(declared, list):
        return None
    try:
        reference = SecretReference(
            environment=EnvironmentId(environment),
            name=name,
            kind=SecretKind(kind),
        )
        grants = GrantSet(
            grants=tuple(Grant(value) for value in declared if isinstance(value, str))
        )
    except (ValidationError, ValueError):
        return None
    return GrantDeclaration(reference=reference, declared=grants)
