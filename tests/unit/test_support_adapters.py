"""Building a bundle: collection, limits, redaction, the archive and its validator.

The archive is written to a real temporary directory, because the properties that
matter — member ordering, normalised metadata, a digest that verifies against the
stored bytes, a partial file that never appears under the final name — are
properties of a file rather than of an object graph.

Redaction is exercised against a synthetic corpus. Nothing here is a real
credential; every value is shaped like one so that a plaintext survivor would be
findable by a substring search.
"""

import json
import zipfile
from pathlib import Path

import pytest

from globin.adapters.runtime_state import FileOperations
from globin.adapters.runtime_state import render as render_state_document
from globin.adapters.support import (
    COMPRESSION,
    MEMBER_PERMISSIONS,
    NORMALISED_TIMESTAMP,
    ZipArchiveWriter,
    digest_of,
)
from globin.application.observability import Logger
from globin.application.support import (
    TRUNCATION_NOTICE,
    UNPARSED_NOTICE,
    BundleBuilder,
    Candidate,
    redact_ndjson,
)
from globin.domain.observability import LogEvent
from globin.domain.support import ArtifactKind, BundleLimits, BundleManifest
from globin.errors import ValidationError
from globin.ports.support import ArchiveWriter, ArtifactSource

SECRETS = {
    "api_key": "AKIAFAKEKEYVALUE01",
    "authorization": "Bearer eyJfakefaketoken",
    "password": "hunter2-not-real",
    "signature": "9f8e7d6c5b4a3f2e1d0c",
    "session_id": "sess-abcdef012345",
    "private_key": "pk-fake-0123456789abcdef",
}
"""A corpus of credential-NAMED fields, so a survivor is findable by substring.

The values are deliberately *not* shaped like the real thing. Redaction here
matches field names, so the shape is incidental to what is being proven — and a
convincing private-key header committed to a public repository is a finding the
supply gate is right to raise, whatever the surrounding test says it is for.
The one file that legitimately carries such shapes is
`tests/unit/test_supply_secrets.py`, which has a recorded allowance because its
whole subject is whether each pattern fires.
"""


class Sink:
    """A log sink that keeps what it was given."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.events: list[LogEvent] = []

    def emit(self, event: LogEvent) -> None:
        """Keep one record."""
        self.events.append(event)


def limits(**overrides: int) -> BundleLimits:
    """Generous limits, with named fields overridden."""
    values = {
        "total_input_bytes": 1 << 22,
        "archive_bytes": 1 << 21,
        "member_bytes": 1 << 20,
        "log_bytes": 1 << 21,
        "member_count": 16,
    }
    values.update(overrides)
    return BundleLimits(**values)


def builder(destination: Path, **overrides: int) -> tuple[BundleBuilder, ZipArchiveWriter]:
    """A builder writing to the given path."""
    writer = ZipArchiveWriter(path=destination, operations=FileOperations())
    return (
        BundleBuilder(
            writer=writer,
            limits=limits(**overrides),
            logger=Logger(sink=Sink(), correlation_id="c"),
            render=render_state_document,
            digest=digest_of,
        ),
        writer,
    )


def candidate(
    member: str, payload: bytes, kind: ArtifactKind, *, redactable: bool = False
) -> Candidate:
    """One candidate returning fixed bytes."""
    return Candidate(member=member, kind=kind, read=lambda: payload, redactable=redactable)


def build(
    destination: Path, candidates: tuple[Candidate, ...], **overrides: int
) -> tuple[BundleManifest, str, int]:
    """Build one bundle and return what it produced."""
    subject, _writer = builder(destination, **overrides)
    return subject.build(candidates, manifest_member="manifest.json", report_member="report.txt")


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------


def test_members_are_written_in_lexicographic_order_whatever_order_they_arrive(
    tmp_path: Path,
) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    entries = writer.write(
        (("snapshot.json", b"s"), ("logs/globin.log", b"l"), ("manifest.json", b"m"))
    )
    assert [entry.member for entry in entries] == [
        "logs/globin.log",
        "manifest.json",
        "snapshot.json",
    ]


def test_every_member_carries_normalised_metadata(tmp_path: Path) -> None:
    """Timestamps are normalised rather than copied.

    A real modification time varies with when a file was touched, and on this host
    it would additionally record when an operator was at their machine.
    """
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    writer.write((("snapshot.json", b"{}"),))
    with zipfile.ZipFile(writer.temporary) as archive:
        for info in archive.infolist():
            assert info.date_time == NORMALISED_TIMESTAMP
            assert info.external_attr == MEMBER_PERMISSIONS
            assert info.compress_type == COMPRESSION
            assert info.create_system == 0


def test_the_same_logical_inputs_produce_identical_bytes(tmp_path: Path) -> None:
    payloads = (("snapshot.json", b'{"a":1}'), ("report.txt", b"hello"))
    first = ZipArchiveWriter(tmp_path / "one.zip", FileOperations())
    second = ZipArchiveWriter(tmp_path / "two.zip", FileOperations())
    first.write(payloads)
    second.write(tuple(reversed(payloads)))
    assert first.temporary.read_bytes() == second.temporary.read_bytes()


def test_an_unsafe_member_name_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    with pytest.raises(ValidationError):
        writer.write((("../escape", b"x"),))


def test_a_repeated_member_is_refused(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    with pytest.raises(ValidationError, match="same member twice"):
        writer.write((("snapshot.json", b"x"), ("snapshot.json", b"y")))


def test_two_members_differing_only_in_case_are_refused(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    with pytest.raises(ValidationError, match="only in case"):
        writer.write((("logs/A.log", b"x"), ("logs/a.log", b"y")))


def test_a_member_the_allowlist_does_not_produce_is_refused(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    with pytest.raises(ValidationError, match="allowlist"):
        writer.write((("unexpected.bin", b"x"),))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_correct_archive_validates(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    entries = writer.write((("snapshot.json", b"{}"), ("manifest.json", b"{}")))
    described = tuple(entry for entry in entries if entry.member != "manifest.json")
    manifest = BundleManifest(entries=described, limits=limits())
    assert writer.validate(manifest, manifest_member="manifest.json") == ()


def test_an_archive_missing_a_described_member_is_refused(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    entries = writer.write((("snapshot.json", b"{}"), ("manifest.json", b"{}")))
    from globin.domain.support import BundleEntry

    described = (
        *[entry for entry in entries if entry.member != "manifest.json"],
        BundleEntry("report.txt", ArtifactKind.REPORT, 1, digest_of(b"x")),
    )
    problems = writer.validate(
        BundleManifest(entries=tuple(sorted(described, key=lambda e: e.member))),
        manifest_member="manifest.json",
    )
    assert any("omits it" in problem for problem in problems)


def test_an_archive_holding_a_member_the_manifest_omits_is_refused(tmp_path: Path) -> None:
    """The shape a leak has: something written that nobody described."""
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    writer.write((("snapshot.json", b"{}"), ("report.txt", b"x"), ("manifest.json", b"{}")))
    entries = tuple(
        entry
        for entry in writer.write(
            (("snapshot.json", b"{}"), ("report.txt", b"x"), ("manifest.json", b"{}"))
        )
        if entry.member == "snapshot.json"
    )
    problems = writer.validate(BundleManifest(entries=entries), manifest_member="manifest.json")
    assert any("manifest omits it" in problem for problem in problems)


def test_a_wrong_digest_is_caught(tmp_path: Path) -> None:
    from globin.domain.support import BundleEntry

    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    writer.write((("snapshot.json", b"{}"), ("manifest.json", b"{}")))
    wrong = BundleEntry("snapshot.json", ArtifactKind.SNAPSHOT, 2, "sha256:" + "0" * 64)
    problems = writer.validate(BundleManifest(entries=(wrong,)), manifest_member="manifest.json")
    assert any("recorded digest" in problem for problem in problems)


def test_a_wrong_size_is_caught(tmp_path: Path) -> None:
    from globin.domain.support import BundleEntry

    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    writer.write((("snapshot.json", b"{}"), ("manifest.json", b"{}")))
    wrong = BundleEntry("snapshot.json", ArtifactKind.SNAPSHOT, 99, digest_of(b"{}"))
    problems = writer.validate(BundleManifest(entries=(wrong,)), manifest_member="manifest.json")
    assert any("stores" in problem for problem in problems)


def test_an_archive_without_its_own_manifest_is_refused(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    entries = writer.write((("snapshot.json", b"{}"),))
    problems = writer.validate(BundleManifest(entries=entries), manifest_member="manifest.json")
    assert any("its own manifest" in problem for problem in problems)


def test_an_unreadable_archive_is_reported_rather_than_raised(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    writer.temporary.write_bytes(b"not a zip at all")
    problems = writer.validate(BundleManifest(), manifest_member="manifest.json")
    assert any("could not be read back" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def test_a_published_bundle_leaves_no_partial_file(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    writer.write((("snapshot.json", b"{}"),))
    digest, size = writer.publish(1 << 20)
    assert writer.path.exists()
    assert not writer.temporary.exists()
    assert digest.startswith("sha256:")
    assert size > 0


def test_an_oversized_archive_is_refused_and_nothing_is_left_behind(tmp_path: Path) -> None:
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    writer.write((("snapshot.json", b"x" * 5000),))
    with pytest.raises(ValidationError, match="the limit is"):
        writer.publish(10)
    assert not writer.path.exists()
    assert not writer.temporary.exists()


def test_discarding_when_there_is_nothing_to_discard_is_quiet(tmp_path: Path) -> None:
    ZipArchiveWriter(tmp_path / "b.zip", FileOperations()).discard()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_every_sensitive_field_is_redacted_out_of_a_log() -> None:
    line = json.dumps({"event": "x", "fields": SECRETS})
    cleaned = redact_ndjson(line.encode("utf-8")).decode("utf-8")
    for value in SECRETS.values():
        assert value not in cleaned
    assert "[redacted]" in cleaned


def test_an_unparseable_line_is_dropped_rather_than_passed_through() -> None:
    """Dropped rather than passed through.

    This is the one place the module prefers losing a diagnostic to risking a
    credential: an unparseable line cannot be redacted by field name.
    """
    payload = b'{"a":1}\nnot json at all api_key=AKIAFAKEKEYVALUE01\n'
    cleaned = redact_ndjson(payload)
    assert b"AKIAFAKEKEYVALUE01" not in cleaned
    assert UNPARSED_NOTICE.rstrip(b"\n") in cleaned


def test_a_json_line_that_is_not_an_object_is_dropped() -> None:
    assert UNPARSED_NOTICE.rstrip(b"\n") in redact_ndjson(b"[1, 2, 3]\n")


def test_an_empty_log_stays_empty() -> None:
    assert redact_ndjson(b"") == b""


# ---------------------------------------------------------------------------
# Collection and limits
# ---------------------------------------------------------------------------


def test_a_bundle_collects_every_candidate_it_can(tmp_path: Path) -> None:
    manifest, digest, size = build(
        tmp_path / "b.zip",
        (
            candidate("snapshot.json", b'{"a":1}', ArtifactKind.SNAPSHOT),
            candidate("logs/globin.log", b'{"event":"x"}\n', ArtifactKind.LOG, redactable=True),
        ),
    )
    members = [entry.member for entry in manifest.entries]
    assert members == ["logs/globin.log", "report.txt", "snapshot.json"]
    assert digest.startswith("sha256:")
    assert size > 0


def test_the_manifest_describes_everything_except_itself(tmp_path: Path) -> None:
    manifest, _digest, _size = build(
        tmp_path / "b.zip", (candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),)
    )
    with zipfile.ZipFile(tmp_path / "b.zip") as archive:
        present = set(archive.namelist())
    described = {entry.member for entry in manifest.entries}
    assert present - described == {"manifest.json"}


def test_every_recorded_digest_verifies_against_the_stored_bytes(tmp_path: Path) -> None:
    build(tmp_path / "b.zip", (candidate("snapshot.json", b'{"a":1}', ArtifactKind.SNAPSHOT),))
    with zipfile.ZipFile(tmp_path / "b.zip") as archive:
        recorded = json.loads(archive.read("manifest.json"))
        for entry in recorded["entries"]:
            assert digest_of(archive.read(entry["member"])) == entry["digest"]


def test_an_unreadable_candidate_is_excluded_with_a_reason_and_no_path(tmp_path: Path) -> None:
    def refuse() -> bytes:
        message = r"C:\Users\someone\secret.log"
        raise FileNotFoundError(message)

    manifest, _digest, _size = build(
        tmp_path / "b.zip",
        (
            candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),
            Candidate("logs/globin.log", ArtifactKind.LOG, refuse),
        ),
    )
    assert manifest.exclusions
    assert all("someone" not in repr(item) for item in manifest.exclusions)


def test_a_directory_where_a_file_was_expected_is_excluded(tmp_path: Path) -> None:
    def refuse() -> bytes:
        raise IsADirectoryError

    manifest, _digest, _size = build(
        tmp_path / "b.zip",
        (
            candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),
            Candidate("logs/globin.log", ArtifactKind.LOG, refuse),
        ),
    )
    assert any(item.reason == "BUNDLE_NOT_REGULAR" for item in manifest.exclusions)


def test_an_oversized_member_is_truncated_and_says_so_in_its_own_content(
    tmp_path: Path,
) -> None:
    """The notice goes in the content, not only in the manifest.

    The person reading the file inside the archive is not necessarily the person
    who read the manifest, and a log that simply stops looks like a process that
    simply stopped.
    """
    manifest, _digest, _size = build(
        tmp_path / "b.zip",
        (candidate("snapshot.json", b"x" * 5000, ArtifactKind.SNAPSHOT),),
        member_bytes=1000,
    )
    assert manifest.entries[-1].size_bytes == 1000
    with zipfile.ZipFile(tmp_path / "b.zip") as archive:
        assert TRUNCATION_NOTICE in archive.read("snapshot.json")


def test_the_member_count_budget_excludes_the_rest(tmp_path: Path) -> None:
    manifest, _digest, _size = build(
        tmp_path / "b.zip",
        tuple(
            candidate(f"logs/globin.log.{index}", b"x", ArtifactKind.ROTATED_LOG)
            for index in range(1, 6)
        ),
        member_count=2,
    )
    assert any(item.reason == "BUNDLE_BUDGET_SPENT" for item in manifest.exclusions)


def test_a_candidate_with_an_unsafe_member_name_is_excluded(tmp_path: Path) -> None:
    manifest, _digest, _size = build(
        tmp_path / "b.zip",
        (
            candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),
            Candidate("../escape", ArtifactKind.LOG, lambda: b"x"),
        ),
    )
    assert any(item.reason == "BUNDLE_NAME_UNSAFE" for item in manifest.exclusions)


def test_the_snapshot_is_collected_before_the_logs_can_spend_the_budget(
    tmp_path: Path,
) -> None:
    """The budget is spent in a deliberate order.

    A collector reading logs first could produce a bundle saying a great deal
    about what happened and nothing about the machine it happened on.
    """
    manifest, _digest, _size = build(
        tmp_path / "b.zip",
        (
            candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),
            candidate("logs/globin.log", b"x" * 4000, ArtifactKind.LOG),
        ),
        total_input_bytes=4096,
        member_bytes=4096,
    )
    assert "snapshot.json" in [entry.member for entry in manifest.entries]


def test_a_bundle_that_fails_validation_is_not_published(tmp_path: Path) -> None:
    class Refusing(ZipArchiveWriter):
        """A writer whose validator always objects."""

        def validate(self, _manifest: BundleManifest, *, manifest_member: str) -> tuple[str, ...]:
            """Always report a disagreement."""
            assert manifest_member
            return ("arranged disagreement",)

    subject = BundleBuilder(
        writer=Refusing(tmp_path / "b.zip", FileOperations()),
        limits=limits(),
        logger=Logger(sink=Sink(), correlation_id="c"),
        render=render_state_document,
        digest=digest_of,
    )
    with pytest.raises(ValidationError, match="did not match its manifest"):
        subject.build(
            (candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),),
            manifest_member="manifest.json",
            report_member="report.txt",
        )
    assert not (tmp_path / "b.zip").exists()
    assert not (tmp_path / "b.zip.partial").exists()


def test_the_report_lists_what_was_included_and_what_was_not(tmp_path: Path) -> None:
    def refuse() -> bytes:
        raise FileNotFoundError

    build(
        tmp_path / "b.zip",
        (
            candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),
            Candidate("logs/globin.log", ArtifactKind.LOG, refuse),
        ),
    )
    with zipfile.ZipFile(tmp_path / "b.zip") as archive:
        report = archive.read("report.txt").decode("utf-8")
    assert "Included:" in report
    assert "snapshot.json" in report
    assert "BUNDLE_UNREADABLE" in report


def test_no_synthetic_secret_survives_into_a_finished_bundle(tmp_path: Path) -> None:
    """The end-to-end statement: nothing shaped like a credential leaves here."""
    log = "\n".join(json.dumps({"event": "e", "fields": SECRETS}) for _ in range(3))
    build(
        tmp_path / "b.zip",
        (
            candidate("snapshot.json", b"{}", ArtifactKind.SNAPSHOT),
            candidate("logs/globin.log", log.encode("utf-8"), ArtifactKind.LOG, redactable=True),
        ),
    )
    raw = (tmp_path / "b.zip").read_bytes()
    with zipfile.ZipFile(tmp_path / "b.zip") as archive:
        extracted = b"".join(archive.read(name) for name in archive.namelist())
    for value in SECRETS.values():
        assert value.encode("utf-8") not in raw
        assert value.encode("utf-8") not in extracted


# ---------------------------------------------------------------------------
# The ports
# ---------------------------------------------------------------------------


def test_the_archive_writer_answers_every_method_its_port_declares(tmp_path: Path) -> None:
    """Structural, not nominal: the adapter never names the protocol.

    `docs/TESTING_STRATEGY.md` prefers a hand-written double satisfying a
    `Protocol` to a mock, and that only works if the real implementation is held
    to the same shape. The protocols are not `runtime_checkable` — making them so
    would let an `isinstance` call claim a match on method names alone — so the
    surface is compared rather than asserted.
    """
    writer = ZipArchiveWriter(tmp_path / "b.zip", FileOperations())
    for name in ("write", "validate"):
        assert callable(getattr(writer, name)), name
        assert hasattr(ArchiveWriter, name), name


def test_the_artifact_source_port_declares_the_two_halves_a_collector_returns() -> None:
    """Both halves, and the second is not optional.

    A collector returning only what it accepted would make an exclusion
    indistinguishable from a file that never existed.
    """
    assert hasattr(ArtifactSource, "collect")
    assert ArtifactSource.collect.__doc__
