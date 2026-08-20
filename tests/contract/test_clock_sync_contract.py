"""The clock contract against the package, in both directions, and against its prose.

Three artefacts state the same rules: `clock-contract.toml` declares them,
`globin.domain.clock_sync` implements them, and `CLOCK_DISCIPLINE.md` explains them.
`docs/engineering/SOURCE_OF_TRUTH.md` permits that only because this module compares
them — and compares them **both ways**, so a value declared and not implemented fails
just as a value implemented and not declared does.

The strongest checks here are the ones that recompute rather than compare. The
declared defaults are used to *build* a discipline and the result is compared against
the one the code produces; the declared estimator name is *executed* against a window
whose fastest sample is known. A test that only matched strings would pass on a
contract that had been edited to describe the wrong behaviour accurately.
"""

import tomllib
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.clock_sync import (
    CONTRACT_RELATIVE_PATH,
    ClockContract,
    discipline_from,
    read_clock_contract,
)
from globin.application.clock_sync import self_test
from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import MAX_RECV_WINDOW_MILLIS, TimestampUnit
from globin.domain.clock import Duration, MonotonicReading
from globin.domain.clock_sync import (
    FUTURE_TOLERANCE_MILLIS,
    INVALID_TIMESTAMP_CODE,
    MAX_SAMPLE_COUNT,
    MAX_TIMING_RETRIES,
    OFFSET_BUCKET_BOUNDS_MILLIS,
    ROUND_TRIP_BUCKET_BOUNDS_MILLIS,
    AdmissionStatus,
    CalibrationSample,
    ClockDomain,
    JumpDirection,
    SyncState,
    TimingRecovery,
    choose_sample,
    default_discipline,
)
from globin.domain.configuration import MAXIMUM_CLOCK_SAMPLES
from globin.domain.rest import AMBIGUOUS_EXCHANGE_CODES
from globin.errors import ValidationError

GUIDE: Final[str] = "docs/engineering/CLOCK_DISCIPLINE.md"

DOMAIN = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("testnet"),
    protocol=ProtocolKind.REST,
)


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> ClockContract:
    """The declared contract, read once."""
    document = read_clock_contract(repo_root / CONTRACT_RELATIVE_PATH)
    assert document is not None, f"{CONTRACT_RELATIVE_PATH} is absent"
    return document


@pytest.fixture(scope="module")
def raw(repo_root: Path) -> dict[str, object]:
    """The whole document, for the tables the typed reader does not carry."""
    return tomllib.loads((repo_root / CONTRACT_RELATIVE_PATH).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def guide(repo_root: Path) -> str:
    """The prose half."""
    return (repo_root / GUIDE).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The defaults, recomputed
# ---------------------------------------------------------------------------


def test_the_declared_defaults_build_the_discipline_the_code_uses(contract: ClockContract) -> None:
    """Recomputed, not compared: the document's numbers must *produce* the defaults.

    This is what stops the contract describing thresholds nobody applies. If the
    code's defaults changed and the document did not, the two disciplines differ and
    this fails.
    """
    assert discipline_from(**dict(contract.defaults)) == default_discipline()


def test_every_declared_default_names_a_field_the_discipline_has(
    contract: ClockContract,
) -> None:
    """The other direction: a declared key the builder does not accept fails."""
    expected = {
        "sample_count",
        "freshness_ttl_millis",
        "degraded_grace_millis",
        "max_round_trip_millis",
        "max_uncertainty_millis",
        "max_offset_jump_millis",
        "max_wall_divergence_millis",
        "network_budget_millis",
    }
    assert set(contract.defaults) == expected


def test_the_declared_sample_ceiling_matches_both_modules(contract: ClockContract) -> None:
    """`configuration` restates the clock layer's bound because it may not import it.

    Two domain modules may not depend on each other without a cycle, so the ceiling
    is written twice. This is the comparison that makes the duplication a tripwire
    rather than drift.
    """
    assert MAXIMUM_CLOCK_SAMPLES == MAX_SAMPLE_COUNT
    assert contract.defaults["sample_count"] <= MAX_SAMPLE_COUNT


# ---------------------------------------------------------------------------
# The estimator, executed
# ---------------------------------------------------------------------------


def test_the_declared_estimator_is_the_one_the_code_runs(contract: ClockContract) -> None:
    """The declared name is executed rather than matched.

    A window whose fastest sample is known is built, and the selection is checked
    against it. A contract claiming `lowest_round_trip` over code that averaged
    would fail here.
    """
    assert contract.estimator == "lowest_round_trip"
    window = tuple(
        CalibrationSample(
            domain=DOMAIN,
            offset_micros=index,
            round_trip=Duration(trip * 1_000_000),
            taken_at=MonotonicReading(index * 10**9),
            wall_anchor_micros=1,
            reported_unit=TimestampUnit.MILLISECONDS,
        )
        for index, trip in enumerate((400, 12, 800, 90))
    )
    chosen = choose_sample(window)
    assert chosen is not None
    assert chosen.round_trip.milliseconds == 12


def test_the_declared_uncertainty_rule_is_the_one_the_sample_reports(
    raw: dict[str, object],
) -> None:
    """`half_round_trip`, executed against a sample rather than read as a word."""
    estimator = raw["estimator"]
    assert isinstance(estimator, dict)
    assert estimator["uncertainty"] == "half_round_trip"
    sample = CalibrationSample(
        domain=DOMAIN,
        offset_micros=0,
        round_trip=Duration(80 * 1_000_000),
        taken_at=MonotonicReading(0),
        wall_anchor_micros=1,
        reported_unit=TimestampUnit.MILLISECONDS,
    )
    assert sample.uncertainty_micros == sample.round_trip.microseconds // 2


# ---------------------------------------------------------------------------
# The vocabulary, both directions
# ---------------------------------------------------------------------------


def test_the_declared_states_are_exactly_the_states_that_exist(contract: ClockContract) -> None:
    """A declared word with no member fails, and a member with no word fails."""
    assert set(contract.states) == {item.value for item in SyncState}


def test_the_declared_states_are_in_the_order_the_machine_reaches_them(
    contract: ClockContract,
) -> None:
    """Order is documentation, so it is pinned rather than left to be re-derived."""
    assert contract.states == tuple(item.value for item in SyncState)


def test_exactly_one_declared_state_admits(raw: dict[str, object]) -> None:
    """Counted rather than named, so a sixth state cannot silently become admitting."""
    vocabulary = raw["vocabulary"]
    assert isinstance(vocabulary, dict)
    assert vocabulary["admitting_states"] == len([item for item in SyncState if item.admits])
    assert vocabulary["admitting_states"] == 1


def test_the_declared_admission_outcomes_are_exactly_the_ones_that_exist(
    contract: ClockContract,
) -> None:
    """Both directions over the refusal vocabulary."""
    assert set(contract.admission) == {item.value for item in AdmissionStatus}


def test_the_declared_recovery_verdicts_are_exactly_the_ones_that_exist(
    contract: ClockContract,
) -> None:
    """Three verdicts, and no fourth meaning *retry freely*."""
    assert set(contract.recovery) == {item.value for item in TimingRecovery}


def test_the_declared_jump_directions_are_exactly_the_ones_that_exist(
    raw: dict[str, object],
) -> None:
    """A direction the code cannot produce would be a promise nothing keeps."""
    vocabulary = raw["vocabulary"]
    assert isinstance(vocabulary, dict)
    assert set(vocabulary["jump_directions"]) == {item.value for item in JumpDirection}


# ---------------------------------------------------------------------------
# The buckets
# ---------------------------------------------------------------------------


def test_the_declared_buckets_are_the_bounds_the_code_uses(contract: ClockContract) -> None:
    """A dashboard's cardinality is computable from this file, so it must be true."""
    assert contract.buckets["round_trip_millis"] == ROUND_TRIP_BUCKET_BOUNDS_MILLIS
    assert contract.buckets["offset_millis"] == OFFSET_BUCKET_BOUNDS_MILLIS


def test_no_third_bucket_dimension_is_declared(contract: ClockContract) -> None:
    """The other direction: an undeclared dimension would escape the cardinality budget."""
    assert set(contract.buckets) == {"round_trip_millis", "offset_millis"}


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def test_the_declared_recovery_rules_match_the_code(raw: dict[str, object]) -> None:
    """The code, the number and the venue's own code, in one comparison."""
    recovery = raw["recovery"]
    assert isinstance(recovery, dict)
    assert recovery["code"] == INVALID_TIMESTAMP_CODE
    assert recovery["max_retries"] == MAX_TIMING_RETRIES
    assert recovery["requires_confirmed_outcome"] is True


def test_the_declared_code_is_unambiguous_in_the_transport_contract(
    raw: dict[str, object],
) -> None:
    """The join between two contracts, asserted rather than assumed.

    The bounded retry is reachable only because Phase 034 classifies `-1021` as a
    confirmed failure. If that ever changed, the recovery table here would become
    unreachable and this is where it would be noticed.
    """
    recovery = raw["recovery"]
    assert isinstance(recovery, dict)
    assert recovery["code"] not in AMBIGUOUS_EXCHANGE_CODES


# ---------------------------------------------------------------------------
# Prohibitions
# ---------------------------------------------------------------------------


def test_every_declared_prohibition_is_still_prohibited(raw: dict[str, object]) -> None:
    """Declared so the absences are testable rather than merely stated."""
    prohibitions = raw["prohibitions"]
    assert isinstance(prohibitions, dict)
    permitted = sorted(name for name, value in prohibitions.items() if value)
    assert not permitted, f"declared permitted: {permitted}"


def test_the_prohibition_table_names_the_six_absences_the_phase_claims(
    raw: dict[str, object],
) -> None:
    """A prohibition removed from the table would otherwise pass the check above."""
    prohibitions = raw["prohibitions"]
    assert isinstance(prohibitions, dict)
    assert set(prohibitions) == {
        "widen_window_on_uncertainty",
        "persist_offset_across_restart",
        "retry_unknown_outcome",
        "calibrate_from_a_second_domain",
        "correct_the_host_clock",
        "sign_without_calibration",
    }


def test_nothing_in_the_package_writes_a_host_clock(repo_root: Path) -> None:
    """`correct_the_host_clock`, asserted against the source rather than promised.

    There is no portable way to set a Windows clock from Python without `ctypes`
    and `SetSystemTime`, so the check is for the spellings that would be needed.
    """
    package = repo_root / "src" / "globin"
    forbidden = ("SetSystemTime", "SetLocalTime", "clock_settime", "settimeofday")
    offenders = [
        f"{path.relative_to(repo_root)}: {token}"
        for path in sorted(package.rglob("*.py"))
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


def test_nothing_in_the_clock_layer_persists_an_offset(repo_root: Path) -> None:
    """`persist_offset_across_restart`, asserted the same way.

    The clock modules may not write anything at all: no path, no open, no dump. A
    persisted offset is one a restart would trust without re-measuring, which is
    the whole reason a fresh manager starts uninitialized.
    """
    modules = [
        repo_root / "src" / "globin" / "domain" / "clock_sync.py",
        repo_root / "src" / "globin" / "application" / "clock_sync.py",
    ]
    forbidden = ("open(", "write_text", "write_bytes", "json.dump", "Path(")
    offenders = [
        f"{path.name}: {token}"
        for path in modules
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


# ---------------------------------------------------------------------------
# The prose
# ---------------------------------------------------------------------------


def test_the_guide_states_the_gate_count_the_code_has(guide: str) -> None:
    """A count in prose is a claim, so it is compared to its source.

    Seven gates and seven refusal words, which is not a coincidence but is also not
    a one-to-one mapping: gates 5 and 6 *share* ``clock_uncertainty_exceeded``, and
    gate 7 *splits* into two. The arithmetic happens to balance, and the table in the
    guide is what says which is which.
    """
    refusals = [item for item in AdmissionStatus if item is not AdmissionStatus.ADMITTED]
    assert "Seven gates" in guide
    assert len(refusals) == 7
    for refusal in refusals:
        assert f"`{refusal.value}`" in guide, refusal.value


def test_the_guide_states_the_venue_bounds_the_code_carries(guide: str) -> None:
    """The two numbers that come from Binance, each stated once and checked here."""
    assert f"{FUTURE_TOLERANCE_MILLIS} ms" in guide or f"{FUTURE_TOLERANCE_MILLIS} ms," in guide
    assert f"{MAX_RECV_WINDOW_MILLIS} ms" in guide


def test_the_guide_states_the_domain_counts_the_registry_carries(
    guide: str, repo_root: Path
) -> None:
    """The claim that three of twenty-four domains resolve, recomputed.

    It is the one number in the guide that changes when the registry does, which is
    exactly why it is bound rather than written down and trusted. Written as digits
    in the prose, against this repository's usual habit of spelling small numbers,
    because a count derived from data should read as a measurement rather than as
    part of a sentence.
    """
    from globin.adapters.api_reality import read_registry
    from globin.adapters.rest import read_contract
    from globin.application.clock_sync import declared_domains

    snapshot = read_registry(repo_root / "docs" / "engineering" / "binance-api-reality.toml")
    contract = read_contract(repo_root / "docs" / "engineering" / "rest-transport.toml")
    assert snapshot is not None
    assert contract is not None
    availability = declared_domains(snapshot, contract)
    usable = [item for item in availability if item.available]
    claim = f"**{len(availability)} domains are declared and {len(usable)} can be calibrated.**"
    assert claim in guide, claim


def test_the_guide_names_the_bucket_cardinalities_the_constants_imply(guide: str) -> None:
    """The published cardinality table, compared to the bounds that produce it."""
    assert f"| round-trip bucket | {len(ROUND_TRIP_BUCKET_BOUNDS_MILLIS) + 1} |" in guide
    assert (
        f"| offset-magnitude bucket, with sign | {(len(OFFSET_BUCKET_BOUNDS_MILLIS) + 1) * 2} |"
        in guide
    )
    assert f"| synchronization state | {len(SyncState)} |" in guide
    assert f"| admission refusal reason | {len(AdmissionStatus)} |" in guide
    assert f"| recovery verdict | {len(TimingRecovery)} |" in guide


def test_the_guide_lists_every_state_the_code_has(guide: str) -> None:
    """Both directions over the state table in the prose."""
    for state in SyncState:
        assert f"| `{state.value}` |" in guide, state.value


def test_the_guide_states_that_twenty_six_stays_free(guide: str) -> None:
    """The running claim every phase since 030 has had to keep."""
    assert "26 stays free" in guide


# ---------------------------------------------------------------------------
# The self-test
# ---------------------------------------------------------------------------


def test_the_self_test_passes_against_the_declared_defaults(contract: ClockContract) -> None:
    """The offline gate, run against the thresholds the document declares."""
    report = self_test(discipline_from(**dict(contract.defaults)))
    assert report.passed, [item.detail for item in report.failures]


def test_the_self_test_record_is_json_safe(contract: ClockContract) -> None:
    """It goes into the evidence manifest, so it has to survive a round trip."""
    import json

    report = self_test(discipline_from(**dict(contract.defaults)))
    assert json.loads(json.dumps(report.as_record()))["passed"] is True


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------


def test_an_absent_contract_is_absent_rather_than_an_error(tmp_path: Path) -> None:
    """Nothing established is a different fact from something malformed."""
    assert read_clock_contract(tmp_path / "nothing.toml") is None


def test_a_malformed_contract_is_refused(tmp_path: Path) -> None:
    """A document that exists and will not parse is a defect, and says so."""
    target = tmp_path / "clock-contract.toml"
    target.write_text("this is not = = toml", encoding="utf-8")
    with pytest.raises(ValidationError, match="could not be read"):
        read_clock_contract(target)


def _almost_complete() -> str:
    """A contract with every table and one missing key.

    Returns:
        The document text.

    Written out rather than derived from the committed file, so that the case stays
    what it says it is when the committed file changes.
    """
    return (
        "[meta]\nschema_version = 1\n"
        "[estimator]\nselection = 'lowest_round_trip'\n"
        "[defaults]\nsample_count = 5\n"
        "[vocabulary]\nstates = []\nadmission = []\nrecovery = []\n"
        "[buckets]\n"
    )


@pytest.mark.parametrize(
    ("body", "match"),
    [
        pytest.param(
            "[meta]\nschema_version = 1\n",
            r"\[estimator\] table",
            id="a-later-table-is-missing",
        ),
        pytest.param("schema = 1\n", r"\[meta\] table", id="the-first-table-is-missing"),
        pytest.param(
            _almost_complete(),
            "introduced_in_phase",
            id="a-required-integer-is-missing",
        ),
    ],
)
def test_a_contract_missing_a_required_value_is_refused(
    tmp_path: Path, body: str, match: str
) -> None:
    """Every required value is named in its own refusal."""
    target = tmp_path / "clock-contract.toml"
    target.write_text(body, encoding="utf-8")
    with pytest.raises(ValidationError, match=match):
        read_clock_contract(target)


@pytest.mark.parametrize(
    ("table", "body", "match"),
    [
        pytest.param(
            "estimator",
            "selection = 42",
            "'selection' string",
            id="a-string-that-is-a-number",
        ),
        pytest.param(
            "vocabulary",
            "states = 'uninitialized'",
            "'states' list of words",
            id="a-word-list-that-is-one-word",
        ),
        pytest.param(
            "vocabulary",
            "states = [1, 2]",
            "'states' list of words",
            id="a-word-list-of-numbers",
        ),
        pytest.param(
            "buckets",
            "round_trip_millis = 5",
            "'round_trip_millis' list of integers",
            id="a-number-list-that-is-one-number",
        ),
        pytest.param(
            "buckets",
            "round_trip_millis = [true, false]",
            "'round_trip_millis' list of integers",
            id="a-number-list-of-flags",
        ),
    ],
)
def test_a_contract_whose_value_is_the_wrong_shape_is_refused(
    tmp_path: Path, table: str, body: str, match: str
) -> None:
    """Every reader refusal, named in its own message.

    A reader that accepted a scalar where a list belongs would produce a contract
    that parsed and described nothing, and the comparison tests above would then be
    comparing the code against an empty claim -- passing for the wrong reason. Each
    case here is one of those.
    """
    document = {
        "meta": "schema_version = 1\nintroduced_in_phase = 36",
        "estimator": "selection = 'lowest_round_trip'",
        "defaults": "sample_count = 5",
        "vocabulary": "states = []\nadmission = []\nrecovery = []",
        "buckets": "round_trip_millis = []\noffset_millis = []",
    }
    document[table] = body
    target = tmp_path / "clock-contract.toml"
    target.write_text(
        "".join(f"[{name}]\n{value}\n" for name, value in document.items()), encoding="utf-8"
    )
    with pytest.raises(ValidationError, match=match):
        read_clock_contract(target)


def test_the_contract_record_is_stable_and_json_safe(contract: ClockContract) -> None:
    """It goes into the evidence manifest in a deterministic order."""
    import json

    first = json.dumps(contract.as_record(), sort_keys=False)
    second = json.dumps(contract.as_record(), sort_keys=False)
    assert first == second
    assert json.loads(first)["estimator"] == "lowest_round_trip"
