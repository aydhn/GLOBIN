"""The serialization rules, asserted rather than written down.

``docs/SERIALIZATION_POLICY.md`` states how GLOBIN persists a value. This module
holds the document to the code, and the code to two decisions that are invisible
by construction:

*A deliberate absence.* :class:`~globin.domain.clock.MonotonicReading` has no
wire form on purpose, because its origin is undefined and a stored reading means
nothing to whoever reads it back. An absence cannot be seen in a diff, so it is
asserted here — otherwise the first person to want one adds it, reasonably, and
nothing objects.

*A deliberate copy.* ``tools/quality/evidence/manifest.py`` chose the envelope's
shape two phases before this module existed, and this module adopted it. Two
copies of a rule are drift unless a test compares them, which
``docs/engineering/SOURCE_OF_TRUTH.md`` states plainly, so they are compared
below.
"""

import inspect
from pathlib import Path
from typing import Final

import pytest

from globin.domain import serialization
from globin.domain.serialization import (
    SCHEMA_KEY,
    VERSION_KEY,
    Compatibility,
    Schema,
    identifier_storage_width,
)
from tests.support import markdown_prose, markdown_section
from tools.quality.evidence import manifest

POLICY_RELATIVE_PATH: Final[str] = "docs/SERIALIZATION_POLICY.md"


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> str:
    """The serialization policy document, as text."""
    return (repo_root / POLICY_RELATIVE_PATH).read_text(encoding="utf-8")


def _public(prefix: str) -> set[str]:
    """The subjects the module has a function of one kind for.

    Args:
        prefix: ``encode_`` or ``decode_``.

    Returns:
        The part of each name after the prefix.
    """
    return {
        name[len(prefix) :]
        for name, value in vars(serialization).items()
        if name.startswith(prefix) and inspect.isfunction(value)
    }


def test_every_wire_form_can_be_read_back() -> None:
    """A one-way encoder is a value written into a record nothing can recover.

    Structural rather than behavioural: the round trips themselves are in
    ``tests/property``. This catches the case those cannot — an encoder added
    with no reader at all, which no round-trip test would think to look for.
    """
    assert _public("encode_") == _public("decode_")


def test_a_monotonic_reading_has_no_wire_form() -> None:
    """The absence is the decision, so the absence is what is asserted.

    ``globin.domain.clock`` documents the reference point as undefined and
    readings from different processes as incomparable. Persisting one stores a
    number that cannot be compared with anything the reader has.
    """
    assert "monotonic_reading" not in _public("encode_")
    assert "MonotonicReading" not in serialization.__dict__


def test_the_policy_explains_why_a_monotonic_reading_is_not_stored(policy: str) -> None:
    """A rule with no reason recorded is a rule somebody will undo."""
    assert "monotonic" in markdown_prose(policy).lower()


def test_the_evidence_manifest_uses_the_envelope_this_module_defines() -> None:
    """The deliberate copy, compared.

    The quality tooling proved the envelope's shape first and cannot import
    ``globin`` — ``test_evidence_contract.py`` asserts it never does. That makes
    the two spellings a genuine duplication, and this is the test that stops them
    drifting.
    """
    document = manifest.build(run={}, gates={}, timing={})
    assert SCHEMA_KEY in document
    assert VERSION_KEY in document


def test_the_evidence_schema_name_satisfies_the_rule_for_a_schema_name() -> None:
    """The tooling's own name is a legal one under the rule this phase wrote.

    Had the rule been written without checking, the first schema GLOBIN ever
    shipped would have been outside it.
    """
    assert Schema(manifest.SCHEMA, manifest.SCHEMA_VERSION).name == manifest.SCHEMA


def test_the_policy_names_the_envelope_keys(policy: str) -> None:
    """The two keys are a wire contract, so the document quotes them exactly."""
    section = markdown_section(policy, "## The envelope")
    assert SCHEMA_KEY in section
    assert VERSION_KEY in section


def test_the_policy_states_the_identifier_column_width(policy: str) -> None:
    """``globin.domain.identifiers`` deferred the width to this phase by name.

    Bound to the derived value rather than restated, so registering a longer
    identifier kind fails here instead of leaving the document quietly wrong.
    """
    section = markdown_section(policy, "## Storage widths")
    assert str(identifier_storage_width()) in section


def test_the_policy_describes_every_compatibility_answer(policy: str) -> None:
    """Four members, and a document explaining three of them is a trap.

    Pinned to the subsection that classifies a change rather than to the whole
    of "Schema evolution": :func:`tests.support.markdown_section` stops at the
    next heading of any level, and the answers live in a table under one.
    """
    section = markdown_section(policy, "### Classifying a change")
    for member in Compatibility:
        assert member.value in section, f"{member.value} is not explained"


def test_the_policy_carries_no_placeholder_debt(policy: str) -> None:
    """The same rule every engineering document is held to."""
    prose = markdown_prose(policy).upper()
    for marker in ("TODO", "FIXME", "XXX", "TBD"):
        assert marker not in prose
