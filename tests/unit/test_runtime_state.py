"""The runtime-state judgements, exercised from literals.

Nothing here touches a filesystem, takes a lock or reads a clock. A boundary
violation is described without creating one, and an unclean previous run is
judged without crashing a process — which is the point of keeping these
judgements in the domain layer where `pathlib` cannot reach.

The rules being pinned are the ones a plausible refactor breaks: that a segment
cannot escape its tree, that an open lifecycle record and a closed one are
different shapes, and that a record is never allowed to imply a live process.
"""

import pytest

from globin.domain.bootstrap import CheckStatus, ExitCode, recorded_outside, spec_for
from globin.domain.runtime_state import (
    InstanceMetadata,
    LifecycleRecord,
    LifecycleStatus,
    RuntimeArea,
    RuntimeLayout,
    ShutdownReason,
    boundary_outcome,
    child_problems,
    lock_outcome,
    persistence_outcome,
    previous_run_outcome,
    read_lifecycle,
    segment_problems,
)
from globin.errors import ValidationError

ROOT = recorded_outside("C:/somewhere/GLOBIN")


def a_record(**overrides: object) -> LifecycleRecord:
    """An open lifecycle record, with any field replaced."""
    fields: dict[str, object] = {
        "status": LifecycleStatus.RUNNING,
        "instance_id": "a" * 32,
        "pid": 4321,
        "started_at": "2026-08-16T12:00:00Z",
    }
    fields.update(overrides)
    return LifecycleRecord(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Segments and children
# ---------------------------------------------------------------------------


def test_a_plain_directory_name_is_accepted() -> None:
    assert segment_problems("state", named="state") == ()


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        pytest.param("..", "leaves the tree", id="traversal"),
        pytest.param(" .. ", "leaves the tree", id="traversal with whitespace"),
        pytest.param("a/b", "path separator", id="a forward separator"),
        pytest.param("a\\b", "path separator", id="a backward separator"),
        pytest.param("../evil", "path separator", id="traversal through a separator"),
        pytest.param("C:", "names a drive", id="a bare drive"),
        pytest.param("C:/Windows", "path separator", id="an absolute path"),
        pytest.param("", "is empty", id="empty"),
    ],
)
def test_a_segment_that_could_leave_the_tree_is_refused(segment: str, expected: str) -> None:
    """Each of these is a real route out, not a hypothetical one.

    A separator smuggles a second level past a check that only looked at one; a
    drive letter makes the "relative" segment absolute, which wins the join
    outright and lands the tree wherever the string said.
    """
    problems = segment_problems(segment, named="state")
    assert problems
    assert any(expected in problem for problem in problems)


def test_an_empty_segment_reports_once_and_stops() -> None:
    """Every later rule would also fire on the empty string, saying nothing new."""
    assert len(segment_problems("", named="state")) == 1


def test_a_child_name_is_held_to_the_same_rules() -> None:
    assert child_problems("lifecycle.json", area=RuntimeArea.STATE) == ()
    assert child_problems("../lifecycle.json", area=RuntimeArea.STATE)


def test_the_child_message_names_the_area_a_reader_must_look_in() -> None:
    problems = child_problems("..", area=RuntimeArea.TMP)
    assert any("tmp entry" in problem for problem in problems)


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------


def test_the_declared_layout_is_four_areas_under_one_namespace() -> None:
    layout = RuntimeLayout()
    assert layout.namespace == "GLOBIN"
    assert set(layout.areas()) == set(RuntimeArea)
    assert layout.segment_for(RuntimeArea.STATE) == "state"


def test_the_area_order_is_fixed_rather_than_sorted() -> None:
    """Two runs must report their problems in the same order.

    A manifest built from an unordered walk would differ between runs of one
    tree, which is the determinism every gate here is checked against.
    """
    assert RuntimeLayout().areas() == RuntimeLayout().areas()


@pytest.mark.parametrize(
    "field",
    ["namespace", "state", "cache", "run", "tmp"],
)
def test_a_layout_that_could_escape_its_own_root_cannot_be_built(field: str) -> None:
    """Validated at construction, so the adapter never holds a value it must refuse."""
    with pytest.raises(ValidationError, match="leaves the tree"):
        RuntimeLayout(**{field: ".."})


def test_a_layout_reports_every_bad_segment_at_once() -> None:
    with pytest.raises(ValidationError) as caught:
        RuntimeLayout(state="..", cache="a/b")
    assert "state" in str(caught.value)
    assert "cache" in str(caught.value)


# ---------------------------------------------------------------------------
# Instance metadata
# ---------------------------------------------------------------------------


def test_instance_metadata_publishes_a_recorded_root_and_no_path() -> None:
    """The tree lives under a user profile, and a user profile names its owner."""
    record = InstanceMetadata(
        version="0.1.0",
        pid=4321,
        instance_id="b" * 32,
        started_at="2026-08-16T12:00:00Z",
        profile="default",
        root=ROOT,
    ).as_record()
    assert record["root"] == {"location": "outside", "fingerprint": ROOT.fingerprint}
    assert "C:/somewhere" not in str(record)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        pytest.param("instance_id", "", "needs an identifier", id="no identifier"),
        pytest.param("pid", 0, "not a process", id="pid zero"),
        pytest.param("pid", -1, "not a process", id="a negative pid"),
    ],
)
def test_instance_metadata_refuses_a_record_that_identifies_nothing(
    field: str, value: object, expected: str
) -> None:
    fields: dict[str, object] = {
        "version": "0.1.0",
        "pid": 4321,
        "instance_id": "b" * 32,
        "started_at": "2026-08-16T12:00:00Z",
        "profile": "default",
        "root": ROOT,
    }
    fields[field] = value
    with pytest.raises(ValidationError, match=expected):
        InstanceMetadata(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The lifecycle record
# ---------------------------------------------------------------------------


def test_an_open_record_carries_no_ending() -> None:
    record = a_record()
    assert not record.ended_cleanly
    assert record.as_record()["finished_at"] is None


def test_a_closed_record_carries_all_three_ending_fields() -> None:
    record = a_record(
        status=LifecycleStatus.STOPPED,
        finished_at="2026-08-16T12:05:00Z",
        reason=ShutdownReason.COMPLETED,
        exit_code=0,
    )
    assert record.ended_cleanly
    assert record.as_record()["reason"] == "completed"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"status": LifecycleStatus.STOPPED},
            "needs no finishing time",
            id="stopped with no finishing time",
        ),
        pytest.param(
            {"finished_at": "2026-08-16T12:05:00Z"},
            "carries no finishing time",
            id="running with a finishing time",
        ),
        pytest.param({"exit_code": 0}, "did not stop", id="running with an exit code"),
        pytest.param({"instance_id": ""}, "needs an identifier", id="no identifier"),
    ],
)
def test_a_record_whose_shape_contradicts_its_status_is_unrepresentable(
    overrides: dict[str, object], expected: str
) -> None:
    """The shape and the status cannot contradict each other.

    A stopped run that ended at no particular moment, and a running one that has
    already returned, are both nonsense the type refuses to hold.
    """
    with pytest.raises(ValidationError, match=expected):
        a_record(**overrides)


def test_a_stopped_record_must_say_why_it_stopped() -> None:
    with pytest.raises(ValidationError, match="must say why"):
        a_record(status=LifecycleStatus.STOPPED, finished_at="2026-08-16T12:05:00Z", exit_code=0)


def test_a_record_round_trips_through_its_published_form() -> None:
    record = a_record(
        status=LifecycleStatus.STOPPED,
        finished_at="2026-08-16T12:05:00Z",
        reason=ShutdownReason.SIGNALLED,
        exit_code=0,
    )
    assert read_lifecycle(record.as_record()) == record


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param("not an object", "must be an object", id="not an object"),
        pytest.param({}, "announces schema version", id="no version"),
        pytest.param({"schema_version": 2}, "announces schema version", id="a future version"),
    ],
)
def test_something_that_is_not_a_lifecycle_record_is_refused(
    document: object, expected: str
) -> None:
    """A record from a future GLOBIN is refused rather than read anyway.

    Guessing at a shape somebody else defined is how a reader ends up confidently
    reporting the wrong thing about a run it did not understand.
    """
    with pytest.raises(ValidationError, match=expected):
        read_lifecycle(document)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        pytest.param("status", "dancing", "expected one of", id="an unknown status"),
        pytest.param("reason", "boredom", "expected one of", id="an unknown reason"),
        pytest.param("instance_id", 7, "expected a string", id="a numeric identifier"),
        pytest.param("pid", "4321", "expected an integer", id="a textual pid"),
        pytest.param("pid", True, "expected an integer", id="a boolean pid"),
        pytest.param("started_at", None, "expected a string", id="no start time"),
        pytest.param("finished_at", 7, "expected a string or nothing", id="a numeric ending"),
    ],
)
def test_a_field_of_the_wrong_type_is_refused_by_name(
    field: str, value: object, expected: str
) -> None:
    """A boolean pid is the row worth having.

    Python makes `True` an integer, so a record saying `pid = true` would
    otherwise read as process one.
    """
    document = dict(a_record().as_record())
    document[field] = value
    with pytest.raises(ValidationError, match=expected):
        read_lifecycle(document)


# ---------------------------------------------------------------------------
# The four check judgements
# ---------------------------------------------------------------------------


def test_a_tree_that_resolves_inside_its_root_passes() -> None:
    outcome = boundary_outcome((), RuntimeLayout())
    assert outcome.status is CheckStatus.PASS
    assert "5 areas" in outcome.summary


def test_a_tree_that_escapes_its_root_fails_with_a_remediation() -> None:
    outcome = boundary_outcome(("the tmp area resolves outside the runtime root",), RuntimeLayout())
    assert outcome.status is CheckStatus.FAIL
    assert outcome.remediation


def test_a_working_state_mechanism_passes_and_a_broken_one_fails() -> None:
    assert persistence_outcome("").status is CheckStatus.PASS
    assert persistence_outcome("the state area is read-only").status is CheckStatus.FAIL


def test_no_previous_run_is_a_pass_rather_than_a_warning() -> None:
    """A first run on a clean machine has nothing to report and is not suspicious."""
    outcome = previous_run_outcome(None)
    assert outcome.status is CheckStatus.PASS


def test_a_previous_run_that_ended_cleanly_passes() -> None:
    outcome = previous_run_outcome(
        a_record(
            status=LifecycleStatus.STOPPED,
            finished_at="2026-08-16T12:05:00Z",
            reason=ShutdownReason.COMPLETED,
            exit_code=0,
        )
    )
    assert outcome.status is CheckStatus.PASS


def test_an_open_previous_record_warns_and_does_not_refuse() -> None:
    """The rule the whole design turns on.

    Whether an instance is running is the lock's question and only the lock's.
    The process that wrote an open record may have died a week ago, so refusing
    on it would make a crash permanently fatal.
    """
    outcome = previous_run_outcome(a_record())
    assert outcome.status is CheckStatus.WARN
    assert "uncleanly" in outcome.summary
    assert "coordinator lock" in outcome.remediation


def test_an_unreadable_previous_record_fails_with_a_way_out() -> None:
    outcome = previous_run_outcome(None, "lifecycle.json is not valid JSON")
    assert outcome.status is CheckStatus.FAIL
    assert "Delete it" in outcome.remediation


def test_an_available_lock_passes() -> None:
    assert lock_outcome(acquired=True).status is CheckStatus.PASS


def test_a_held_lock_fails_and_tells_the_operator_not_to_delete_the_file() -> None:
    """The remediation is load-bearing.

    Deleting the lock file is the first thing somebody tries and the one thing
    that cannot help: the file is not what decides ownership.
    """
    outcome = lock_outcome(acquired=False, problem="another coordinator holds it")
    assert outcome.status is CheckStatus.FAIL
    assert "Do not delete the lock file" in outcome.remediation


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        pytest.param("paths.boundary", ExitCode.PATHS_UNUSABLE, id="boundary"),
        pytest.param("state.persistence", ExitCode.RUNTIME_PERSISTENCE_FAILED, id="persistence"),
        pytest.param("state.previous_run", ExitCode.RUNTIME_STATE_CORRUPT, id="previous run"),
        pytest.param("instance.lock", ExitCode.INSTANCE_ALREADY_ACTIVE, id="lock"),
    ],
)
def test_each_new_check_carries_the_exit_code_a_launcher_will_branch_on(
    identifier: str, expected: ExitCode
) -> None:
    """One code per failure class, so a launcher need not parse English."""
    assert spec_for(identifier).exit_code is expected
