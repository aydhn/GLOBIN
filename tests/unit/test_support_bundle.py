"""The pure bundle judgement: member names, limits, entries and the manifest.

Path safety is the subject, and it is tested here rather than against a real
filesystem because the interesting cases — a member escaping the root, two names
colliding under a case-insensitive comparison, a reserved device name — are exactly
the ones that are awkward to reproduce by making files, and impossible to reproduce
on the wrong platform.
"""

import pytest

from globin.domain.support import (
    BUNDLE_SCHEMA_VERSION,
    EXCLUDED_TOO_LARGE,
    EXCLUSION_REASONS,
    MAXIMUM_MEMBER_LENGTH,
    RESERVED_STEMS,
    ArtifactKind,
    BundleEntry,
    BundleExclusion,
    BundleLimits,
    BundleManifest,
    member_problems,
    safe_member_name,
)
from globin.errors import ValidationError

DIGEST = "sha256:" + "a" * 64


def limits(**overrides: int) -> BundleLimits:
    """A valid set of limits, with named fields overridden."""
    values = {
        "total_input_bytes": 1 << 26,
        "archive_bytes": 1 << 25,
        "member_bytes": 1 << 23,
        "log_bytes": 1 << 24,
        "member_count": 64,
    }
    values.update(overrides)
    return BundleLimits(**values)


def entry(member: str = "snapshot.json", size: int = 10) -> BundleEntry:
    """One manifest entry."""
    return BundleEntry(member, ArtifactKind.SNAPSHOT, size, DIGEST)


# ---------------------------------------------------------------------------
# Member names, and the six refusals
# ---------------------------------------------------------------------------


def test_a_normal_member_name_is_accepted() -> None:
    assert member_problems("logs/globin.log") == ()
    assert member_problems("snapshot.json") == ()


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        pytest.param("", "not empty", id="empty"),
        pytest.param("x" * (MAXIMUM_MEMBER_LENGTH + 1), "longer than", id="too-long"),
        pytest.param("logs\\globin.log", "backslash", id="backslash"),
        pytest.param("/etc/passwd", "absolute", id="leading-slash"),
        pytest.param("C:/Windows/system.ini", "drive", id="drive-letter"),
        pytest.param("../../secrets", "parent segment", id="traversal"),
        pytest.param("logs//globin.log", "parent segment", id="empty-segment"),
        pytest.param("logs/./globin.log", "parent segment", id="current-segment"),
        pytest.param("logs/con.txt", "reserved", id="reserved-stem"),
        pytest.param("logs/nul", "reserved", id="bare-reserved"),
        pytest.param("logs/globin.log ", "dot or a space", id="trailing-space"),
        pytest.param("logs/globin.", "dot or a space", id="trailing-dot"),
        pytest.param("logs/glo\x01bin.log", "control character", id="control-character"),
    ],
)
def test_an_unsafe_member_name_is_refused(member: str, expected: str) -> None:
    """Each row is a real extraction failure rather than a style preference."""
    problems = member_problems(member)
    assert problems
    assert any(expected in problem for problem in problems)


def test_every_reserved_stem_is_caught_with_and_without_an_extension() -> None:
    """`con.txt` is reserved as surely as `con` is."""
    for stem in RESERVED_STEMS:
        assert member_problems(f"logs/{stem}")
        assert member_problems(f"logs/{stem}.txt")


def test_a_member_name_is_built_from_two_known_good_pieces() -> None:
    assert safe_member_name("logs", "globin.log") == "logs/globin.log"
    assert safe_member_name("", "snapshot.json") == "snapshot.json"


def test_building_an_unsafe_member_name_raises_rather_than_returning_one() -> None:
    with pytest.raises(ValidationError, match="no safe member name"):
        safe_member_name("logs", "../escape")


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def test_a_valid_limit_set_is_accepted() -> None:
    assert limits().member_count == 64


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        pytest.param({"archive_bytes": 100}, "archive_bytes is between", id="archive-too-small"),
        pytest.param({"archive_bytes": 1 << 40}, "archive_bytes is between", id="archive-too-big"),
        pytest.param({"member_count": 0}, "member_count is between", id="no-members"),
        pytest.param({"member_count": 100_000}, "member_count is between", id="too-many-members"),
        pytest.param({"total_input_bytes": 0}, "positive count", id="zero-total"),
        pytest.param({"log_bytes": -1}, "positive count", id="negative-log"),
    ],
)
def test_an_impossible_limit_set_is_refused(override: dict[str, int], expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        limits(**override)


def test_a_member_bound_above_the_total_is_refused() -> None:
    """Otherwise the first member could spend the whole budget."""
    with pytest.raises(ValidationError, match="exceeds total_input_bytes"):
        limits(total_input_bytes=1 << 20, member_bytes=1 << 21)


def test_a_boolean_limit_is_refused() -> None:
    with pytest.raises(ValidationError, match="positive count"):
        limits(total_input_bytes=True)


# ---------------------------------------------------------------------------
# Entries and exclusions
# ---------------------------------------------------------------------------


def test_an_entry_names_a_safe_member_and_a_well_formed_digest() -> None:
    built = entry()
    assert built.member == "snapshot.json"
    assert built.digest == DIGEST


def test_an_entry_naming_an_unsafe_member_is_refused() -> None:
    with pytest.raises(ValidationError, match="unsafe member"):
        BundleEntry("../escape", ArtifactKind.SNAPSHOT, 1, DIGEST)


@pytest.mark.parametrize(
    "digest",
    [
        pytest.param("deadbeef", id="not-prefixed"),
        pytest.param("sha256:short", id="too-short"),
        pytest.param("md5:" + "a" * 64, id="wrong-algorithm"),
    ],
)
def test_an_entry_with_a_malformed_digest_is_refused(digest: str) -> None:
    with pytest.raises(ValidationError, match="sha256 hex digest"):
        BundleEntry("snapshot.json", ArtifactKind.SNAPSHOT, 1, digest)


def test_an_entry_with_a_negative_size_is_refused() -> None:
    with pytest.raises(ValidationError, match="byte count"):
        BundleEntry("snapshot.json", ArtifactKind.SNAPSHOT, -1, DIGEST)


def test_an_exclusion_must_name_a_declared_reason() -> None:
    assert BundleExclusion(ArtifactKind.LOG, EXCLUDED_TOO_LARGE).reason in EXCLUSION_REASONS
    with pytest.raises(ValidationError, match="declared bundle exclusion"):
        BundleExclusion(ArtifactKind.LOG, "INVENTED")


def test_an_exclusion_may_name_no_kind_at_all() -> None:
    """A candidate refused before anything decided what it was."""
    assert BundleExclusion(None, EXCLUDED_TOO_LARGE).kind is None


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def test_a_manifest_in_member_order_is_accepted() -> None:
    built = BundleManifest(entries=(entry("a.json"), entry("b.json")), limits=limits())
    assert built.total_bytes() == 20
    assert built.schema_version == BUNDLE_SCHEMA_VERSION


def test_a_manifest_out_of_member_order_is_refused() -> None:
    with pytest.raises(ValidationError, match="member order"):
        BundleManifest(entries=(entry("b.json"), entry("a.json")))


def test_a_manifest_naming_the_same_member_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="same member twice"):
        BundleManifest(entries=(entry("a.json"), entry("a.json")))


def test_a_manifest_naming_two_members_differing_only_in_case_is_refused() -> None:
    """Not theoretical on the target host.

    Windows compares filenames case-insensitively, so an archive holding both
    extracts to one file and the manifest then describes a member that is not
    there.
    """
    with pytest.raises(ValidationError, match="only in case"):
        BundleManifest(entries=(entry("logs/Globin.log"), entry("logs/globin.log")))


def test_an_empty_manifest_is_accepted() -> None:
    """A bundle that collected nothing is still a bundle, and its report says so."""
    assert BundleManifest().total_bytes() == 0
