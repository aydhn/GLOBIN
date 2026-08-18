"""The two things a configuration report is written to, and read back from.

``test_config_evidence.py`` owns the projection — who set what, and how two runs
differ. This owns the artefacts: the manifest that goes into the repository's
evidence tree, and the snapshot that goes into the machine's state tree.

Nothing here writes outside ``tmp_path``. The state store is a hand-written double
satisfying the port, so a test never touches a real user profile.
"""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from globin.adapters.config_evidence import (
    DIGEST_KEY,
    EVIDENCE_DIRECTORY,
    MANIFEST_NAME,
    SCHEMA,
    SCHEMA_VERSION,
    SNAPSHOT_FILE,
    ConfigManifestError,
    build,
    digest,
    load,
    publish_snapshot,
    read_snapshot,
    render,
    write,
)
from globin.domain.bootstrap import RuntimePaths
from globin.domain.config_evidence import (
    CONFIG_SCHEMA_VERSION,
    ConfigSnapshot,
    compare,
    provenance_of,
    snapshot_of,
)
from globin.domain.configuration import (
    MIN_SEVERITY,
    config_fingerprint,
    config_layer,
    default_layer,
    resolve,
)
from globin.domain.runtime_state import RuntimeArea
from globin.errors import ConfigurationError

DOCUMENT_ORIGIN: str = "config/profiles/paper.toml"


class RecordingStore:
    """A :class:`~globin.ports.runtime_state.StateStore` that keeps documents in memory.

    A hand-written double satisfying the protocol rather than a mock, which is
    ``TESTING_STRATEGY.md``'s default. It records what was published so that a test
    can assert *where* as well as *what*.
    """

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.documents: dict[tuple[RuntimeArea, str], dict[str, object]] = {}

    def publish(self, area: RuntimeArea, name: str, document: Mapping[str, object]) -> None:
        """Record one document."""
        self.documents[(area, name)] = json.loads(json.dumps(dict(document)))

    def read(self, area: RuntimeArea, name: str) -> Mapping[str, object] | None:
        """Return a recorded document, or ``None``."""
        return self.documents.get((area, name))

    def discard(self, area: RuntimeArea, name: str) -> None:
        """Forget one document."""
        self.documents.pop((area, name), None)


def _snapshot(severity: str = "INFO", *, profile: str = "paper") -> ConfigSnapshot:
    """A snapshot of the defaults with one document over them."""
    layers = (default_layer(), config_layer(DOCUMENT_ORIGIN, {MIN_SEVERITY: severity}))
    return snapshot_of(
        provenance_of(layers), profile=profile, semantic=config_fingerprint(resolve(layers))
    )


def _manifest() -> dict[str, object]:
    """A manifest describing one resolution."""
    snapshot = _snapshot()
    return build(
        profile=snapshot.profile,
        provenance=provenance_of(
            (default_layer(), config_layer(DOCUMENT_ORIGIN, {MIN_SEVERITY: "INFO"}))
        ).as_record(),
        fingerprints={"semantic": snapshot.semantic, "evidence": snapshot.evidence},
        validation={"bound": True, "problem": ""},
        drift=compare(None, snapshot).as_record(),
    )


# ---------------------------------------------------------------------------
# Rendering and digesting
# ---------------------------------------------------------------------------


def test_a_rendering_is_canonical_and_ends_in_one_newline() -> None:
    """The shape every manifest in this repository shares, so two can be compared."""
    rendered = render({"b": 1, "a": 2})
    assert rendered == '{"a":2,"b":1}\n'


def test_two_renderings_of_one_document_agree() -> None:
    """A document that does not render deterministically has a digest identifying nothing."""
    document = _manifest()
    assert render(document) == render(document)


def test_the_digest_excludes_itself() -> None:
    """Otherwise it would have to be computed over a value that depends on it."""
    document = _manifest()
    without = {key: value for key, value in document.items() if key != DIGEST_KEY}
    assert digest(document) == digest(without)


def test_the_manifest_declares_what_it_is() -> None:
    """A reader who found the file alone must be able to tell what produced it."""
    document = _manifest()
    assert document["schema"] == SCHEMA
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["phase"] == 30


def test_the_manifest_carries_no_timestamp() -> None:
    """It is compared between runs, and a clock reading would make every run differ."""
    rendered = render(_manifest())
    for word in ("timestamp", "generated_at", "recorded_at", "when"):
        assert word not in rendered


def test_a_manifest_round_trips() -> None:
    """The positive case, so the refusals below are not vacuously satisfied."""
    document = _manifest()
    assert load(render(document)) == document


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("not json at all", "not JSON", id="not-json"),
        pytest.param("[1, 2]", "not an object", id="not-an-object"),
        pytest.param('{"schema": "other"}', "rather than", id="another-schema"),
    ],
)
def test_a_document_that_is_not_this_manifest_is_refused(text: str, expected: str) -> None:
    """Each refusal names what is wrong rather than reporting a generic failure."""
    with pytest.raises(ConfigManifestError, match=expected):
        load(text)


def test_a_manifest_from_another_version_is_refused() -> None:
    """Partially understanding a document written to a different shape is worse than refusing."""
    document = dict(_manifest())
    document["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ConfigManifestError, match="version"):
        load(render(document))


def test_a_manifest_that_has_been_edited_is_refused() -> None:
    """The digest is what makes a recorded document evidence rather than a claim."""
    document = dict(_manifest())
    document["profile"] = "live"
    with pytest.raises(ConfigManifestError, match="own digest"):
        load(render(document))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_the_manifest_is_written_inside_the_project(tmp_path: Path) -> None:
    """Nothing is written outside the project root, ever."""
    recorded = write(_manifest(), root=tmp_path, paths=RuntimePaths())
    target = tmp_path / RuntimePaths().artifacts / EVIDENCE_DIRECTORY / MANIFEST_NAME
    assert target.is_file()
    assert recorded.path is not None


def test_what_was_written_loads_back(tmp_path: Path) -> None:
    """A file that cannot be read back is not evidence of anything."""
    document = _manifest()
    write(document, root=tmp_path, paths=RuntimePaths())
    target = tmp_path / RuntimePaths().artifacts / EVIDENCE_DIRECTORY / MANIFEST_NAME
    assert load(target.read_text(encoding="utf-8")) == document


def test_writing_twice_produces_the_same_bytes(tmp_path: Path) -> None:
    """Byte stability is what lets two runs be compared without parsing either."""
    document = _manifest()
    write(document, root=tmp_path, paths=RuntimePaths())
    target = tmp_path / RuntimePaths().artifacts / EVIDENCE_DIRECTORY / MANIFEST_NAME
    first = target.read_bytes()
    write(document, root=tmp_path, paths=RuntimePaths())
    assert target.read_bytes() == first


def test_no_credential_shaped_value_reaches_the_written_file(tmp_path: Path) -> None:
    """Asserted over the bytes on disk, which is where a leak would actually be."""
    secret = "sk-live-thisisnotarealkey"  # noqa: S105 -- a fixture; the point is it never appears
    layers = (default_layer(), config_layer(DOCUMENT_ORIGIN, {"venue.api_key": secret}))
    snapshot = snapshot_of(
        provenance_of(layers), profile="paper", semantic=config_fingerprint(resolve(layers))
    )
    document = build(
        profile=snapshot.profile,
        provenance=provenance_of(layers).as_record(),
        fingerprints={"semantic": snapshot.semantic, "evidence": snapshot.evidence},
        validation={"bound": False, "problem": "unknown setting"},
        drift=compare(None, snapshot).as_record(),
    )
    write(document, root=tmp_path, paths=RuntimePaths())
    target = tmp_path / RuntimePaths().artifacts / EVIDENCE_DIRECTORY / MANIFEST_NAME
    assert secret not in target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The baseline
# ---------------------------------------------------------------------------


def test_no_recorded_snapshot_reads_as_none() -> None:
    """A first run has no baseline, which the caller turns into `unmeasured`."""
    assert read_snapshot(RecordingStore()) is None


def test_a_published_snapshot_reads_back_unchanged() -> None:
    """The round trip drift depends on, exercised through the port rather than the file."""
    store = RecordingStore()
    publish_snapshot(store, _snapshot())
    restored = read_snapshot(store)
    assert restored is not None
    assert not compare(restored, _snapshot()).moved


def test_the_baseline_goes_in_the_state_area() -> None:
    """State about this machine, not evidence about this repository."""
    store = RecordingStore()
    publish_snapshot(store, _snapshot())
    assert (RuntimeArea.STATE, SNAPSHOT_FILE) in store.documents


def test_a_published_snapshot_carries_no_display() -> None:
    """The least it can hold while still answering "did this change"."""
    store = RecordingStore()
    publish_snapshot(store, _snapshot())
    assert "INFO" not in json.dumps(store.documents[(RuntimeArea.STATE, SNAPSHOT_FILE)])


def test_a_snapshot_recorded_under_another_contract_is_refused() -> None:
    """A baseline nobody can read is reported, never treated as absent."""
    store = RecordingStore()
    publish_snapshot(store, _snapshot())
    store.documents[(RuntimeArea.STATE, SNAPSHOT_FILE)]["schema_version"] = (
        CONFIG_SCHEMA_VERSION + 1
    )
    with pytest.raises(ConfigurationError, match="config_schema_version"):
        read_snapshot(store)


def test_a_snapshot_whose_fields_are_not_a_list_is_refused() -> None:
    """No baseline and a baseline nobody can read call for different actions."""
    store = RecordingStore()
    publish_snapshot(store, _snapshot())
    store.documents[(RuntimeArea.STATE, SNAPSHOT_FILE)]["fields"] = {"not": "a list"}
    with pytest.raises(ConfigurationError, match="not a list"):
        read_snapshot(store)
