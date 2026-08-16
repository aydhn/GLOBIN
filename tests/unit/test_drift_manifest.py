"""The drift manifest and the baseline: their shape, their digest, and what they refuse.

Two documents rather than one, and most of what is asserted here is that they can
be told apart. They live in the same directory, are written by the same package
and differ only in their schema string, so a reader pointed at the wrong one must
say which it found rather than fail somewhere further along.
"""

import json

import pytest

from tools.quality.drift import manifest

RUN = {"repository": "aydhn/GLOBIN", "commit": "a" * 40, "mode": "check"}
FINDINGS = {"policy": {"verdict": "passed", "problems": []}}
VERDICT = {"verdict": "passed", "reasons": []}
OBSERVATION = {"interpreter.version": "3.14.5", "host.system": "Windows"}


def built() -> dict[str, object]:
    """A manifest of the values above."""
    return manifest.build(run=RUN, findings=FINDINGS, verdict=VERDICT)


def baseline() -> dict[str, object]:
    """A baseline of the values above."""
    return manifest.build_baseline(commit="a" * 40, observation=OBSERVATION)


# ---------------------------------------------------------------------------
# Rendering, and the determinism the build-twice comparison depends on
# ---------------------------------------------------------------------------


def test_rendering_is_one_line_of_sorted_ascii_json() -> None:
    """One line so a diff of two runs is a diff of one line."""
    rendered = manifest.render(built())
    assert rendered.endswith("\n")
    assert rendered.count("\n") == 1
    assert rendered.isascii()


def test_key_order_in_the_input_does_not_change_the_rendering() -> None:
    """Determinism is what makes the gate's build-twice comparison mean anything.

    A rendering that depended on insertion order would fail that check for a
    reason having nothing to do with the host.
    """
    assert manifest.render({"a": 1, "b": 2}) == manifest.render({"b": 2, "a": 1})


def test_two_builds_of_the_same_inputs_are_byte_identical() -> None:
    """The property the gate asserts about itself on every run."""
    assert manifest.render(built()) == manifest.render(built())


# ---------------------------------------------------------------------------
# The digest
# ---------------------------------------------------------------------------


def test_the_digest_covers_everything_except_itself() -> None:
    """Otherwise stamping it would change what it is a digest of."""
    document = built()
    without = {key: value for key, value in document.items() if key != manifest.DIGEST_KEY}
    assert manifest.digest(document) == manifest.digest(without)
    assert document[manifest.DIGEST_KEY] == manifest.digest(without)


def test_the_digest_announces_its_algorithm() -> None:
    """A bare hex string is a claim nobody can check in ten years."""
    assert str(built()[manifest.DIGEST_KEY]).startswith(manifest.DIGEST_PREFIX)


def test_the_manifest_records_the_phase_that_introduced_it() -> None:
    """A tripwire on the frontier, in the sense `SOURCE_OF_TRUTH.md` permits a copy."""
    assert manifest.PHASE == 19


# ---------------------------------------------------------------------------
# Reading a manifest back
# ---------------------------------------------------------------------------


def test_a_manifest_round_trips() -> None:
    """The ordinary case, which has to work before any refusal below matters."""
    assert manifest.load(manifest.render(built())) == built()


def test_text_that_is_not_json_is_refused() -> None:
    """A truncated write is a file that exists and is not a manifest."""
    with pytest.raises(manifest.DriftManifestError, match="not valid JSON"):
        manifest.load("{")


def test_json_that_is_not_an_object_is_refused() -> None:
    """A list parses and is not a document."""
    with pytest.raises(manifest.DriftManifestError, match="expected an object"):
        manifest.load("[1, 2]")


def test_another_gate_s_manifest_is_refused() -> None:
    """A reader pointed at the wrong file should say so rather than read half of it."""
    document = built()
    document["schema"] = "globin.wheels.manifest"
    with pytest.raises(manifest.DriftManifestError, match="declares schema"):
        manifest.load(json.dumps(document))


def test_a_version_this_reader_does_not_implement_is_refused() -> None:
    """Refusing is what makes the version a compatibility contract rather than a label."""
    document = built()
    document["schema_version"] = manifest.SCHEMA_VERSION + 1
    with pytest.raises(manifest.DriftManifestError, match="implements"):
        manifest.load(json.dumps(document))


def test_content_edited_after_the_digest_was_taken_is_refused() -> None:
    """The failure the digest exists for: a document changed by hand after the fact."""
    document = built()
    document["phase"] = 20
    with pytest.raises(manifest.DriftManifestError, match="digests to"):
        manifest.load(json.dumps(document))


# ---------------------------------------------------------------------------
# The baseline, which is a different document in the same directory
# ---------------------------------------------------------------------------


def test_a_baseline_round_trips() -> None:
    """What `accept` writes is what `check` reads."""
    assert manifest.load_baseline(manifest.render(baseline())) == baseline()


def test_a_baseline_carries_the_commit_it_was_taken_at() -> None:
    """Nothing here records a clock, so the commit is what orders two baselines."""
    assert baseline()["commit"] == "a" * 40


def test_a_baseline_is_not_readable_as_a_manifest() -> None:
    """They differ by one string, and that string is the whole point of it being there."""
    with pytest.raises(manifest.DriftManifestError, match="declares schema"):
        manifest.load(manifest.render(baseline()))


def test_a_manifest_is_not_readable_as_a_baseline() -> None:
    """And the other direction, so neither can be silently accepted for the other."""
    with pytest.raises(manifest.DriftManifestError, match="drift baseline"):
        manifest.load_baseline(manifest.render(built()))


def test_a_baseline_edited_after_it_was_written_is_refused() -> None:
    """A half-written baseline would otherwise report drift that never happened."""
    document = baseline()
    observation = document["observation"]
    assert isinstance(observation, dict)
    observation = dict(observation)
    observation["interpreter.version"] = "3.14.9"
    document["observation"] = observation
    with pytest.raises(manifest.DriftManifestError, match="digests to"):
        manifest.load_baseline(json.dumps(document))
