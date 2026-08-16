"""The bootstrap manifest: canonical bytes, a sealing digest, and four refusals.

The shape is the one every gate under ``.globin`` already uses, so these
assertions are the ones ``tests/unit/test_runtime_manifest.py`` makes about that
one. Repeating a solved shape is cheap; a second shape that drifts is not.
"""

import json
import re
from pathlib import Path

import pytest

from globin.adapters.bootstrap import (
    DIGEST_KEY,
    DIGEST_PREFIX,
    MANIFEST_NAME,
    PHASE,
    SCHEMA,
    SCHEMA_VERSION,
    BootstrapManifestError,
    build,
    digest,
    load,
    render,
    write,
)
from globin.domain.bootstrap import (
    BootstrapOutcome,
    BootstrapReport,
    CheckOutcome,
    CheckStatus,
    ExitCode,
    RuntimePaths,
    check_identifiers,
)


def outcome(*, ready: bool = False, observed: dict[str, object] | None = None) -> BootstrapOutcome:
    """One run's conclusion, passing or refusing."""
    if ready:
        outcomes = tuple(
            CheckOutcome(identifier=name, status=CheckStatus.PASS, summary="fine")
            for name in check_identifiers()
        )
    else:
        outcomes = (
            CheckOutcome(
                identifier="project.root",
                status=CheckStatus.FAIL,
                summary="no project root was found",
                remediation="run it from inside a checkout",
            ),
        )
    return BootstrapOutcome(
        report=BootstrapReport(outcomes=outcomes),
        observed=observed if observed is not None else {"host": {"system": "Windows"}},
    )


def test_a_manifest_carries_its_schema_version_and_phase() -> None:
    """So that another manifest fed to this reader is refused by name."""
    built = build(outcome())
    assert built["schema"] == SCHEMA
    assert built["schema_version"] == SCHEMA_VERSION
    assert built["phase"] == PHASE == 21


def test_rendering_is_canonical_so_two_writers_cannot_disagree_about_bytes() -> None:
    """One line, sorted keys, no incidental whitespace."""
    rendered = render(build(outcome()))
    assert rendered.endswith("\n")
    assert rendered.count("\n") == 1, "one line, so a diff of two runs is a diff of one line"
    assert ", " not in rendered, "compact separators, or whitespace changes the digest"
    assert ": " not in rendered
    keys = list(json.loads(rendered))
    assert keys == sorted(keys), "keys are sorted, or the digest depends on insertion order"


def test_rendering_is_ascii_only() -> None:
    """A Windows console encodes with the active code page, so ASCII is the safe set."""
    rendered = render(build(outcome(observed={"note": "éğ中"})))
    assert rendered.isascii()


def test_the_digest_covers_everything_except_itself() -> None:
    """Which is what makes it a seal rather than a decoration."""
    built = build(outcome())
    without = {key: value for key, value in built.items() if key != DIGEST_KEY}
    assert built[DIGEST_KEY] == digest(without)
    assert str(built[DIGEST_KEY]).startswith(DIGEST_PREFIX)


def test_a_manifest_reads_back_as_what_was_written() -> None:
    """The control."""
    built = build(outcome())
    assert load(render(built)) == built


def test_something_that_is_not_json_is_refused() -> None:
    """Each refusal has its own message, because "this is wrong" is not a diagnosis."""
    with pytest.raises(BootstrapManifestError, match="not valid JSON"):
        load("{not json")


def test_something_that_is_not_an_object_is_refused() -> None:
    """A JSON array parses and is still not a manifest."""
    with pytest.raises(BootstrapManifestError, match="must be a JSON object"):
        load("[1, 2, 3]")


def test_a_manifest_from_another_schema_is_refused() -> None:
    """Refused by name rather than by a missing key."""
    built = dict(build(outcome()))
    built["schema"] = "globin.runtime.manifest"
    with pytest.raises(BootstrapManifestError, match=re.escape(f"not a {SCHEMA}")):
        load(json.dumps(built))


def test_a_manifest_from_another_version_is_refused_rather_than_read_anyway() -> None:
    """An older document is regenerated, not reinterpreted."""
    built = dict(build(outcome()))
    built["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(BootstrapManifestError, match="Regenerate it"):
        load(json.dumps(built))


def test_a_hand_edited_manifest_is_refused() -> None:
    """The whole point of sealing it."""
    built = dict(build(outcome()))
    built["phase"] = 22
    with pytest.raises(BootstrapManifestError, match="edited or truncated"):
        load(json.dumps(built))


def test_a_refusing_run_records_its_reason_codes() -> None:
    """Derived from the checks that did not pass, so the set cannot go stale."""
    built = build(outcome())
    verdict = built["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["reasons"] == ["BOOTSTRAP_PROJECT_ROOT"]
    assert verdict["ready"] is False
    assert verdict["exit_code"] == int(ExitCode.PATHS_UNUSABLE)
    assert verdict["fingerprint"] is None


def test_a_field_whose_name_looks_like_a_credential_is_redacted() -> None:
    """Redaction happens where the record is built, not where it is printed.

    Nothing in a bootstrap manifest should trip this today. The point is that it
    keeps being true when a later phase adds a section without reading the
    docstring that says so.
    """
    rendered = render(build(outcome(observed={"api_key": "sentinel-value-never-published"})))
    assert "sentinel-value-never-published" not in rendered
    assert "[redacted]" in rendered


def test_the_manifest_is_written_where_the_declared_tree_says(tmp_path: Path) -> None:
    """Under the evidence root, which is inside the project and git-ignored."""
    paths = RuntimePaths()
    recorded = write(outcome(), root=tmp_path, paths=paths)
    assert recorded.path == f"{paths.evidence}/{MANIFEST_NAME}"
    written = (tmp_path / paths.evidence / MANIFEST_NAME).read_text(encoding="utf-8")
    assert load(written)


def test_a_refused_run_still_writes_its_evidence(tmp_path: Path) -> None:
    """A gate that failed silently and left no artefact looks like one that never ran."""
    write(outcome(), root=tmp_path, paths=RuntimePaths())
    assert (tmp_path / RuntimePaths().evidence / MANIFEST_NAME).is_file()


def test_the_written_file_ends_with_one_newline_and_no_carriage_return(tmp_path: Path) -> None:
    """Written with an explicit newline, so Windows does not translate it."""
    write(outcome(), root=tmp_path, paths=RuntimePaths())
    raw = (tmp_path / RuntimePaths().evidence / MANIFEST_NAME).read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
