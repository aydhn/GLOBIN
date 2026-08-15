"""The release manifest, its seal, and the assets it describes.

Two modules with one job between them: say what a release published, and make
the saying tamper-evident. Both are pure, so both are tested from literals.

**The digest is what makes this evidence rather than a note.** A manifest edited
by hand — to drop a finding, to turn a BLOCKED into a PASS before publishing it
as a release asset — must be refused on the way back in rather than read and
believed. Several tests below do exactly that edit and require the refusal.
"""

import json

import pytest

from tools.quality.release import assets, manifest
from tools.quality.release.plan import ReleaseError


def document() -> dict[str, object]:
    """A sealed manifest with something in every section."""
    return manifest.build(
        run={"repository": "aydhn/GLOBIN", "commit": "a" * 40, "version": "0.1.0"},
        acceptance={"total": 1, "blocking": 1},
        findings={"changelog": {"verdict": "passed", "problems": []}},
        capability={"tag_signing": {"state": manifest.SIGNING_UNAVAILABLE}},
        verdict={"verdict": "passed", "reasons": []},
    )


# ---------------------------------------------------------------------------
# Canonical rendering
# ---------------------------------------------------------------------------


def test_rendering_sorts_keys_and_adds_no_incidental_whitespace() -> None:
    """Two writers must not be able to disagree about bytes."""
    rendered = manifest.render({"b": 1, "a": 2})
    assert rendered == '{"a":2,"b":1}\n'


def test_rendering_is_ascii_only() -> None:
    """A Windows console cannot encode what its active code page lacks."""
    rendered = manifest.render({"note": "café"})
    assert rendered.isascii()


def test_key_order_in_the_source_does_not_change_the_bytes() -> None:
    assert manifest.render({"a": 1, "b": 2}) == manifest.render({"b": 2, "a": 1})


# ---------------------------------------------------------------------------
# The seal
# ---------------------------------------------------------------------------


def test_a_built_manifest_carries_a_digest_over_its_own_contents() -> None:
    built = document()
    assert built[manifest.DIGEST_KEY] == manifest.digest(built)
    assert str(built[manifest.DIGEST_KEY]).startswith(manifest.DIGEST_PREFIX)


def test_the_digest_ignores_the_field_that_holds_it() -> None:
    """Otherwise sealing would change the very thing the seal describes."""
    built = document()
    without = {key: value for key, value in built.items() if key != manifest.DIGEST_KEY}
    assert manifest.digest(built) == manifest.digest(without)


def test_the_schema_and_its_version_are_inside_the_sealed_payload() -> None:
    """So that a canonicalisation change cannot collide with an older digest."""
    built = document()
    assert built["schema"] == manifest.SCHEMA
    assert built["schema_version"] == manifest.SCHEMA_VERSION
    assert built["phase"] == manifest.PHASE


def test_two_builds_of_the_same_inputs_are_byte_identical() -> None:
    assert manifest.render(document()) == manifest.render(document())


# ---------------------------------------------------------------------------
# Reading one back
# ---------------------------------------------------------------------------


def test_a_sealed_manifest_reads_back() -> None:
    assert manifest.load(manifest.render(document()))["schema"] == manifest.SCHEMA


def test_text_that_is_not_json_is_refused() -> None:
    with pytest.raises(ReleaseError, match="not valid JSON"):
        manifest.load("{")


def test_json_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ReleaseError, match="must be a JSON object"):
        manifest.load("[1, 2]")


def test_another_gates_manifest_is_refused_by_name() -> None:
    """Another gate's manifest must fail on its schema, not on a missing key."""
    other = json.dumps({"schema": "globin.governance.manifest", "schema_version": 1})
    with pytest.raises(ReleaseError, match=r"not a globin\.release\.manifest"):
        manifest.load(other)


def test_a_manifest_of_another_schema_version_is_refused() -> None:
    built = document()
    built["schema_version"] = manifest.SCHEMA_VERSION + 1
    built[manifest.DIGEST_KEY] = manifest.digest(built)
    with pytest.raises(ReleaseError, match="Regenerate it"):
        manifest.load(manifest.render(built))


def test_a_manifest_edited_after_sealing_is_refused() -> None:
    """The tamper case: turn the verdict into a pass, then publish it."""
    built = document()
    built["verdict"] = {"verdict": "passed", "reasons": []}
    built["findings"] = {"changelog": {"verdict": "passed", "problems": []}}
    built["acceptance"] = {"total": 999}
    with pytest.raises(ReleaseError, match="does not describe its contents"):
        manifest.load(manifest.render(built))


def test_a_manifest_with_its_digest_removed_is_refused() -> None:
    built = document()
    del built[manifest.DIGEST_KEY]
    with pytest.raises(ReleaseError, match="does not describe its contents"):
        manifest.load(manifest.render(built))


# ---------------------------------------------------------------------------
# The closed vocabularies
# ---------------------------------------------------------------------------


def test_the_signing_states_are_three_and_distinguish_annotation_from_signature() -> None:
    """Describing a tag that merely carries a message as signed."""
    assert {
        manifest.SIGNING_ANNOTATED,
        manifest.SIGNING_SIGNED,
        manifest.SIGNING_UNAVAILABLE,
    } == manifest.SIGNING_STATES
    assert manifest.SIGNING_ANNOTATED != manifest.SIGNING_SIGNED
    assert "UNSIGNED" in manifest.SIGNING_ANNOTATED


def test_every_reason_code_is_prefixed_and_declared_once() -> None:
    assert all(reason.startswith("RELEASE_") for reason in manifest.REASONS)
    assert len(manifest.REASONS) == len({reason.lower() for reason in manifest.REASONS})


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def test_the_published_set_includes_the_checksum_file() -> None:
    names = assets.published_names()
    assert assets.CHECKSUM_FILE in names
    assert set(assets.PUBLISHED) < set(names)
    assert names == tuple(sorted(names))


def test_the_checksum_file_is_not_one_of_the_content_assets() -> None:
    """It describes them, so including it would make the set self-referential."""
    assert assets.CHECKSUM_FILE not in assets.PUBLISHED


def test_a_checksum_document_is_sorted_by_name_and_lowercase_hexadecimal() -> None:
    document = assets.checksum_document({"b.json": b"second", "a.json": b"first"})
    lines = document.splitlines()
    assert [line.split("  ")[1] for line in lines] == ["a.json", "b.json"]
    for line in lines:
        recorded = line.split("  ")[0]
        assert len(recorded) == 64
        assert recorded == recorded.lower()


def test_the_same_assets_in_a_different_order_produce_the_same_document() -> None:
    first = assets.checksum_document({"a.json": b"1", "b.json": b"2"})
    second = assets.checksum_document({"b.json": b"2", "a.json": b"1"})
    assert first == second


def test_different_content_produces_a_different_digest() -> None:
    """Guard the guard: a constant-returning checksum would pass the rest."""
    assert assets.checksum_document({"a": b"one"}) != assets.checksum_document({"a": b"two"})


def test_the_checksum_file_refuses_to_be_one_of_its_own_entries() -> None:
    """A file cannot carry its own digest: recording it would change it."""
    with pytest.raises(ReleaseError, match="cannot be one of its own entries"):
        assets.checksum_document({assets.CHECKSUM_FILE: b"anything"})


def test_a_missing_content_asset_is_reported() -> None:
    assert assets.missing({assets.MANIFEST_FILE: b"{}"}) == (
        assets.ACCEPTANCE_FILE,
        assets.SBOM_FILE,
    )


def test_a_complete_set_reports_nothing_missing() -> None:
    assert assets.missing(dict.fromkeys(assets.PUBLISHED, b"{}")) == ()
