"""The declared ingestion cadence, read from its committed document.

Small on purpose. The policy is four numbers and a word; everything that decides
anything from them is in :mod:`globin.domain.ingestion`, which is pure and takes
the date as an argument.

**A second reader of this document lives under ``tools/``**, in the venue gate, and
shares no code with this one. That is the arrangement Phase 033 built for the
registry: two readers in different packages is how a disagreement becomes visible
rather than how one is created.
"""

import tomllib
from pathlib import Path
from typing import Final

from globin.domain.ingestion import CadenceRule, IngestionPolicy
from globin.errors import ValidationError

POLICY_PATH: Final[str] = "docs/engineering/ingestion-policy.toml"
"""Where the declared cadence lives, relative to the repository root."""


class IngestionPolicyError(ValidationError):
    """The declared cadence is unreadable or contradicts itself."""


def parse_policy(text: str) -> IngestionPolicy:
    """Turn the declared cadence into values.

    Args:
        text: The document.

    Returns:
        The policy.

    Raises:
        IngestionPolicyError: If the document is not TOML, or a required table or
            field is absent or the wrong type.

    ``tomllib.TOMLDecodeError`` is a ``ValueError``, which Phase 030 found the hard
    way when one escaped two handlers written to catch it. It is caught explicitly.
    """
    try:
        document = tomllib.loads(text)
    except (ValueError, TypeError) as fault:
        msg = f"the ingestion policy is not valid TOML: {fault}"
        raise IngestionPolicyError(msg) from fault
    default = document.get("default")
    if not isinstance(default, dict):
        msg = "the ingestion policy declares no [default] table"
        raise IngestionPolicyError(msg)
    rows = document.get("cadence", [])
    if not isinstance(rows, list):
        msg = "'cadence' in the ingestion policy is not an array of tables"
        raise IngestionPolicyError(msg)
    rules: list[CadenceRule] = []
    for row in rows:
        if not isinstance(row, dict):
            msg = "a 'cadence' entry in the ingestion policy is not a table"
            raise IngestionPolicyError(msg)
        rules.append(
            CadenceRule(
                regime=_text(row, "regime"),
                recheck_days=_integer(row, "recheck_days"),
                reason=_text(row, "reason"),
            )
        )
    return IngestionPolicy(
        rules=tuple(rules),
        default_days=_integer(default, "recheck_days"),
        default_reason=_text(default, "reason"),
    )


def _text(row: dict[str, object], key: str) -> str:
    """One required string field.

    Args:
        row: The table.
        key: Which key.

    Returns:
        The value.

    Raises:
        IngestionPolicyError: If it is absent or is not a string.
    """
    found = row.get(key)
    if not isinstance(found, str):
        msg = f"the ingestion policy's {key!r} is {type(found).__name__}, not a string"
        raise IngestionPolicyError(msg)
    return found


def _integer(row: dict[str, object], key: str) -> int:
    """One required integer field.

    Args:
        row: The table.
        key: Which key.

    Returns:
        The value.

    Raises:
        IngestionPolicyError: If it is absent, a boolean, or not an integer.
    """
    found = row.get(key)
    if not isinstance(found, int) or isinstance(found, bool):
        msg = f"the ingestion policy's {key!r} is {type(found).__name__}, not an integer"
        raise IngestionPolicyError(msg)
    return found


def read_policy(path: Path) -> IngestionPolicy | None:
    """The declared cadence, or nothing.

    Args:
        path: Where the document lives.

    Returns:
        The policy, or ``None`` when the document is absent or unreadable.

    Raises:
        IngestionPolicyError: If the document is present and contradicts itself.

    **An absent policy is not an absent cadence — it is an unmeasured one.** A
    caller that treated ``None`` as "nothing is stale" would turn a missing document
    into permission to trust every record for ever, which is the optimistic
    acceptance this phase exists to refuse. Callers report unmeasured instead.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_policy(text)
