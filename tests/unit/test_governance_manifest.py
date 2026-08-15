"""The governance manifest: canonical bytes, a digest that covers them, and a reader that refuses.

The shape is the one the evidence, execution, supply and workflow manifests share,
so these tests are deliberately the same tests. What they establish is that the
fourth copy of a solved solution really is the solved solution, rather than
something that resembles it.
"""

import json

import pytest

from tools.quality.governance import manifest
from tools.quality.governance.plan import GovernanceError


def document() -> dict[str, object]:
    """A sealed manifest, built the way the gate builds one."""
    return manifest.build(
        run={"repository": "owner/name", "commit": "0" * 40},
        ownership={"location": ".github/CODEOWNERS", "owners": ["@owner"]},
        findings={"required_files": {"verdict": "passed", "problems": []}},
        capability={"code_owner_review": {"state": "NOT_APPLICABLE", "reason": "why"}},
        verdict={"verdict": "passed", "reasons": []},
    )


def test_two_renderings_of_one_document_are_byte_identical() -> None:
    """The property the digest is worth nothing without."""
    assert manifest.render(document()) == manifest.render(document())


def test_the_rendering_is_canonical_and_ascii_only() -> None:
    """Everything a gate writes must be ASCII, and sorted so two writers agree.

    A Windows console encodes its output with the active code page, and a
    character it cannot represent turns a report into a traceback.
    """
    text = manifest.render(document())
    assert text.endswith("\n")
    assert text.count("\n") == 1, "one line, so a diff is a diff rather than a reflow"
    assert text.isascii()
    keys = list(json.loads(text))
    assert keys == sorted(keys)


def test_the_digest_covers_everything_except_itself() -> None:
    sealed = document()
    assert sealed[manifest.DIGEST_KEY] == manifest.digest(sealed)
    assert manifest.digest(sealed) == manifest.digest(
        {key: value for key, value in sealed.items() if key != manifest.DIGEST_KEY}
    )


def test_a_manifest_edited_by_hand_is_refused_rather_than_believed() -> None:
    """This is what makes the file evidence rather than a note.

    Dropping a finding or flipping a verdict leaves the digest describing a
    document that no longer exists.
    """
    tampered = document()
    tampered["verdict"] = {"verdict": "passed", "reasons": ["invented"]}
    with pytest.raises(GovernanceError, match="digest"):
        manifest.load(manifest.render(tampered))


def test_a_well_formed_manifest_round_trips() -> None:
    assert manifest.load(manifest.render(document()))["schema"] == manifest.SCHEMA


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("{", "not valid JSON", id="not json"),
        pytest.param("[]", "must be a JSON object", id="not an object"),
        pytest.param('{"schema":"globin.supply.manifest"}', "not a globin", id="another schema"),
    ],
)
def test_a_document_that_is_not_this_manifest_is_refused_by_name(text: str, expected: str) -> None:
    with pytest.raises(GovernanceError, match=expected):
        manifest.load(text)


def test_a_manifest_from_a_different_schema_version_is_refused() -> None:
    """Reading it anyway would be guessing at a shape that has changed."""
    older = document()
    older["schema_version"] = manifest.SCHEMA_VERSION + 1
    older[manifest.DIGEST_KEY] = manifest.digest(older)
    with pytest.raises(GovernanceError, match="version"):
        manifest.load(manifest.render(older))


def test_every_reason_code_is_declared_and_spelled_consistently() -> None:
    """A new failure mode must not arrive with an undeclared name.

    Reflection rather than a second list, because a hand-maintained copy is
    exactly what this asserts against.
    """
    declared = {
        value
        for name, value in vars(manifest).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert declared == set(manifest.REASONS)
    for code in manifest.REASONS:
        assert code.startswith("GOVERNANCE_"), code
        assert code.isupper(), code
