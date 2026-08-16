"""The lock manifest: canonical, self-digesting, and refusing what it cannot verify.

The ninth copy of a solved shape, tested for the same properties as the other
eight. What matters is not that the code is novel but that this copy has not
drifted from the others: one sorted ASCII line, a digest covering everything but
itself, and six refusals that are what make the file evidence rather than a note.
"""

import json

import pytest

from tools.quality.lock.manifest import (
    DIGEST_KEY,
    DIGEST_PREFIX,
    PHASE,
    REASONS,
    SCHEMA,
    SCHEMA_VERSION,
    LockManifestError,
    build,
    digest,
    load,
    render,
)

RUN = {"repository": "aydhn/GLOBIN", "commit": "0" * 40, "mode": "check"}
FINDINGS = {"hashes": {"verdict": "passed", "problems": []}}
VERDICT = {"verdict": "passed", "reasons": []}


def manifest() -> dict[str, object]:
    """A well-formed manifest."""
    return build(run=RUN, findings=FINDINGS, verdict=VERDICT)


def test_the_manifest_declares_what_it_is() -> None:
    """A reader meeting the file cold must be able to tell what wrote it."""
    document = manifest()
    assert document["schema"] == SCHEMA == "globin.lock.manifest"
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["phase"] == PHASE == 20


def test_rendering_is_one_sorted_ascii_line() -> None:
    """Two writers must not be able to disagree about bytes."""
    text = render(manifest())
    assert text.endswith("\n")
    assert text.count("\n") == 1
    assert text.isascii()
    keys = list(json.loads(text))
    assert keys == sorted(keys)


def test_two_builds_of_one_run_are_byte_identical_whatever_the_input_order() -> None:
    """Determinism is what makes the gate's own comparison meaningful."""
    first = render(build(run=RUN, findings=FINDINGS, verdict=VERDICT))
    second = render(
        build(
            run=dict(reversed(list(RUN.items()))),
            findings=FINDINGS,
            verdict=VERDICT,
        )
    )
    assert first == second


def test_the_digest_covers_everything_except_itself() -> None:
    """Otherwise the digest would have to be computed from a document containing it."""
    document = manifest()
    recorded = document[DIGEST_KEY]
    assert isinstance(recorded, str)
    assert recorded.startswith(DIGEST_PREFIX)
    assert digest(document) == recorded
    without = {key: value for key, value in document.items() if key != DIGEST_KEY}
    assert digest(without) == recorded


@pytest.mark.parametrize(
    "section",
    [pytest.param("run", id="run"), pytest.param("findings", id="findings")],
)
def test_the_digest_changes_when_any_section_does(section: str) -> None:
    """A seal that did not move would seal nothing."""
    document = manifest()
    altered = dict(document)
    altered[section] = {"changed": True}
    assert digest(altered) != document[DIGEST_KEY]


def test_a_well_formed_manifest_reads_back() -> None:
    """The control for the refusals below."""
    assert load(render(manifest()))[DIGEST_KEY] == manifest()[DIGEST_KEY]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("{not json", "valid JSON", id="not-json"),
        pytest.param('["a"]', "expected an object", id="not-an-object"),
        pytest.param(
            json.dumps({"schema": "globin.wheels.manifest", "schema_version": 1}),
            "expected",
            id="another-gates-manifest",
        ),
        pytest.param(
            json.dumps({"schema": SCHEMA, "schema_version": SCHEMA_VERSION + 1}),
            "this reader implements",
            id="another-version",
        ),
    ],
)
def test_a_manifest_this_reader_cannot_verify_is_refused(text: str, expected: str) -> None:
    """Refused rather than read optimistically.

    The wheels-manifest case is the one worth naming: two gates write documents of
    the same shape into sibling directories, and reading one as the other would
    report a verdict about the wrong subject.
    """
    with pytest.raises(LockManifestError, match=expected):
        load(text)


def test_a_hand_edited_manifest_is_refused() -> None:
    """The whole reason the digest exists."""
    document = manifest()
    document["verdict"] = {"verdict": "passed", "reasons": ["invented"]}
    with pytest.raises(LockManifestError, match="digests to"):
        load(render(document))


def test_a_manifest_with_no_digest_is_refused_rather_than_treated_as_unsigned() -> None:
    """An absent seal is not a weaker seal."""
    document = {key: value for key, value in manifest().items() if key != DIGEST_KEY}
    with pytest.raises(LockManifestError, match="digests to"):
        load(render(document))


def test_every_reason_is_prefixed_and_upper_case() -> None:
    """The prefix is what lets a reader tell which gate emitted a code."""
    assert REASONS
    for reason in REASONS:
        assert reason.startswith("LOCK_"), reason
        assert reason.isupper(), reason
