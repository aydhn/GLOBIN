"""The declared transport contract, read; and Phase 034's evidence, written.

Two jobs, both of them file-shaped, and neither of them able to reach a socket.
That separation is why this module exists beside
:mod:`globin.adapters.rest_transport` rather than inside it: the module that may
open a connection should be small enough to read in one sitting, and a contract
parser and a manifest writer would triple it.

**This is the second reader of a declared document, and the first one is under
``tools/``.** ``tools/quality/rest`` parses ``rest-transport.toml`` with no shared
code, and ``tests/contract/test_rest_contract.py`` compares what the two see —
exactly the arrangement Phase 033 built for the registry, and for the same reason:
two readers of one document inside one package is how they come to disagree, and
two readers in *different* packages is how you find out that they have.
"""

import hashlib
import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from globin.domain.api_reality import ProductFamily, SurfaceCapability
from globin.domain.rest import HttpMethod
from globin.domain.rest_contract import (
    NegotiationDeclaration,
    ProbeDescriptor,
    StatusRule,
    TransportContract,
)
from globin.errors import ValidationError

CONTRACT_PATH: Final[str] = "docs/engineering/rest-transport.toml"
"""Where the declared transport contract lives, relative to the repository root."""

SCHEMA: Final[str] = "globin.rest.manifest"
"""What a document produced by this surface calls itself."""

MANIFEST_SCHEMA_VERSION: Final[int] = 1
"""The version every manifest this surface emits is written against."""

PHASE: Final[int] = 34
"""The phase that built this."""

MANIFEST_NAME: Final[str] = "rest-manifest.json"
"""What the evidence document is called."""

EVIDENCE_DIRECTORY: Final[str] = "rest"
"""Which subdirectory of ``.globin/`` the evidence is published into."""

DIGEST_PREFIX: Final[str] = "sha256:"
"""What a digest is spelled with."""

DIGEST_KEY: Final[str] = "digest"
"""The manifest key holding the digest, excluded from the digest it holds."""


class TransportContractError(ValidationError):
    """The declared transport contract is absent, unreadable or self-contradictory.

    A :class:`~globin.errors.ValidationError` because a committed document that
    contradicts itself is bad data, which is what that class is for. Named
    separately so a caller can tell a contract fault from any other validation
    fault without reading the message.
    """


def render(document: Mapping[str, object]) -> str:
    """One manifest as canonical JSON.

    Args:
        document: The manifest.

    Returns:
        Sorted keys, no incidental whitespace, ASCII only, one trailing newline.
    """
    return (
        json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )


def digest(document: Mapping[str, object]) -> str:
    """One manifest's content digest.

    Args:
        document: The manifest, with or without its digest already set.

    Returns:
        :data:`DIGEST_PREFIX` followed by 64 lowercase hexadecimal characters,
        taken over everything except the digest itself.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def _tables(document: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    """Every table under one array-of-tables key.

    Args:
        document: The parsed contract.
        key: Which key.

    Returns:
        The rows, empty when the key is absent.

    Raises:
        TransportContractError: If the key holds something other than tables.
    """
    found = document.get(key, [])
    if not isinstance(found, list):
        msg = f"{key!r} in the transport contract is not an array of tables"
        raise TransportContractError(msg)
    for row in found:
        if not isinstance(row, dict):
            msg = f"a {key!r} entry in the transport contract is not a table"
            raise TransportContractError(msg)
    return tuple(found)


def _table(document: Mapping[str, object], key: str) -> Mapping[str, object]:
    """One table.

    Args:
        document: The parsed contract.
        key: Which key.

    Returns:
        The table.

    Raises:
        TransportContractError: If it is absent or is not a table.
    """
    found = document.get(key)
    if not isinstance(found, dict):
        msg = f"the transport contract declares no [{key}] table"
        raise TransportContractError(msg)
    return found


def _text(row: Mapping[str, object], key: str) -> str:
    """One required string field.

    Args:
        row: The table.
        key: Which key.

    Returns:
        The value.

    Raises:
        TransportContractError: If it is absent or is not a string.
    """
    found = row.get(key)
    if not isinstance(found, str):
        msg = f"the transport contract's {key!r} is {type(found).__name__}, not a string"
        raise TransportContractError(msg)
    return found


def _integer(row: Mapping[str, object], key: str) -> int:
    """One required integer field.

    Args:
        row: The table.
        key: Which key.

    Returns:
        The value.

    Raises:
        TransportContractError: If it is absent, a boolean, or not an integer.
    """
    found = row.get(key)
    if not isinstance(found, int) or isinstance(found, bool):
        msg = f"the transport contract's {key!r} is {type(found).__name__}, not an integer"
        raise TransportContractError(msg)
    return found


def _member[T](enumeration: type[T], value: str, *, field: str) -> T:
    """One enumeration member, by value.

    Args:
        enumeration: Which enumeration.
        value: The declared spelling.
        field: How to name the field in a message.

    Returns:
        The member.

    Raises:
        TransportContractError: If no member carries that value.
    """
    try:
        return enumeration(value)  # type: ignore[call-arg]
    except ValueError as fault:
        msg = f"the transport contract's {field} is {value!r}, which is not a permitted value"
        raise TransportContractError(msg) from fault


def _status(row: Mapping[str, object], *, field: str) -> StatusRule:
    """One status or exchange-code rule.

    Args:
        row: The declared table.
        field: How to name it in a message.

    Returns:
        The rule.

    Raises:
        TransportContractError: If a field is absent or the wrong type.
    """
    ambiguous = row.get("ambiguous_when_mutating")
    if not isinstance(ambiguous, bool):
        msg = f"a {field} declares no boolean ambiguous_when_mutating"
        raise TransportContractError(msg)
    return StatusRule(
        code=_integer(row, "code"),
        meaning=_text(row, "meaning") if "meaning" in row else _text(row, "name"),
        ambiguous_when_mutating=ambiguous,
        reason=_text(row, "reason"),
        source=_text(row, "source"),
    )


def parse_contract(text: str) -> TransportContract:
    """Turn the declared contract into values.

    Args:
        text: The document.

    Returns:
        The contract.

    Raises:
        TransportContractError: If the document is not TOML, or contradicts itself.

    ``tomllib.TOMLDecodeError`` is a ``ValueError`` rather than an ``Exception``
    subclass anybody expects, which Phase 030 found the hard way when a decode
    error escaped two handlers that had been written to catch it. It is caught
    explicitly here for that reason.
    """
    try:
        document = tomllib.loads(text)
    except (ValueError, TypeError) as fault:
        msg = f"the transport contract is not valid TOML: {fault}"
        raise TransportContractError(msg) from fault
    target = _table(document, "target")
    negotiation_row = _table(document, "negotiation")
    limits_row = _table(document, "limits")
    prohibitions_row = _table(document, "prohibitions")
    negotiation = NegotiationDeclaration(
        accept_header=_text(negotiation_row, "accept_header"),
        media_type_json=_text(negotiation_row, "media_type_json"),
        media_type_sbe=_text(negotiation_row, "media_type_sbe"),
        sbe_schema_header=_text(negotiation_row, "sbe_schema_header"),
        sbe_schema_format=_text(negotiation_row, "sbe_schema_format"),
        time_unit_header=_text(negotiation_row, "time_unit_header"),
        time_unit_microsecond=_text(negotiation_row, "time_unit_microsecond"),
        retry_after_header=_text(negotiation_row, "retry_after_header"),
        used_weight_prefix=_text(negotiation_row, "used_weight_prefix"),
        order_count_prefix=_text(negotiation_row, "order_count_prefix"),
        source=_text(negotiation_row, "source"),
        sbe_source=_text(negotiation_row, "sbe_source"),
    )
    probes = tuple(
        ProbeDescriptor(
            family=ProductFamily(_text(row, "family")),
            operation=_text(row, "operation"),
            method=_member(HttpMethod, _text(row, "method"), field="a probe method"),
            path=_text(row, "path"),
            capability=_member(
                SurfaceCapability, _text(row, "capability"), field="a probe capability"
            ),
            weight=_integer(row, "weight"),
            security=_text(row, "security"),
            notes=_text(row, "notes"),
            source=_text(row, "source"),
        )
        for row in _tables(document, "probe")
    )
    return TransportContract(
        negotiation=negotiation,
        probes=probes,
        statuses=tuple(_status(row, field="status rule") for row in _tables(document, "status")),
        exchange_codes=tuple(
            _status(row, field="exchange code rule") for row in _tables(document, "exchange_code")
        ),
        limits={key: value for key, value in limits_row.items() if isinstance(value, int)},
        prohibitions={
            key: value for key, value in prohibitions_row.items() if isinstance(value, bool)
        },
        phase=_integer(target, "phase"),
        observed_on=_text(target, "observed_on"),
    )


def read_contract(path: Path) -> TransportContract | None:
    """The declared contract, or nothing.

    Args:
        path: Where the document lives.

    Returns:
        The contract, or ``None`` when the document is absent or unreadable.

    Raises:
        TransportContractError: If the document is present and contradicts itself.

    The same distinction :mod:`globin.ports.api_reality` draws: ``None`` means *the
    declaration was not readable*, which a caller reports as unmeasured, while an
    exception means *the committed document is wrong*, which is a defect here.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_contract(text)


@dataclass(frozen=True, slots=True)
class TomlTransportContractSource:
    """The transport contract, read from the committed document.

    Args:
        path: Where the declaration lives.
    """

    path: Path

    def contract(self) -> TransportContract | None:
        """The contract, or nothing.

        Returns:
            The parsed contract, or ``None`` if the declaration is absent.

        Raises:
            TransportContractError: If the declaration is present and wrong.
        """
        return read_contract(self.path)


def build(
    *,
    run: Mapping[str, object],
    findings: Mapping[str, object],
    verdict: Mapping[str, object],
) -> dict[str, object]:
    """One manifest, with its digest set last.

    Args:
        run: What was read and what was exercised.
        findings: What was concluded.
        verdict: The single answer.

    Returns:
        The manifest, ready to render.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "phase": PHASE,
        "run": dict(run),
        "findings": dict(findings),
        "verdict": dict(verdict),
    }
    document[DIGEST_KEY] = digest(document)
    return document


def load(text: str) -> dict[str, object]:
    """Read a manifest back and confirm it was not edited.

    Args:
        text: The rendered manifest.

    Returns:
        The manifest.

    Raises:
        TransportContractError: If it is not JSON, carries no digest, or its digest
            does not match its content.
    """
    try:
        document = json.loads(text)
    except ValueError as fault:
        msg = f"the rest manifest is not valid JSON: {fault}"
        raise TransportContractError(msg) from fault
    if not isinstance(document, dict):
        msg = "the rest manifest is not an object"
        raise TransportContractError(msg)
    recorded = document.get(DIGEST_KEY)
    if not isinstance(recorded, str):
        msg = "the rest manifest carries no digest"
        raise TransportContractError(msg)
    if recorded != digest(document):
        msg = "the rest manifest was edited after its digest was taken"
        raise TransportContractError(msg)
    return dict(document)


def write(document: Mapping[str, object], *, directory: Path) -> Path:
    """Publish one manifest, refusing a rendering that is not reproducible.

    Args:
        document: The manifest.
        directory: Where it goes.

    Returns:
        The path written.

    Raises:
        TransportContractError: If two renderings of one manifest disagree.
    """
    rendered = render(document)
    if rendered != render(document):
        msg = "two renderings of the same rest manifest disagreed"
        raise TransportContractError(msg)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MANIFEST_NAME
    target.write_text(rendered, encoding="utf-8", newline="\n")
    return target
