"""The GPU manifest: canonical bytes, a digest that seals them, and four refusals.

The shape is the one every gate under `.globin` already uses, so these assertions
are the ones `tests/unit/test_bootstrap_manifest.py` makes about that one.
Repeating a solved shape is cheap; a second shape that drifts is not.
"""

import json

import pytest

from tools.quality.gpu.manifest import (
    DIGEST_KEY,
    DIGEST_PREFIX,
    PHASE,
    REASONS,
    SCHEMA,
    SCHEMA_VERSION,
    GpuManifestError,
    build,
    digest,
    load,
    render,
)


def a_manifest(**overrides: object) -> dict[str, object]:
    """One manifest, built the way the gate builds it."""
    sections: dict[str, object] = {
        "run": {"repository": "aydhn/GLOBIN", "commit": "a" * 40},
        "findings": {"target": {"verdict": "passed", "problems": []}},
        "verdict": {"verdict": "passed", "reasons": []},
    }
    sections.update(overrides)
    return build(**sections)  # type: ignore[arg-type]


def test_a_manifest_carries_its_schema_version_and_phase() -> None:
    """So that another manifest fed to this reader is refused by name."""
    built = a_manifest()
    assert built["schema"] == SCHEMA
    assert built["schema_version"] == SCHEMA_VERSION
    assert built["phase"] == PHASE == 23


def test_rendering_is_canonical_so_two_writers_cannot_disagree_about_bytes() -> None:
    """One line, sorted keys, no incidental whitespace."""
    rendered = render(a_manifest())
    assert rendered.endswith("\n")
    assert rendered.count("\n") == 1, "one line, so a diff of two runs is a diff of one line"
    assert ", " not in rendered, "compact separators, or whitespace changes the digest"
    assert ": " not in rendered
    keys = list(json.loads(rendered))
    assert keys == sorted(keys), "keys are sorted, or the digest depends on insertion order"


def test_rendering_is_ascii_only() -> None:
    """A Windows console encodes with the active code page, so ASCII is the safe set."""
    rendered = render(a_manifest(run={"note": "éğ中"}))
    assert rendered.isascii()


def test_the_digest_covers_everything_except_itself() -> None:
    """Which is what makes it a seal rather than a decoration."""
    built = a_manifest()
    without = {key: value for key, value in built.items() if key != DIGEST_KEY}
    assert built[DIGEST_KEY] == digest(without)
    assert str(built[DIGEST_KEY]).startswith(DIGEST_PREFIX)


def test_two_builds_of_one_run_produce_identical_bytes() -> None:
    """Determinism, checked rather than claimed.

    The gate itself renders twice and compares; this proves the property the gate
    is relying on, so a failure there is about the run rather than about this.
    """
    assert render(a_manifest()) == render(a_manifest())


def test_a_manifest_reads_back() -> None:
    assert load(render(a_manifest()))["schema"] == SCHEMA


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("not json at all", "not valid JSON", id="not-json"),
        pytest.param("[1, 2, 3]", "expected an object", id="not-an-object"),
        pytest.param(
            json.dumps({"schema": "globin.other.manifest", "schema_version": 1}),
            "declares schema",
            id="another-schema",
        ),
        pytest.param(
            json.dumps({"schema": SCHEMA, "schema_version": 99}),
            "this reader implements",
            id="a-future-version",
        ),
    ],
)
def test_a_manifest_this_reader_cannot_vouch_for_is_refused(text: str, expected: str) -> None:
    """Each refusal path, so none of them is reachable only in theory.

    A future version is refused rather than read for the reason
    `SERIALIZATION_POLICY.md` gives: code that knew less than the writer cannot
    understand the record by ignoring the parts it does not recognise.
    """
    with pytest.raises(GpuManifestError, match=expected):
        load(text)


def test_a_hand_edited_manifest_is_refused() -> None:
    """The seal's whole purpose: content and digest must agree."""
    tampered = json.loads(render(a_manifest()))
    tampered["verdict"] = {"verdict": "passed", "reasons": ["invented"]}
    with pytest.raises(GpuManifestError, match="but its content digests to"):
        load(json.dumps(tampered))


def test_every_reason_is_prefixed_and_the_set_is_closed() -> None:
    """A reason code is a stable identifier a machine consumer may branch on."""
    assert len(REASONS) == 9
    assert all(reason.startswith("GPU_") for reason in REASONS)
    assert all(reason.isupper() for reason in REASONS)
