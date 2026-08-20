"""The estimator, the units and the parsing, against hand-computed answers.

Every number in this module was worked out on paper before the code ran. That is
the point of an estimator test: comparing the implementation against itself proves
only that it is consistent, and the failure this phase exists to prevent — an
offset that is confidently wrong — is perfectly consistent.

The scenario builder :func:`_sample` is the one piece of machinery here. It places
the venue's answer at the **true** midpoint of a simulated exchange and then offsets
it by a known amount, so a correct estimator recovers exactly that amount and an
incorrect one does not.
"""

from datetime import UTC, datetime, timedelta

import pytest

from globin.domain.api_reality import EnvironmentName, ProductFamily, ProtocolKind
from globin.domain.auth_timing import TimestampUnit
from globin.domain.clock import (
    MICROSECONDS_PER_MILLISECOND,
    Duration,
    Instant,
    MonotonicReading,
    instant,
)
from globin.domain.clock_sync import (
    OFFSET_BUCKET_BOUNDS_MILLIS,
    OVERFLOW_BUCKET,
    ROUND_TRIP_BUCKET_BOUNDS_MILLIS,
    SERVER_TIME_FIELD,
    CalibrationSample,
    ClockAnchor,
    ClockDomain,
    JumpDirection,
    ServerTimeReading,
    bound_window,
    choose_sample,
    corrected_stamp,
    default_discipline,
    detect_jump,
    max_window_micros,
    offset_bucket,
    offset_moved_too_far,
    round_trip_bucket,
    sample_offset,
    server_time_from,
)
from globin.errors import ValidationError

NANOSECONDS_PER_MILLISECOND = 1_000_000

DOMAIN = ClockDomain(
    family=ProductFamily("spot"),
    environment=EnvironmentName("testnet"),
    protocol=ProtocolKind.REST,
)

ANCHOR = Instant(datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC))


def _sample(*, ahead_millis: int, round_trip_millis: int, start_ns: int = 0) -> CalibrationSample:
    """One exchange in which the venue is a known distance ahead.

    Args:
        ahead_millis: How far ahead of the host the venue really is.
        round_trip_millis: How long the exchange really took.
        start_ns: Where on the monotonic clock it began.

    Returns:
        The sample the estimator produced from it.

    The venue's answer is placed at the **true** midpoint plus the offset, which is
    what a symmetric path would produce. An estimator that recovers ``ahead_millis``
    exactly is right; one that recovers anything else has folded part of the round
    trip into the offset.
    """
    started = MonotonicReading(start_ns)
    finished = MonotonicReading(start_ns + round_trip_millis * NANOSECONDS_PER_MILLISECOND)
    true_midpoint = ANCHOR.epoch_micros + (round_trip_millis * MICROSECONDS_PER_MILLISECOND) // 2
    reading = ServerTimeReading(
        epoch_micros=true_midpoint + ahead_millis * MICROSECONDS_PER_MILLISECOND,
        unit=TimestampUnit.MILLISECONDS,
    )
    return sample_offset(
        DOMAIN, reading=reading, wall_anchor=ANCHOR, started=started, finished=finished
    )


# ---------------------------------------------------------------------------
# The estimator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "ahead_millis"),
    [
        pytest.param("exact-zero", 0, id="exact-zero"),
        pytest.param("venue-ahead", 250, id="venue-ahead"),
        pytest.param("venue-behind", -250, id="venue-behind"),
        pytest.param("venue-far-ahead", 5_000, id="venue-far-ahead"),
    ],
)
def test_the_estimator_recovers_the_offset_it_was_given(label: str, ahead_millis: int) -> None:
    """A symmetric path yields the offset exactly, in either direction."""
    sample = _sample(ahead_millis=ahead_millis, round_trip_millis=40)
    assert sample.offset_micros == ahead_millis * MICROSECONDS_PER_MILLISECOND, label


def test_a_naive_estimator_would_have_been_wrong_by_half_the_round_trip() -> None:
    """The reason the midpoint exists, made into a number.

    ``server_time - local_receive_time`` attributes the whole round trip to the
    offset. On a 400ms link that is a 200ms error, and a host with a perfect clock
    would correct itself into being 200ms wrong.
    """
    sample = _sample(ahead_millis=0, round_trip_millis=400)
    naive = sample.offset_micros - sample.round_trip.microseconds // 2
    assert sample.offset_micros == 0
    assert naive == -200 * MICROSECONDS_PER_MILLISECOND


def test_the_uncertainty_is_half_the_round_trip() -> None:
    """The classical bound, which is what makes the fastest sample the best one."""
    sample = _sample(ahead_millis=0, round_trip_millis=90)
    assert sample.uncertainty_micros == 45 * MICROSECONDS_PER_MILLISECOND


def test_the_round_trip_comes_from_the_monotonic_clock_and_the_anchor_from_the_wall() -> None:
    """A wall clock stepped mid-flight cannot enter the round trip.

    The two readings are supplied separately, so this asserts the pairing rather
    than the arithmetic: the span is a difference of monotonic readings and the
    anchor is a single wall reading, so there is no second wall reading for a jump
    to land between.
    """
    sample = _sample(ahead_millis=0, round_trip_millis=100)
    assert sample.round_trip == Duration(100 * NANOSECONDS_PER_MILLISECOND)
    assert sample.wall_anchor_micros == ANCHOR.epoch_micros


def test_a_finished_reading_before_the_started_one_is_refused() -> None:
    """Not a negative duration but a refusal, which `Duration` already guarantees."""
    reading = ServerTimeReading(epoch_micros=ANCHOR.epoch_micros, unit=TimestampUnit.MILLISECONDS)
    with pytest.raises(ValidationError, match="earlier reading is the larger one"):
        sample_offset(
            DOMAIN,
            reading=reading,
            wall_anchor=ANCHOR,
            started=MonotonicReading(1_000),
            finished=MonotonicReading(0),
        )


# ---------------------------------------------------------------------------
# Sample selection
# ---------------------------------------------------------------------------


def test_the_lowest_round_trip_wins_over_a_high_latency_outlier() -> None:
    """One slow exchange must not move the estimate.

    The outlier here carries an offset of 900ms — a wildly wrong answer that a mean
    would drag the estimate towards. Selecting the minimum ignores it entirely.
    """
    window = (
        _sample(ahead_millis=5, round_trip_millis=800, start_ns=0),
        _sample(ahead_millis=7, round_trip_millis=30, start_ns=10**10),
        _sample(ahead_millis=900, round_trip_millis=1_500, start_ns=2 * 10**10),
    )
    chosen = choose_sample(window)
    assert chosen is not None
    assert chosen.round_trip.milliseconds == 30
    assert chosen.offset_micros == 7 * MICROSECONDS_PER_MILLISECOND


def test_a_tie_on_round_trip_goes_to_the_later_sample() -> None:
    """Deterministic, so two runs over one window always agree."""
    window = (
        _sample(ahead_millis=1, round_trip_millis=30, start_ns=0),
        _sample(ahead_millis=2, round_trip_millis=30, start_ns=10**10),
    )
    chosen = choose_sample(window)
    assert chosen is not None
    assert chosen.offset_micros == 2 * MICROSECONDS_PER_MILLISECOND


def test_an_empty_window_chooses_nothing() -> None:
    """`None` rather than a fabricated sample."""
    assert choose_sample(()) is None


def test_the_first_sample_on_a_fresh_pool_is_discarded_by_arithmetic() -> None:
    """The transport-specific half of the estimator's justification.

    `HttpRestTransport` pools connections, so the first exchange pays a TCP and TLS
    handshake and its elapsed time is not a round trip. This models that: a first
    sample whose apparent offset is inflated by the handshake, followed by two
    ordinary ones. The estimator must not pick the first, and must not average it in
    either — asserted by the chosen offset being the true one rather than a blend.
    """
    window = (
        _sample(ahead_millis=140, round_trip_millis=300, start_ns=0),
        _sample(ahead_millis=10, round_trip_millis=25, start_ns=10**10),
        _sample(ahead_millis=10, round_trip_millis=28, start_ns=2 * 10**10),
    )
    chosen = choose_sample(window)
    assert chosen is not None
    assert chosen.offset_micros == 10 * MICROSECONDS_PER_MILLISECOND


# ---------------------------------------------------------------------------
# The bounded window
# ---------------------------------------------------------------------------


def test_the_window_never_grows_past_the_configured_count() -> None:
    """Memory is bounded by construction, not by anybody remembering to trim."""
    window: tuple[CalibrationSample, ...] = ()
    for index in range(50):
        window = bound_window(window, _sample(ahead_millis=1, round_trip_millis=20), 5)
        assert len(window) <= 5, index
    assert len(window) == 5


def test_the_window_keeps_the_newest_samples() -> None:
    """Oldest first, and the oldest are what fall off."""
    window: tuple[CalibrationSample, ...] = ()
    for index in range(6):
        window = bound_window(window, _sample(ahead_millis=index, round_trip_millis=20), 3)
    assert [item.offset_micros // MICROSECONDS_PER_MILLISECOND for item in window] == [3, 4, 5]


@pytest.mark.parametrize("keep", [0, -1, True], ids=["zero", "negative", "a-flag"])
def test_a_window_that_keeps_nothing_is_refused(keep: object) -> None:
    """A window of zero would silently discard every measurement taken."""
    with pytest.raises(ValidationError):
        bound_window((), _sample(ahead_millis=0, round_trip_millis=1), keep)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Wall-clock jump detection
# ---------------------------------------------------------------------------


def _anchor(seconds: int, monotonic_ms: int) -> ClockAnchor:
    """Both clocks at one moment.

    Args:
        seconds: How many seconds past the fixed anchor the wall clock reads.
        monotonic_ms: What the monotonic clock reads, in milliseconds.

    Returns:
        The pair.
    """
    return ClockAnchor(
        wall=instant(ANCHOR.moment.replace(second=ANCHOR.moment.second) + _delta(seconds)),
        monotonic=MonotonicReading(monotonic_ms * NANOSECONDS_PER_MILLISECOND),
    )


def _delta(seconds: int) -> timedelta:
    """A timedelta of whole seconds.

    Args:
        seconds: How many.

    Returns:
        The timedelta.
    """
    return timedelta(seconds=seconds)


def test_a_wall_clock_set_forward_is_detected() -> None:
    """Four seconds of wall time across one second of real time is three seconds of jump."""
    verdict = detect_jump(
        earlier=_anchor(0, 0),
        later=_anchor(4, 1_000),
        discipline=default_discipline(),
    )
    assert verdict.detected
    assert verdict.direction is JumpDirection.FORWARD
    assert verdict.divergence_micros == 3 * 1_000 * MICROSECONDS_PER_MILLISECOND


def test_a_wall_clock_set_backward_is_detected() -> None:
    """A backward step is the case a `Duration` could not have expressed at all."""
    verdict = detect_jump(
        earlier=_anchor(10, 0),
        later=_anchor(5, 1_000),
        discipline=default_discipline(),
    )
    assert verdict.detected
    assert verdict.direction is JumpDirection.BACKWARD
    assert verdict.divergence_micros == -6 * 1_000 * MICROSECONDS_PER_MILLISECOND


def test_a_monotonic_clock_that_tracks_the_wall_clock_is_no_jump() -> None:
    """The negative case, without which the detector would flag every measurement."""
    verdict = detect_jump(
        earlier=_anchor(0, 0),
        later=_anchor(5, 5_000),
        discipline=default_discipline(),
    )
    assert not verdict.detected
    assert verdict.direction is JumpDirection.NONE
    assert verdict.divergence_micros == 0


def test_a_divergence_inside_the_threshold_is_no_jump() -> None:
    """The threshold is not zero, because two adjacent reads are not simultaneous."""
    discipline = default_discipline()
    verdict = detect_jump(
        earlier=ClockAnchor(wall=ANCHOR, monotonic=MonotonicReading(0)),
        later=ClockAnchor(
            wall=instant(ANCHOR.moment + _delta(1)),
            monotonic=MonotonicReading(900 * NANOSECONDS_PER_MILLISECOND),
        ),
        discipline=discipline,
    )
    assert verdict.divergence_micros == 100 * MICROSECONDS_PER_MILLISECOND
    assert not verdict.detected


def test_an_anchor_refuses_two_readings_of_the_wrong_kind() -> None:
    """The pair is the unit, so a mismatched pair cannot be built."""
    with pytest.raises(ValidationError, match="wall reading"):
        ClockAnchor(wall=MonotonicReading(0), monotonic=MonotonicReading(0))  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="monotonic reading"):
        ClockAnchor(wall=ANCHOR, monotonic=ANCHOR)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Offset movement
# ---------------------------------------------------------------------------


def test_an_offset_that_moved_further_than_a_venue_clock_could_is_flagged() -> None:
    """A venue clock does not step; a host clock does."""
    discipline = default_discipline()
    previous = _sample(ahead_millis=0, round_trip_millis=20)
    current = _sample(ahead_millis=5_000, round_trip_millis=20)
    assert offset_moved_too_far(previous, current, discipline)


def test_a_small_movement_is_ordinary_drift() -> None:
    """Clocks drift, and drift is not a step."""
    discipline = default_discipline()
    previous = _sample(ahead_millis=0, round_trip_millis=20)
    current = _sample(ahead_millis=3, round_trip_millis=20)
    assert not offset_moved_too_far(previous, current, discipline)


def test_the_first_sample_has_nothing_to_have_moved_from() -> None:
    """No previous anchor is not a jump."""
    assert not offset_moved_too_far(
        None, _sample(ahead_millis=9_000, round_trip_millis=20), default_discipline()
    )


# ---------------------------------------------------------------------------
# Timestamp units
# ---------------------------------------------------------------------------


def test_a_microsecond_stamp_is_exact() -> None:
    """Nothing is discarded, because the correction and the reading share a unit."""
    moment = instant(ANCHOR.moment.replace(microsecond=123_456))
    assert corrected_stamp(moment, 7, TimestampUnit.MICROSECONDS) == moment.epoch_micros + 7


def test_a_millisecond_stamp_floors_once_and_towards_the_past() -> None:
    """One flooring step, applied after the correction rather than before it."""
    moment = instant(ANCHOR.moment.replace(microsecond=999_999))
    micros = corrected_stamp(moment, 1, TimestampUnit.MICROSECONDS)
    millis = corrected_stamp(moment, 1, TimestampUnit.MILLISECONDS)
    assert millis == micros // MICROSECONDS_PER_MILLISECOND
    assert millis * MICROSECONDS_PER_MILLISECOND <= micros


def test_correcting_before_flooring_is_not_the_same_as_flooring_before_correcting() -> None:
    """The bug this ordering prevents, made into an assertion.

    With 999999 microseconds on the clock and a correction of one microsecond, the
    corrected moment crosses a millisecond boundary. Flooring first would discard
    the 999 microseconds and then add nothing, landing a whole millisecond earlier.
    """
    moment = instant(ANCHOR.moment.replace(microsecond=999_999))
    correct = corrected_stamp(moment, 1, TimestampUnit.MILLISECONDS)
    wrong = moment.epoch_millis + 1 // MICROSECONDS_PER_MILLISECOND
    assert correct == wrong + 1


def test_a_zero_correction_agrees_with_the_phase_009_projection() -> None:
    """The clock layer does not invent a second way to express a moment."""
    moment = instant(ANCHOR.moment.replace(microsecond=654_321))
    assert corrected_stamp(moment, 0, TimestampUnit.MILLISECONDS) == moment.epoch_millis
    assert corrected_stamp(moment, 0, TimestampUnit.MICROSECONDS) == moment.epoch_micros


def test_a_negative_correction_moves_the_stamp_backwards() -> None:
    """A host running fast is corrected downward, which is the common direction."""
    assert corrected_stamp(ANCHOR, -250_000, TimestampUnit.MILLISECONDS) == (
        ANCHOR.epoch_millis - 250
    )


def test_an_offset_that_is_not_an_integer_is_refused() -> None:
    """A float offset would reintroduce exactly the drift this module avoids."""
    with pytest.raises(ValidationError, match="clock offset"):
        corrected_stamp(ANCHOR, 1.5, TimestampUnit.MILLISECONDS)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="clock offset"):
        corrected_stamp(ANCHOR, True, TimestampUnit.MILLISECONDS)


# ---------------------------------------------------------------------------
# Reading the venue's answer
# ---------------------------------------------------------------------------


def test_a_documented_millisecond_body_parses() -> None:
    """The exact response the venue publishes for `GET /api/v3/time`."""
    reading = server_time_from({SERVER_TIME_FIELD: 1499827319559}, TimestampUnit.MILLISECONDS)
    assert reading.epoch_micros == 1499827319559 * MICROSECONDS_PER_MILLISECOND
    assert reading.unit is TimestampUnit.MILLISECONDS


def test_a_microsecond_body_is_taken_at_face_value() -> None:
    """No multiplication when the request negotiated microseconds."""
    reading = server_time_from({SERVER_TIME_FIELD: 1499827319559000}, TimestampUnit.MICROSECONDS)
    assert reading.epoch_micros == 1499827319559000


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        pytest.param([], "decoded to list", id="a-list"),
        pytest.param(None, "decoded to NoneType", id="nothing"),
        pytest.param({"code": -1121}, "carries no", id="an-error-body"),
        pytest.param({SERVER_TIME_FIELD: "1499827319559"}, "carries serverTime=str", id="a-string"),
        pytest.param({SERVER_TIME_FIELD: 1.5}, "carries serverTime=float", id="a-float"),
        pytest.param({SERVER_TIME_FIELD: True}, "carries serverTime=bool", id="a-flag"),
    ],
)
def test_a_body_that_is_not_the_documented_shape_is_refused(payload: object, match: str) -> None:
    """A parsed body and a usable reading are different facts."""
    with pytest.raises(ValidationError, match=match):
        server_time_from(payload, TimestampUnit.MILLISECONDS)


@pytest.mark.parametrize("value", [0, -1], ids=["zero", "before-the-epoch"])
def test_a_server_time_that_could_not_be_a_moment_is_refused(value: int) -> None:
    """Zero is the shape of a missing field that survived parsing."""
    with pytest.raises(ValidationError, match="not a moment the venue could have reported"):
        ServerTimeReading(epoch_micros=value, unit=TimestampUnit.MILLISECONDS)


# ---------------------------------------------------------------------------
# Published buckets
# ---------------------------------------------------------------------------


def test_a_round_trip_bucket_is_one_of_the_declared_bounds() -> None:
    """Cardinality is arithmetic, so the value set can be enumerated here."""
    produced = {
        round_trip_bucket(value * MICROSECONDS_PER_MILLISECOND) for value in range(0, 3_000, 7)
    }
    allowed = {f"<={bound}ms" for bound in ROUND_TRIP_BUCKET_BOUNDS_MILLIS} | {OVERFLOW_BUCKET}
    assert produced <= allowed
    assert len(allowed) == len(ROUND_TRIP_BUCKET_BOUNDS_MILLIS) + 1


def test_an_offset_bucket_keeps_its_sign() -> None:
    """Which way a clock is wrong changes what an operator does about it."""
    assert offset_bucket(500) == "+<=1ms"
    assert offset_bucket(-500) == "-<=1ms"
    assert offset_bucket(10**9) == f"+{OVERFLOW_BUCKET}"
    assert offset_bucket(-(10**9)) == f"-{OVERFLOW_BUCKET}"


def test_the_offset_dimension_has_the_cardinality_its_bounds_imply() -> None:
    """Seven magnitudes and a sign is fourteen values, and no fifteenth."""
    produced = {
        offset_bucket(sign * value * MICROSECONDS_PER_MILLISECOND)
        for sign in (1, -1)
        for value in range(0, 3_000, 11)
    }
    assert len(produced) <= (len(OFFSET_BUCKET_BOUNDS_MILLIS) + 1) * 2


def test_a_sample_publishes_buckets_rather_than_raw_counts() -> None:
    """The record is a diagnostic, so nothing unbounded appears in it."""
    record = _sample(ahead_millis=17, round_trip_millis=40).as_record()
    assert record["offset_millis"] == 17
    assert record["round_trip_bucket"] == "<=50ms"
    assert "round_trip_micros" not in record
    assert "wall_anchor_micros" not in record


# ---------------------------------------------------------------------------
# The venue ceiling
# ---------------------------------------------------------------------------


def test_the_window_ceiling_is_derived_rather_than_written_again() -> None:
    """One place spells 60000, and this is not it."""
    assert max_window_micros() == 60_000 * MICROSECONDS_PER_MILLISECOND
