"""The wheel-survey manifest: its shape, its digest, and what it refuses to read.

The digest is the part worth testing hardest. A manifest that verifies against
itself while its content has changed is worse than one with no digest at all,
because the second admits it proves nothing.
"""

import json

import pytest

from tools.quality.wheels import manifest

RUN: dict[str, object] = {"repository": "aydhn/GLOBIN", "commit": "0" * 40, "mode": "check"}
FINDINGS: dict[str, object] = {"target": {"verdict": "passed", "problems": []}}
VERDICT: dict[str, object] = {"verdict": "passed", "reasons": []}


def built() -> dict[str, object]:
    """A manifest of the shape the gate writes."""
    return manifest.build(run=RUN, findings=FINDINGS, verdict=VERDICT)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_the_manifest_carries_every_section_the_other_gates_carry() -> None:
    """A reader who has seen one of these has seen them all.

    Dropping a section here would make this the one gate whose evidence has to be
    read differently.
    """
    document = built()
    assert set(document) == {
        "schema",
        "schema_version",
        "phase",
        "run",
        "findings",
        "verdict",
        "digest",
    }


def test_the_manifest_names_the_phase_that_introduced_it() -> None:
    assert manifest.PHASE == 18


def test_the_schema_is_this_package_and_its_version_is_the_first() -> None:
    assert manifest.SCHEMA == "globin.wheels.manifest"
    assert manifest.SCHEMA_VERSION == 1


# ---------------------------------------------------------------------------
# Rendering and determinism
# ---------------------------------------------------------------------------


def test_rendering_is_one_line_of_sorted_ascii_json() -> None:
    rendered = manifest.render(built())
    assert rendered.endswith("\n")
    assert rendered.count("\n") == 1
    assert rendered.isascii()


def test_key_order_in_the_input_does_not_change_the_rendering() -> None:
    """Determinism is what makes the build-twice comparison mean anything.

    A rendering that depended on insertion order would fail that check for a
    reason having nothing to do with the survey.
    """
    forwards = manifest.build(run=RUN, findings=FINDINGS, verdict=VERDICT)
    backwards = manifest.build(
        run=dict(reversed(list(RUN.items()))), findings=FINDINGS, verdict=VERDICT
    )
    assert manifest.render(forwards) == manifest.render(backwards)


def test_the_digest_covers_everything_except_itself() -> None:
    document = built()
    without = {key: value for key, value in document.items() if key != manifest.DIGEST_KEY}
    assert manifest.digest(document) == manifest.digest(without)
    assert document[manifest.DIGEST_KEY] == manifest.digest(without)


def test_the_digest_announces_its_algorithm() -> None:
    assert str(built()[manifest.DIGEST_KEY]).startswith(manifest.DIGEST_PREFIX)


def test_changing_any_content_changes_the_digest() -> None:
    other = manifest.build(
        run=RUN,
        findings={"target": {"verdict": "failed", "problems": ["something"]}},
        verdict=VERDICT,
    )
    assert other[manifest.DIGEST_KEY] != built()[manifest.DIGEST_KEY]


# ---------------------------------------------------------------------------
# Reading one back
# ---------------------------------------------------------------------------


def test_a_manifest_this_module_wrote_reads_back() -> None:
    assert manifest.load(manifest.render(built())) == built()


def test_text_that_is_not_json_is_refused() -> None:
    with pytest.raises(manifest.WheelManifestError, match="not valid JSON"):
        manifest.load("{")


def test_json_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(manifest.WheelManifestError, match="expected an object"):
        manifest.load("[1, 2]")


def test_another_gate_s_manifest_is_refused() -> None:
    """A reader pointed at the wrong file should say so.

    Every gate writes to ``.globin/``, so reporting on a document it does not
    understand is a real possibility rather than a theoretical one.
    """
    document = built()
    document["schema"] = "globin.governance.manifest"
    with pytest.raises(manifest.WheelManifestError, match="declares schema"):
        manifest.load(json.dumps(document))


def test_a_version_this_reader_does_not_implement_is_refused() -> None:
    document = built()
    document["schema_version"] = 99
    with pytest.raises(manifest.WheelManifestError, match="implements"):
        manifest.load(json.dumps(document))


def test_content_edited_after_the_digest_was_taken_is_refused() -> None:
    """The failure the digest exists for: a manifest changed by hand after the fact."""
    document = built()
    document["phase"] = 20
    with pytest.raises(manifest.WheelManifestError, match="digests to"):
        manifest.load(json.dumps(document))


def test_a_manifest_with_no_digest_at_all_is_refused() -> None:
    document = built()
    del document[manifest.DIGEST_KEY]
    with pytest.raises(manifest.WheelManifestError, match="digests to"):
        manifest.load(json.dumps(document))


# ---------------------------------------------------------------------------
# The reason vocabulary
# ---------------------------------------------------------------------------


def test_every_reason_is_a_wheels_reason_and_is_ascii() -> None:
    """A reason code is read out of a manifest by something that did not write it.

    A stray prefix or a non-ASCII character makes that harder for no benefit.
    """
    for reason in manifest.REASONS:
        assert reason.startswith("WHEELS_")
        assert reason.isascii()
        assert reason == reason.upper()


def test_the_reason_set_is_closed_and_has_no_duplicates() -> None:
    declared = [
        value
        for name, value in vars(manifest).items()
        if name.startswith("REASON_") and isinstance(value, str)
    ]
    assert sorted(declared) == sorted(manifest.REASONS)
    assert len(declared) == len(set(declared))
