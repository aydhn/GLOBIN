"""The runtime manifest's canonical form, its digest, and what it refuses to read.

The manifest is evidence rather than a note, and the difference is entirely in
:func:`~tools.quality.runtime.manifest.load`: a document whose digest does not
describe its contents is refused rather than believed. These tests establish that
the refusal actually happens, for each of the four ways a document can be wrong.
"""

import json
import re

import pytest

from tools.quality.runtime import manifest
from tools.quality.runtime.plan import RuntimeBaselineError

SECTIONS: dict[str, dict[str, object]] = {
    "run": {"repository": "aydhn/GLOBIN", "commit": "0" * 40, "mode": "check"},
    "observed": {"interpreter": {"version": "3.14.5"}},
    "findings": {"host": {"verdict": "passed", "problems": []}},
    "capability": {"long_paths": {"state": "enabled"}},
    "verdict": {"verdict": "passed", "reasons": []},
}


def document() -> dict[str, object]:
    """A sealed manifest."""
    return manifest.build(**SECTIONS)


def test_a_manifest_carries_its_schema_name_version_and_phase() -> None:
    built = document()
    assert built["schema"] == manifest.SCHEMA
    assert built["schema_version"] == manifest.SCHEMA_VERSION
    assert built["phase"] == 17


def test_rendering_is_canonical_so_two_writers_cannot_disagree_about_bytes() -> None:
    rendered = manifest.render(document())
    assert rendered.endswith("\n")
    assert rendered.count("\n") == 1, "one line, so a diff of two runs is a diff of one line"
    assert ", " not in rendered, "compact separators, or whitespace changes the digest"
    assert ": " not in rendered
    keys = list(json.loads(rendered))
    assert keys == sorted(keys), "keys are sorted, or the digest depends on insertion order"


def test_rendering_is_ascii_only() -> None:
    """A Windows console encodes with the active code page.

    A character it cannot represent turns a report into a traceback.
    """
    rendered = manifest.render(
        manifest.build(**{**SECTIONS, "observed": {"note": "éğ中"}})  # type: ignore[arg-type]
    )
    assert rendered.isascii()


def test_the_digest_covers_everything_except_itself() -> None:
    built = document()
    without = {key: value for key, value in built.items() if key != manifest.DIGEST_KEY}
    assert built[manifest.DIGEST_KEY] == manifest.digest(without)
    assert str(built[manifest.DIGEST_KEY]).startswith(manifest.DIGEST_PREFIX)


def test_building_the_same_sections_twice_produces_identical_bytes() -> None:
    assert manifest.render(document()) == manifest.render(document())


def test_a_changed_section_changes_the_digest() -> None:
    """Otherwise the digest would establish nothing about the contents."""
    other = manifest.build(**{**SECTIONS, "verdict": {"verdict": "failed", "reasons": ["X"]}})  # type: ignore[arg-type]
    assert other[manifest.DIGEST_KEY] != document()[manifest.DIGEST_KEY]


def test_a_sealed_manifest_reads_back() -> None:
    assert manifest.load(manifest.render(document())) == document()


def test_text_that_is_not_json_is_refused() -> None:
    with pytest.raises(RuntimeBaselineError, match="not valid JSON"):
        manifest.load("{not json")


def test_json_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(RuntimeBaselineError, match="must be a JSON object"):
        manifest.load("[]")


def test_another_gate_s_manifest_is_refused_by_name() -> None:
    """A sibling gate's manifest fails on its schema name.

    Not on a missing key three levels down, which is what a reader would have to
    diagnose if the name were not checked first.
    """
    foreign = dict(document())
    foreign["schema"] = "globin.governance.manifest"
    with pytest.raises(RuntimeBaselineError, match=re.escape("not a globin.runtime.manifest")):
        manifest.load(json.dumps(foreign))


def test_a_document_from_another_schema_version_is_refused_rather_than_read() -> None:
    older = dict(document())
    older["schema_version"] = manifest.SCHEMA_VERSION + 1
    with pytest.raises(RuntimeBaselineError, match="Regenerate it"):
        manifest.load(json.dumps(older))


def test_a_hand_edited_manifest_is_refused() -> None:
    """The check that makes this evidence.

    Dropping a finding or flipping a verdict leaves a digest that no longer describes the
    document.
    """
    tampered = dict(document())
    tampered["verdict"] = {"verdict": "passed", "reasons": []}
    tampered["findings"] = {"host": {"verdict": "passed", "problems": []}, "extra": {}}
    with pytest.raises(RuntimeBaselineError, match="has been edited or truncated"):
        manifest.load(json.dumps(tampered))


def test_every_declared_reason_is_a_runtime_reason() -> None:
    """Reason codes are a closed set with one prefix.

    That is why a code from another gate cannot be mistaken for one of these.
    """
    assert manifest.REASONS
    assert all(reason.startswith("RUNTIME_") for reason in manifest.REASONS)


def test_reason_codes_are_upper_case_identifiers() -> None:
    """A code is for a machine.

    A sentence would change whenever somebody improved the wording.
    """
    assert all(
        reason.isupper() and reason.replace("_", "").isalnum() for reason in manifest.REASONS
    )
