"""The logging policy document and the logging code say the same thing.

``docs/LOGGING_POLICY.md`` is where an operator reads which field names are
redacted and what each severity means. The code is where the answer actually
comes from. Two statements of one rule diverge unless something compares them,
and a redaction list that is right in the code and stale in the document is the
worse of the two failures: it tells someone a field is safe when it is not.

The comparison is deliberately bidirectional. Checking only that the code's
fragments appear in the document would let the document list a fragment the code
does not implement, which reads as a promise and is not one.

What this file does *not* do is restate the rules. Whether redaction works is
``tests/unit`` and ``tests/property``; whether the document exists and is
well-formed is ``tests/contract/test_documentation_contract.py``.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.observability import ENVELOPE_KEYS
from globin.domain.observability import REDACTED, SENSITIVE_KEY_FRAGMENTS, Severity

POLICY_RELATIVE_PATH: Final[str] = "docs/LOGGING_POLICY.md"

#: A bullet whose entire content is one inline-code span, as the parsed sections
#: are written. Anything else in those sections is prose and is ignored.
CODE_BULLET_RE: Final[re.Pattern[str]] = re.compile(r"^- `([^`]+)`\s*$", re.MULTILINE)


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> str:
    """The logging policy document as written."""
    return (repo_root / POLICY_RELATIVE_PATH).read_text(encoding="utf-8")


def code_bullets(document: str, heading: str) -> tuple[str, ...]:
    """Return the inline-code bullet items listed under ``heading``.

    Args:
        document: The Markdown source.
        heading: The exact heading line, including its leading hashes.

    Returns:
        Every bullet of the form ``- `item``` between ``heading`` and the next
        heading, in document order.

    Raises:
        AssertionError: If ``heading`` does not appear exactly once.
    """
    occurrences = document.count(f"\n{heading}\n")
    assert occurrences == 1, f"expected one {heading!r} heading, found {occurrences}"

    body = document.split(f"\n{heading}\n", 1)[1]
    section = re.split(r"^#{1,6} ", body, maxsplit=1, flags=re.MULTILINE)[0]
    return tuple(match.group(1) for match in CODE_BULLET_RE.finditer(section))


def test_the_section_reader_finds_its_own_failing_case() -> None:
    """Guard the guard.

    Every assertion below is only as good as this parser. A reader that silently
    returned nothing would make each of them pass while comparing empty sets.
    """
    document = "\n".join(
        [
            "",
            "# Title",
            "",
            "### Items",
            "",
            "- `alpha`",
            "- not code",
            "- `beta`",
            "",
            "### Other",
            "",
            "- `gamma`",
            "",
        ]
    )

    assert code_bullets(document, "### Items") == ("alpha", "beta")
    assert code_bullets(document, "### Other") == ("gamma",)


def test_the_section_reader_refuses_a_heading_it_cannot_locate() -> None:
    """A renamed heading must fail loudly, not silently compare nothing."""
    with pytest.raises(AssertionError, match="expected one"):
        code_bullets("\n### Present\n\n- `alpha`\n", "### Absent")


def test_every_redacted_fragment_is_documented(policy: str) -> None:
    """An undocumented redaction rule is invisible to the person relying on it."""
    documented = set(code_bullets(policy, "### Redacted name fragments"))
    undocumented = sorted(set(SENSITIVE_KEY_FRAGMENTS) - documented)

    assert not undocumented, f"redacted in code but not documented: {undocumented}"


def test_the_document_promises_no_redaction_the_code_does_not_perform(policy: str) -> None:
    """The direction that matters more: a listed fragment is read as a guarantee."""
    documented = set(code_bullets(policy, "### Redacted name fragments"))
    unimplemented = sorted(documented - set(SENSITIVE_KEY_FRAGMENTS))

    assert not unimplemented, f"documented but not redacted: {unimplemented}"


def test_the_documented_fragments_are_listed_in_the_order_the_code_holds_them(
    policy: str,
) -> None:
    """Two lists that agree as sets and disagree in order are tedious to diff."""
    assert code_bullets(policy, "### Redacted name fragments") == SENSITIVE_KEY_FRAGMENTS


def test_the_envelope_keys_match_the_documented_record_shape(policy: str) -> None:
    """Order is part of the shape here, because the record is written in it."""
    assert code_bullets(policy, "### Envelope keys") == ENVELOPE_KEYS


@pytest.mark.parametrize("severity", list(Severity))
def test_every_severity_is_documented(policy: str, severity: Severity) -> None:
    """A level with no stated meaning gets used according to how the code felt."""
    assert f"`{severity.name}`" in policy


def test_the_document_describes_no_severity_the_code_lacks(policy: str) -> None:
    """Catches a level removed from the enumeration and left in the table."""
    tabled = {match.group(1) for match in re.finditer(r"^\| `([A-Z]+)` \|", policy, re.MULTILINE)}

    assert tabled == {severity.name for severity in Severity}


def test_the_redaction_placeholder_is_the_one_the_document_shows(policy: str) -> None:
    """Operators grep for this string; it has to be the one that gets written."""
    assert f"`{REDACTED}`" in policy
