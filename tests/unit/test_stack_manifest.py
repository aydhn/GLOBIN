"""The stack manifest: its shape, its digest, and what it refuses to read back.

The digest is the whole point of the document, so most of these are about the
ways a manifest can disagree with itself. A reader that accepted a document whose
digest did not cover its contents would make the digest decoration.
"""

import json

import pytest

from tools.quality.stack.manifest import (
    DIGEST_KEY,
    REASONS,
    SCHEMA,
    SCHEMA_VERSION,
    StackManifestError,
    build,
    digest,
    load,
    render,
)

RUN: dict[str, object] = {"commit": "0" * 40, "declaration": "docs/engineering/stack-contract.toml"}
FINDINGS: dict[str, object] = {"target": {"verdict": "passed", "problems": []}}
VERDICT: dict[str, object] = {"verdict": "passed", "reasons": []}


def a_manifest() -> dict[str, object]:
    """A well-formed manifest."""
    return build(run=RUN, findings=FINDINGS, verdict=VERDICT)


def test_a_manifest_carries_its_schema_version_and_phase() -> None:
    document = a_manifest()
    assert document["schema"] == SCHEMA
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["phase"] == 22


def test_a_manifest_round_trips() -> None:
    assert load(render(a_manifest())) == a_manifest()


def test_the_rendering_is_one_sorted_ascii_line_with_a_trailing_newline() -> None:
    """The shape every gate under `.globin/` writes.

    Sorted so two builders cannot disagree about key order; compact so no
    incidental whitespace enters the digest; ASCII so a Windows console with any
    active code page can print it.
    """
    rendered = render(a_manifest())
    assert rendered.endswith("\n")
    assert rendered.count("\n") == 1
    assert rendered.isascii()
    assert ", " not in rendered
    keys = list(json.loads(rendered))
    assert keys == sorted(keys)


def test_the_digest_covers_everything_except_itself() -> None:
    document = a_manifest()
    without = {key: value for key, value in document.items() if key != DIGEST_KEY}
    assert document[DIGEST_KEY] == digest(without)


def test_a_changed_field_changes_the_digest() -> None:
    """Guard the guard: a digest that ignored the content would pass every test above."""
    other = build(run=RUN, findings=FINDINGS, verdict={"verdict": "failed", "reasons": ["X"]})
    assert other[DIGEST_KEY] != a_manifest()[DIGEST_KEY]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("{", "not valid JSON", id="not JSON"),
        pytest.param("[]", "expected an object", id="a JSON array"),
        pytest.param('"a string"', "expected an object", id="a JSON string"),
    ],
)
def test_something_that_is_not_a_manifest_is_refused(text: str, expected: str) -> None:
    with pytest.raises(StackManifestError, match=expected):
        load(text)


def test_another_gates_manifest_is_refused_by_name() -> None:
    """Four refusals in a fixed order, each with its own message.

    A reader told only that the file is wrong has a diagnosis they cannot act on.
    """
    document = a_manifest()
    document["schema"] = "globin.wheels.manifest"
    document[DIGEST_KEY] = digest(document)
    with pytest.raises(StackManifestError, match="declares schema"):
        load(render(document))


def test_a_future_schema_version_is_refused_rather_than_read_anyway() -> None:
    document = a_manifest()
    document["schema_version"] = SCHEMA_VERSION + 1
    document[DIGEST_KEY] = digest(document)
    with pytest.raises(StackManifestError, match="this reader implements"):
        load(render(document))


def test_a_manifest_edited_since_it_was_written_is_refused() -> None:
    """The failure the digest exists to catch, with the digest left untouched."""
    document = a_manifest()
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    verdict["verdict"] = "passed but actually not"
    with pytest.raises(StackManifestError, match="digests to"):
        load(render(document))


def test_the_reason_set_is_closed_and_every_code_is_namespaced() -> None:
    """A reason nothing can produce is a claim about a check that does not exist.

    The prefix is what keeps one gate's codes from being mistaken for another's
    when they meet in the aggregate.
    """
    assert REASONS
    assert all(reason.startswith("STACK_") for reason in REASONS)
    assert all(reason.isupper() for reason in REASONS)
