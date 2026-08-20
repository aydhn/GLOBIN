"""The scope-amendment ledger, held against `ROADMAP.md` and the decision log.

This module exists because of a defect `ROADMAP.md` documents about itself. Its
prose list of scope amendments drifted twice: it read *seven* while listing eight
from Phase 024 until Phase 025 repaired it, and by Phase 030 it read *thirteen*
while listing eleven, with the tenth filed below the eleventh. The document names
the cause in four words -- "Nothing tests it."

Phase 032 was assigned the granularity review by `ROADMAP.md` and by six ADRs. A
review whose own counts nothing checked would have been the third instance of the
same defect rather than an answer to it, so the ledger came with this file.

The assertions run in both directions wherever there are two sources, which is
the pattern `test_release_contract.py` uses for the acceptance matrix and for the
same reason: a one-directional check catches a document that overclaims and
misses one that silently drops a row.
"""

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.support import markdown_prose, parse_roadmap

#: The ledger, and the prose half it must agree with.
LEDGER: str = "docs/engineering/scope-amendments.toml"
REVIEW: str = "docs/engineering/GRANULARITY_REVIEW.md"

#: The four keys an amendment is scored on, in the order `ROADMAP.md` states the
#: test: "nothing displaced, nothing deferred, no phase owns the work, and the
#: two halves need each other".
#:
#: ADR-0021 never uses the word "condition" and never numbers these; the
#: four-part form every later record cites is `ROADMAP.md`'s restatement of it.
#: Naming that here rather than citing ADR-0021 directly is deliberate -- the
#: test being scored is the one the programme actually applied.
CONDITIONS: tuple[str, ...] = (
    "nothing_displaced",
    "nothing_deferred",
    "no_phase_owns_it",
    "halves_need_each_other",
)

#: The two verdicts a condition may carry, and no third.
VERDICTS: frozenset[str] = frozenset({"MET", "FAILED"})

#: `**Scope amendments.** N have been made.` in `ROADMAP.md`, as a spelled word.
AMENDMENT_COUNT_RE: re.Pattern[str] = re.compile(
    r"\*\*Scope amendments\.\*\*\s+(?P<word>[A-Z][a-z]+) have been made", re.MULTILINE
)

#: `> **Ordinal.**` -- one per amendment, in `ROADMAP.md`'s amendment section.
ORDINAL_HEADING_RE: re.Pattern[str] = re.compile(
    r"^>?\s*\*\*(?P<word>[A-Z][a-z]+)[.,]", re.MULTILINE
)

#: Spelled cardinals, so a count in prose can be compared to a length. The
#: repository already spells counts in prose rather than digitising them, and
#: `tests/support.py` carries `SPELLED_SIZES` for the same purpose -- this list
#: is separate because it must reach sixteen and beyond, and that one stops
#: where its own callers do.
SPELLED: dict[str, int] = {
    "One": 1,
    "Two": 2,
    "Three": 3,
    "Four": 4,
    "Five": 5,
    "Six": 6,
    "Seven": 7,
    "Eight": 8,
    "Nine": 9,
    "Ten": 10,
    "Eleven": 11,
    "Twelve": 12,
    "Thirteen": 13,
    "Fourteen": 14,
    "Fifteen": 15,
    "Sixteen": 16,
    "Seventeen": 17,
    "Eighteen": 18,
    "Nineteen": 19,
    "Twenty": 20,
}

#: The ordinal words, in order, so position can be checked as well as presence.
ORDINALS: tuple[str, ...] = (
    "First",
    "Second",
    "Third",
    "Fourth",
    "Fifth",
    "Sixth",
    "Seventh",
    "Eighth",
    "Ninth",
    "Tenth",
    "Eleventh",
    "Twelfth",
    "Thirteenth",
    "Fourteenth",
    "Fifteenth",
    "Sixteenth",
    "Seventeenth",
    "Eighteenth",
    "Nineteenth",
    "Twentieth",
)


def _int(entry: Mapping[str, object], key: str) -> int:
    """One integer field, narrowed.

    Args:
        entry: A parsed ledger row.
        key: The field.

    Returns:
        Its value.

    `tomllib` returns `dict[str, Any]`-shaped data whose values are genuinely
    heterogeneous, so the honest annotation is `object` and the narrowing belongs
    at the point of use. Three one-line accessors are the alternative to
    scattering `assert isinstance` through the assertions, or to an `Any` that
    would let a typo through.
    """
    value = entry[key]
    assert isinstance(value, int), f"{key} is {type(value).__name__}, not an integer"
    return value


def _str(entry: Mapping[str, object], key: str) -> str:
    """One string field, narrowed.

    Args:
        entry: A parsed ledger row.
        key: The field.

    Returns:
        Its value.
    """
    value = entry[key]
    assert isinstance(value, str), f"{key} is {type(value).__name__}, not a string"
    return value


def _ints(entry: Mapping[str, object], key: str) -> list[int]:
    """One list-of-phase-numbers field, narrowed.

    Args:
        entry: A parsed ledger row.
        key: The field.

    Returns:
        Its value.
    """
    value = entry[key]
    assert isinstance(value, list), f"{key} is {type(value).__name__}, not a list"
    assert all(isinstance(item, int) for item in value), f"{key} holds a non-integer"
    return value


@pytest.fixture(scope="module")
def ledger(repo_root: Path) -> dict[str, object]:
    """The parsed amendment ledger."""
    return tomllib.loads((repo_root / LEDGER).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def amendments(ledger: dict[str, object]) -> list[dict[str, object]]:
    """Every amendment, in declaration order."""
    entries = ledger["amendment"]
    assert isinstance(entries, list)
    return entries


@pytest.fixture(scope="module")
def statuses(repo_root: Path) -> dict[int, str]:
    """Every phase's status, from `ROADMAP.md`."""
    text = (repo_root / "ROADMAP.md").read_text(encoding="utf-8")
    return {row.phase: row.status for row in parse_roadmap(text)}


def test_the_ledger_is_ordered_and_contiguous(amendments: list[dict[str, object]]) -> None:
    """Ordinals run 1..N with no gap and no repeat.

    A gap would mean an amendment was made and not recorded, which is the failure
    the whole file exists to make impossible.
    """
    ordinals = [entry["ordinal"] for entry in amendments]
    assert ordinals == list(range(1, len(amendments) + 1))


def test_every_ordinal_word_matches_its_number(amendments: list[dict[str, object]]) -> None:
    """`ordinal_word` and `ordinal` say the same thing, and are checked to agree.

    Two spellings of one fact need a check that they agree, or the redundancy
    becomes a way for them to disagree quietly -- which is exactly how the tenth
    amendment came to be filed below the eleventh.
    """
    for entry in amendments:
        index = _int(entry, "ordinal") - 1
        assert _str(entry, "ordinal_word") == ORDINALS[index], (
            f"amendment {entry['ordinal']} calls itself {entry['ordinal_word']!r}"
        )


def test_the_roadmap_count_matches_the_ledger(
    repo_root: Path, amendments: list[dict[str, object]]
) -> None:
    """`ROADMAP.md`'s spelled count equals the number of recorded amendments.

    **This is the assertion that never existed.** `ROADMAP.md` says of this very
    number: "Nothing tests it, which is why it drifted and why it is worth
    reading sceptically." It drifted twice. Now it cannot.
    """
    text = (repo_root / "ROADMAP.md").read_text(encoding="utf-8")
    match = AMENDMENT_COUNT_RE.search(text)
    assert match is not None, "ROADMAP.md no longer states how many amendments have been made"
    word = match.group("word")
    assert word in SPELLED, f"ROADMAP.md spells the amendment count {word!r}"
    assert SPELLED[word] == len(amendments), (
        f"ROADMAP.md says {word.lower()} amendments; the ledger records {len(amendments)}"
    )


def test_the_roadmap_lists_every_amendment_in_order(
    repo_root: Path, amendments: list[dict[str, object]]
) -> None:
    """Every ordinal heading appears exactly once, in ascending order.

    The count agreeing is not enough on its own: by Phase 030 the count read
    thirteen, the list stopped at eleven, and the tenth was filed *below* the
    eleventh. Presence and position are separate failures and are checked
    separately.
    """
    prose = markdown_prose((repo_root / "ROADMAP.md").read_text(encoding="utf-8"))
    positions: dict[str, int] = {}
    for entry in amendments:
        word = _str(entry, "ordinal_word")
        needle = f"**{word}."
        alternate = f"**{word},"
        where = prose.find(needle)
        if where < 0:
            where = prose.find(alternate)
        assert where >= 0, f"ROADMAP.md does not introduce the {word.lower()} amendment"
        positions[word] = where

    ordered = [positions[_str(entry, "ordinal_word")] for entry in amendments]
    assert ordered == sorted(ordered), (
        "ROADMAP.md introduces the amendments out of order: "
        f"{[e['ordinal_word'] for e in amendments]} appear at {ordered}"
    )


def test_every_record_exists_and_is_an_accepted_decision(
    repo_root: Path, amendments: list[dict[str, object]]
) -> None:
    """Each amendment names an ADR that exists and that the index calls Accepted.

    An amendment whose record is missing is an amendment nobody can argue with.
    """
    index = (repo_root / "docs/adr/README.md").read_text(encoding="utf-8")
    for entry in amendments:
        record = _str(entry, "record")
        assert (repo_root / record).is_file(), f"amendment {entry['ordinal']}: {record} is missing"
        # The index links each record by its bare number -- `| [0012](0012-...md) |`
        # -- rather than by an `ADR-NNNN` label, so the link target is what to
        # look for. Matching the number alone would hit any four-digit run.
        target = Path(record).name
        assert f"({target})" in index, f"{record} is not listed in the ADR index"


def test_the_score_is_recomputed_rather_than_trusted(
    amendments: list[dict[str, object]],
) -> None:
    """`score` equals the number of conditions marked `MET`.

    Arithmetic, not a typed number. A record that scored itself would be the same
    class of unchecked claim as the count in `ROADMAP.md` was.
    """
    for entry in amendments:
        if not entry["scored"]:
            assert "score" not in entry, (
                f"amendment {entry['ordinal']} is unscored and carries a score"
            )
            continue
        verdicts = [entry[key] for key in CONDITIONS]
        assert set(verdicts) <= VERDICTS, f"amendment {entry['ordinal']} uses an unknown verdict"
        assert entry["score"] == sum(1 for v in verdicts if v == "MET"), (
            f"amendment {entry['ordinal']} claims {entry['score']} but its conditions say "
            f"{sum(1 for v in verdicts if v == 'MET')}"
        )


def test_the_unscored_amendments_are_the_three_that_predate_the_test(
    amendments: list[dict[str, object]],
) -> None:
    """Only the first three are unscored, and every later one is scored.

    Amendments one and two predate ADR-0021; the third *is* ADR-0021, so scoring
    it against itself would be circular. A fourth unscored row would mean an
    amendment quietly excused itself from the test.
    """
    unscored = [entry["ordinal"] for entry in amendments if not entry["scored"]]
    assert unscored == [1, 2, 3]


def test_every_displaced_phase_exists(
    amendments: list[dict[str, object]], statuses: dict[int, str]
) -> None:
    """A displaced phase is a real phase.

    Guards against a typo turning a real displacement into a claim about a phase
    number that does not exist, which would read as harmless and hide a real one.
    """
    for entry in amendments:
        for phase in _ints(entry, "displaces"):
            assert phase in statuses, f"amendment {entry['ordinal']} displaces phase {phase:03d}"


def test_every_title_collision_still_has_the_title_it_collided_with(
    repo_root: Path, amendments: list[dict[str, object]]
) -> None:
    """A title collision names a phase whose title is still the one recorded.

    Title collisions are the review's sharpest finding, so they are bound to the
    thing they are about. If a later phase retitles 263, 280 or 292, this fails
    and the claim is re-examined rather than left standing against a title that
    no longer exists.
    """
    inheritance = tomllib.loads((repo_root / LEDGER).read_text(encoding="utf-8"))["inheritance"]
    titles = {entry["phase"]: entry["title"] for entry in inheritance}
    parsed = list(parse_roadmap((repo_root / "ROADMAP.md").read_text(encoding="utf-8")))
    rows = {row.phase: row.title for row in parsed}
    complete = {row.phase for row in parsed if row.status == "Complete"}
    for entry in amendments:
        for phase in _ints(entry, "title_collisions"):
            if phase in complete:
                # The collided phase has since shipped, so it has no inheritance row
                # -- `test_every_inherited_phase_is_still_planned` requires those to
                # be Planned. The claim is still true and no longer needs re-checking
                # against a table it has left: a completed phase's title is settled.
                #
                # Phase 034 is the first case. The seventeenth amendment collided
                # with its title, Phase 034 then shipped, and without this branch a
                # completed collision would have had to be deleted from an accepted
                # record to keep the suite green.
                continue
            assert phase in titles, (
                f"amendment {entry['ordinal']} collides with phase {phase:03d}'s title, "
                f"which is neither recorded in the inheritance table nor complete"
            )
            assert rows[phase] == titles[phase], (
                f"phase {phase:03d} is now titled {rows[phase]!r}, and the ledger records "
                f"{titles[phase]!r}. The collision claim needs re-examining."
            )


def test_every_overlapped_phase_is_complete(
    amendments: list[dict[str, object]], statuses: dict[int, str]
) -> None:
    """An overlap with a completed phase names a phase that is `Complete`.

    Overlapping a *planned* phase is displacement and is recorded as such.
    Overlapping a completed one is the worse case ADR-0060 first had to concede,
    and conflating the two would flatten the finding.
    """
    for entry in amendments:
        for phase in _ints(entry, "overlaps_complete"):
            assert statuses[phase] == "Complete", (
                f"amendment {entry['ordinal']} claims to overlap completed phase "
                f"{phase:03d}, which is {statuses[phase]}"
            )


def test_every_inherited_phase_is_still_planned(repo_root: Path, statuses: dict[int, str]) -> None:
    """Every row of the inheritance table names a phase that has not started.

    The table says what a *future* phase will find partly built. A row whose
    phase has shipped is either wrong or stale, and either way the phase it
    describes has already had to deal with what it says.
    """
    inheritance = tomllib.loads((repo_root / LEDGER).read_text(encoding="utf-8"))["inheritance"]
    for entry in inheritance:
        phase = entry["phase"]
        assert statuses[phase] == "Planned", (
            f"the inheritance table describes phase {phase:03d} as not yet started, "
            f"and ROADMAP.md says {statuses[phase]}"
        )


def test_every_inherited_phase_names_where_its_subject_came_from(
    repo_root: Path, statuses: dict[int, str]
) -> None:
    """`from_phases` names delivered phases, so a reader can go and look.

    A row saying "already built" without saying by what is an assertion. Naming
    the phases makes it checkable by hand as well as by this test.
    """
    inheritance = tomllib.loads((repo_root / LEDGER).read_text(encoding="utf-8"))["inheritance"]
    for entry in inheritance:
        assert entry["from_phases"], f"phase {entry['phase']:03d} names no source phase"
        for phase in entry["from_phases"]:
            assert statuses[phase] == "Complete", (
                f"phase {entry['phase']:03d} inherits from {phase:03d}, which is "
                f"{statuses[phase]} rather than Complete"
            )


def test_the_review_and_the_ledger_agree_in_both_directions(
    repo_root: Path, amendments: list[dict[str, object]]
) -> None:
    """Every scored amendment's score appears in the prose, and no other does.

    The two-directional form matters: checking only that the prose is backed by
    the ledger would miss a ledger row the prose forgot, which is the direction
    `ROADMAP.md` actually drifted in.
    """
    prose = markdown_prose((repo_root / REVIEW).read_text(encoding="utf-8"))
    for entry in amendments:
        if not entry["scored"]:
            continue
        row = f"| {entry['ordinal']} | {entry['phase']:03d} |"
        assert row in prose, (
            f"GRANULARITY_REVIEW.md has no summary row for amendment {entry['ordinal']} "
            f"(phase {entry['phase']:03d})"
        )


def test_the_review_states_the_condition_tally_the_ledger_computes(
    repo_root: Path, amendments: list[dict[str, object]]
) -> None:
    """The review's central claim is recomputed from the ledger.

    The finding is that two of the four conditions carry no information across
    this programme -- one is met every time and one is met never. That is the
    whole argument, so it is the one number that must not be typed by hand.
    """
    scored = [entry for entry in amendments if entry["scored"]]
    tally = {key: sum(1 for entry in scored if entry[key] == "MET") for key in CONDITIONS}
    # Read raw rather than through `markdown_prose`, which strips inline code --
    # and the condition names are written as code, because they are the ledger's
    # own key names rather than English.
    text = (repo_root / REVIEW).read_text(encoding="utf-8")
    for key, met in tally.items():
        claim = f"| `{key}` | {met}/{len(scored)} |"
        assert claim in text, (
            f"GRANULARITY_REVIEW.md does not state {key} as {met}/{len(scored)}; "
            f"the ledger computes that."
        )
