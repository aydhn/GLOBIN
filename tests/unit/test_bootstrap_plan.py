"""The bootstrap's judgements, exercised from literals rather than from a machine.

Every function in :mod:`globin.domain.bootstrap` takes facts and returns a
verdict, which is what lets this file prove that a wrong interpreter is refused
without owning a wrong interpreter. Nothing here reads the host, and nothing here
is skipped for want of one.
"""

import pytest

from globin.domain.bootstrap import (
    CREATED_PATHS,
    NAMED_IN_SUMMARY,
    BootstrapOutcome,
    BootstrapReport,
    CheckOutcome,
    CheckStatus,
    DependencyReadiness,
    ExitCode,
    HostFacts,
    InterpreterFacts,
    PathLocation,
    ProjectIdentity,
    RecordedPath,
    RuntimeBaseline,
    RuntimePaths,
    SecretReadiness,
    architecture_outcome,
    check_identifiers,
    checks,
    configuration_outcome,
    context_fingerprint,
    dependency_outcome,
    environment_outcome,
    exit_code_for,
    fingerprint_of,
    host_outcome,
    identity_outcome,
    implementation_outcome,
    parse_version,
    paths_outcome,
    readiness_for,
    ready_outcome,
    recorded_absent,
    recorded_inside,
    recorded_outside,
    root_outcome,
    secrets_outcome,
    spec_for,
    version_outcome,
)
from globin.domain.configuration import default_config
from globin.domain.dependency import (
    DependencyInventory,
    DependencyObservation,
    DependencyState,
    LockState,
)
from globin.domain.diagnostics_http import ReadinessReason
from globin.errors import InternalError, ValidationError

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def baseline(**overrides: object) -> RuntimeBaseline:
    """The declared contract, with any field replaced."""
    values: dict[str, object] = {
        "system": "Windows",
        "minimum_release": "10",
        "implementation": "CPython",
        "minor_line": "3.14",
        "minimum_patch": "3.14.5",
        "architecture": "AMD64",
        "pointer_bits": 64,
        "free_threaded": False,
        "allow_prerelease": False,
        "environment_directory": ".venv",
    }
    values.update(overrides)
    return RuntimeBaseline(**values)  # type: ignore[arg-type]


def host(**overrides: object) -> HostFacts:
    """A machine that satisfies the baseline, with any field replaced."""
    values: dict[str, object] = {
        "system": "Windows",
        "release": "11",
        "machine": "AMD64",
        "pointer_bits": 64,
    }
    values.update(overrides)
    return HostFacts(**values)  # type: ignore[arg-type]


def interpreter(**overrides: object) -> InterpreterFacts:
    """An interpreter that satisfies the baseline, with any field replaced."""
    values: dict[str, object] = {
        "implementation": "cpython",
        "version": "3.14.5",
        "release_level": "final",
        "free_threaded": False,
        "executable": recorded_inside(".venv/Scripts/python.exe"),
        "prefix": recorded_inside(".venv"),
        "base_prefix": recorded_outside("C:/Python314"),
        "in_virtual_environment": True,
    }
    values.update(overrides)
    return InterpreterFacts(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A recorded path cannot be built wrong
# ---------------------------------------------------------------------------


def test_a_path_inside_the_project_carries_its_relative_spelling() -> None:
    """The meaningful case, and identical on every machine."""
    recorded = recorded_inside(".venv/Scripts/python.exe")
    assert recorded.location is PathLocation.REPOSITORY
    assert recorded.path == ".venv/Scripts/python.exe"
    assert recorded.fingerprint is None


def test_a_path_outside_the_project_carries_only_a_fingerprint() -> None:
    """The privacy invariant, asserted on the value rather than on the document."""
    recorded = recorded_outside("C:/Users/Someone/AppData/Local/Python")
    assert recorded.location is PathLocation.OUTSIDE
    assert recorded.path is None
    assert recorded.fingerprint
    assert "Someone" not in str(recorded.as_record())


def test_absence_is_recorded_as_absence() -> None:
    """Rather than as an empty string, which would read as a path that is empty."""
    assert recorded_absent().as_record() == {"location": "absent"}


@pytest.mark.parametrize(
    ("location", "path", "fingerprint"),
    [
        pytest.param(PathLocation.REPOSITORY, None, None, id="inside-without-a-spelling"),
        pytest.param(PathLocation.REPOSITORY, ".venv", "abc", id="inside-with-a-fingerprint"),
        pytest.param(PathLocation.OUTSIDE, "C:/x", None, id="outside-with-a-spelling"),
        pytest.param(PathLocation.OUTSIDE, None, None, id="outside-without-a-fingerprint"),
        pytest.param(PathLocation.ABSENT, ".venv", None, id="absent-with-a-spelling"),
        pytest.param(PathLocation.ABSENT, None, "abc", id="absent-with-a-fingerprint"),
    ],
)
def test_a_combination_the_three_outcomes_do_not_describe_is_refused(
    location: PathLocation, path: str | None, fingerprint: str | None
) -> None:
    """A fourth outcome is unrepresentable, which is stronger than being unused."""
    with pytest.raises(ValidationError):
        RecordedPath(location=location, path=path, fingerprint=fingerprint)


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param("/etc/passwd", id="posix-absolute"),
        pytest.param("C:/Users/Someone", id="windows-absolute"),
        pytest.param("", id="empty"),
    ],
)
def test_an_absolute_path_cannot_be_recorded_as_being_inside(spelling: str) -> None:
    """The factory refuses it, so nothing downstream has to remember to."""
    with pytest.raises(ValidationError):
        recorded_inside(spelling)


def test_a_fingerprint_is_stable_and_does_not_contain_its_input() -> None:
    """Stable enough to compare two runs, and reversible by nobody."""
    assert fingerprint_of("C:/Users/Someone") == fingerprint_of("C:/Users/Someone")
    assert fingerprint_of("C:/Users/Someone") != fingerprint_of("C:/Users/Other")
    assert "Someone" not in fingerprint_of("C:/Users/Someone")


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_every_check_identifier_is_stable_and_machine_readable() -> None:
    """These appear in evidence and in runbooks, so they are a contract."""
    assert check_identifiers() == (
        "project.root",
        "runtime.host",
        "runtime.architecture",
        # Phase 028. Judged here because it compares against the same parsed
        # baseline the two checks above use, and because a capability shortfall
        # should be reported before the interpreter is examined in detail.
        "environment.capability",
        "python.implementation",
        "python.version",
        "python.environment",
        "project.identity",
        "dependency.lock",
        "config.valid",
        "paths.runtime",
        # Phase 022. The mutable runtime tree, in dependency order: it must resolve
        # inside its own root before anything can be written, a document must
        # publish before the previous run's can be read, and the lock is probed
        # last because it is the only one whose answer can change between two runs
        # a second apart.
        "paths.boundary",
        "state.persistence",
        "state.previous_run",
        "instance.lock",
        # Phase 031. Placed before the two secrets checks on purpose: "is there a
        # credential store on this machine at all" is the precondition for "did
        # each reference resolve", so an operator on a host with no store is told
        # to fix the machine rather than to fix a credential.
        "runtime.degradation",
        "secrets.required",
        # Phase 029. Placed after `secrets.required` because a credential that
        # does not resolve cannot be asked what it is permitted to do, and
        # before the aggregate because the aggregate is always last.
        "secrets.entitlement",
        "bootstrap.ready",
    )


def test_no_check_is_registered_twice() -> None:
    """A repeated identifier would make `spec_for` answer about whichever came first."""
    identifiers = check_identifiers()
    assert len(set(identifiers)) == len(identifiers)


def test_a_category_is_the_identifier_first_segment() -> None:
    """So that a reader can group findings without a second table."""
    for spec in checks():
        assert spec.category == spec.identifier.split(".", 1)[0]


def test_looking_up_a_check_that_does_not_exist_is_an_internal_error() -> None:
    """A caller naming a check that does not exist has a bug, not bad input."""
    with pytest.raises(InternalError, match="no check is registered"):
        spec_for("invented.check")


# ---------------------------------------------------------------------------
# The host
# ---------------------------------------------------------------------------


def test_a_supported_host_passes() -> None:
    """The control."""
    assert host_outcome(host(), baseline()).status is CheckStatus.PASS


def test_a_host_that_is_not_the_declared_platform_is_refused() -> None:
    """ADR-0009 declares one platform, and this is where that is enforced."""
    outcome = host_outcome(host(system="Linux"), baseline())
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.HOST_UNSUPPORTED
    assert outcome.remediation


def test_a_host_older_than_the_declared_floor_is_refused() -> None:
    """The floor is what CPython and the planned stack both support."""
    assert host_outcome(host(release="8"), baseline()).status is CheckStatus.FAIL


def test_a_host_newer_than_the_floor_passes() -> None:
    """A floor is a floor, not a pin."""
    assert host_outcome(host(release="12"), baseline()).status is CheckStatus.PASS


def test_a_release_that_is_not_a_number_is_treated_as_older_than_any_floor() -> None:
    """Refusing something unreadable is the fail-closed answer."""
    assert host_outcome(host(release="Server"), baseline()).status is CheckStatus.FAIL


@pytest.mark.parametrize(
    "facts",
    [
        pytest.param(host(machine="ARM64"), id="wrong-architecture"),
        pytest.param(host(pointer_bits=32), id="wrong-width"),
    ],
)
def test_an_architecture_the_wheel_survey_did_not_cover_is_refused(facts: HostFacts) -> None:
    """The wheels were surveyed for one target, and this is that target."""
    outcome = architecture_outcome(facts, baseline())
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.HOST_UNSUPPORTED


def test_an_architecture_comparison_ignores_case() -> None:
    """Platforms disagree about capitalisation and nobody should have to care."""
    assert architecture_outcome(host(machine="amd64"), baseline()).status is CheckStatus.PASS


# ---------------------------------------------------------------------------
# The interpreter
# ---------------------------------------------------------------------------


def test_the_declared_implementation_passes() -> None:
    """The control."""
    assert implementation_outcome(interpreter(), baseline()).status is CheckStatus.PASS


def test_another_implementation_is_refused() -> None:
    """A tree verified on CPython has not been verified on anything else."""
    outcome = implementation_outcome(interpreter(implementation="pypy"), baseline())
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.INTERPRETER_MISMATCH


def test_a_free_threaded_build_is_refused_while_the_contract_refuses_it() -> None:
    """A different ABI with a different wheel set, which nobody has surveyed."""
    facts = interpreter(free_threaded=True)
    assert implementation_outcome(facts, baseline()).status is CheckStatus.FAIL
    assert implementation_outcome(facts, baseline(free_threaded=True)).status is CheckStatus.PASS


def test_the_declared_minor_line_passes_at_or_above_the_patch_floor() -> None:
    """The floor is the oldest patch this tree was verified on."""
    assert version_outcome(interpreter(), baseline()).status is CheckStatus.PASS
    assert version_outcome(interpreter(version="3.14.9"), baseline()).status is CheckStatus.PASS


def test_another_minor_line_is_refused_in_both_directions() -> None:
    """The line is exact, so going backwards is as wrong as going forwards."""
    assert version_outcome(interpreter(version="3.13.1"), baseline()).status is CheckStatus.FAIL
    assert version_outcome(interpreter(version="3.15.0"), baseline()).status is CheckStatus.FAIL


def test_a_patch_below_the_verified_floor_is_refused() -> None:
    """An interpreter that went backwards satisfies no floor."""
    assert version_outcome(interpreter(version="3.14.1"), baseline()).status is CheckStatus.FAIL


def test_a_prerelease_is_refused_while_the_contract_refuses_one() -> None:
    """A release candidate can change behaviour before it ships."""
    facts = interpreter(release_level="candidate")
    assert version_outcome(facts, baseline()).status is CheckStatus.FAIL
    assert version_outcome(facts, baseline(allow_prerelease=True)).status is CheckStatus.PASS


def test_a_version_this_reader_cannot_parse_is_unmeasured_rather_than_failed() -> None:
    """Not knowing is a different answer from knowing it is wrong."""
    outcome = version_outcome(interpreter(version="3.14"), baseline())
    assert outcome.status is CheckStatus.UNMEASURED


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("3.14", id="two-parts"),
        pytest.param("3.14.5.1", id="four-parts"),
        pytest.param("3.14.x", id="not-integers"),
        pytest.param("", id="empty"),
    ],
)
def test_a_version_that_is_not_three_integers_does_not_parse(text: str) -> None:
    """Returned as `None` rather than raised, because the caller decides."""
    assert parse_version(text) is None


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


def test_running_from_the_declared_environment_passes() -> None:
    """The control."""
    assert environment_outcome(interpreter(), baseline()).status is CheckStatus.PASS


def test_an_interpreter_outside_any_virtual_environment_is_refused() -> None:
    """Decided on the prefixes rather than on what PATH resolved."""
    facts = interpreter(in_virtual_environment=False)
    outcome = environment_outcome(facts, baseline())
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.ENVIRONMENT_MISMATCH


def test_an_interpreter_from_another_environment_is_refused() -> None:
    """A virtual environment, and not this project's — the subtler mistake."""
    facts = interpreter(prefix=recorded_outside("C:/other/.venv"))
    assert environment_outcome(facts, baseline()).status is CheckStatus.FAIL


def test_an_environment_at_another_declared_directory_is_refused() -> None:
    """The expected location comes from the contract, so it moves when that does."""
    assert environment_outcome(interpreter(), baseline(environment_directory=".env")).status is (
        CheckStatus.FAIL
    )


# ---------------------------------------------------------------------------
# The project
# ---------------------------------------------------------------------------


def test_a_project_root_that_was_found_passes() -> None:
    """The control."""
    outcome = root_outcome(recorded_inside("."), searched_from="from the working directory")
    assert outcome.status is CheckStatus.PASS


def test_a_project_root_that_was_not_found_is_refused() -> None:
    """Refused rather than guessed at, which is the whole point of the bounded search."""
    outcome = root_outcome(recorded_absent(), searched_from="from the working directory")
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.PATHS_UNUSABLE


def test_an_identity_from_installed_metadata_passes() -> None:
    """What was installed is what a console entry point runs."""
    identity = ProjectIdentity(name="globin", version="0.1.0", source="metadata")
    assert identity_outcome(identity, expected_name="globin").status is CheckStatus.PASS


def test_an_identity_read_from_the_source_tree_warns_rather_than_refuses() -> None:
    """The normal state of a checkout nobody has installed, and not a failure.

    Refusing here would make the diagnostic unusable exactly when somebody needs
    it, which is before the environment has been built.
    """
    identity = ProjectIdentity(name="globin", version="0.1.0", source="package")
    outcome = identity_outcome(identity, expected_name="globin")
    assert outcome.status is CheckStatus.WARN
    assert outcome.remediation


def test_an_identity_nobody_could_read_is_refused() -> None:
    """Neither installed metadata nor the package could say what this is."""
    outcome = identity_outcome(None, expected_name="globin")
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.PROJECT_UNIDENTIFIED


def test_a_distribution_under_another_name_is_refused() -> None:
    """Something other than GLOBIN installed under this import name."""
    identity = ProjectIdentity(name="globin-fork", version="9.9.9", source="metadata")
    assert identity_outcome(identity, expected_name="globin").status is CheckStatus.FAIL


# ---------------------------------------------------------------------------
# Dependencies, configuration, paths and secrets
# ---------------------------------------------------------------------------


def test_no_declared_dependency_passes() -> None:
    """The state from Phase 001 to Phase 020, and still a legitimate one."""
    assert dependency_outcome(DependencyReadiness()).status is CheckStatus.PASS


def test_declared_locked_and_installed_passes() -> None:
    """The state Phase 021 created."""
    readiness = DependencyReadiness(declared=("numpy", "pandas"), locked=True)
    outcome = dependency_outcome(readiness)
    assert outcome.status is CheckStatus.PASS
    assert "2 declared" in outcome.summary


def test_a_declared_dependency_that_is_not_installed_is_refused() -> None:
    """And the remediation names the lock rather than the package."""
    readiness = DependencyReadiness(declared=("numpy",), locked=True, missing=("numpy",))
    outcome = dependency_outcome(readiness)
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.DEPENDENCY_UNREADY
    assert "bootstrap.ps1" in outcome.remediation


def test_the_missing_summary_is_bounded_however_many_are_missing() -> None:
    """The bound holds where the list is longest, which is not where anyone runs.

    ``render_human`` holds every row under 200 characters, and this summary was the
    one row that grew with ``project.dependencies``. It listed every missing name,
    so its length depended on how many were *absent* -- zero on any developed host,
    all of them in CI, which installs no runtime dependency at all. Phase 035 added
    a tenth whose name sorts first and the row reached 217.

    So the bound is asserted here, against a list far longer than the project will
    plausibly declare, rather than only in the rendering test that happens to see a
    real one. Sixty names is not a prediction; it is enough to prove the length no
    longer depends on the count.
    """
    many = tuple(f"distribution-with-a-long-name-{index:02d}" for index in range(60))
    outcome = dependency_outcome(DependencyReadiness(declared=many, locked=True, missing=many))
    assert outcome.status is CheckStatus.FAIL
    assert len(outcome.summary) < 160
    assert "60 declared" in outcome.summary
    assert outcome.summary.count("; ") == NAMED_IN_SUMMARY - 1
    assert many[NAMED_IN_SUMMARY] not in outcome.summary


def test_a_declared_dependency_with_no_lock_beside_it_is_refused() -> None:
    """The pairing ADR-0054 enforces, asserted here where a process can see it."""
    readiness = DependencyReadiness(declared=("numpy",), locked=False)
    assert dependency_outcome(readiness).status is CheckStatus.FAIL


def test_a_configuration_that_bound_passes() -> None:
    """The control, using the real declared defaults."""
    outcome = configuration_outcome(default_config())
    assert outcome.status is CheckStatus.PASS
    assert "DEBUG" in outcome.summary


def test_a_configuration_that_refused_is_reported_with_what_it_said() -> None:
    """The message names the setting, so the remediation can name the document."""
    outcome = configuration_outcome(None, problem="logging.min_severity is not a severity")
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.CONFIGURATION_INVALID
    assert "min_severity" in outcome.summary


def test_a_usable_runtime_tree_passes() -> None:
    """And says how many roots were declared against how many were created."""
    outcome = paths_outcome((), RuntimePaths())
    assert outcome.status is CheckStatus.PASS
    assert str(len(CREATED_PATHS)) in outcome.summary


def test_an_unusable_runtime_root_is_refused() -> None:
    """One sentence per root, and the remediation stays inside the project."""
    outcome = paths_outcome(("the evidence root could not be created",), RuntimePaths())
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.PATHS_UNUSABLE


def test_requiring_no_secret_passes_and_says_that_is_why() -> None:
    """A vacuous truth and a skipped check look identical in a log, so it says which."""
    outcome = secrets_outcome(SecretReadiness())
    assert outcome.status is CheckStatus.PASS
    assert "nothing to resolve" in outcome.summary


def test_a_required_reference_that_did_not_resolve_is_refused() -> None:
    """And the count is reported rather than the identifiers, which are not published."""
    readiness = SecretReadiness(required=("binance.api",), unavailable=("binance.api",))
    outcome = secrets_outcome(readiness)
    assert outcome.status is CheckStatus.FAIL
    assert outcome.exit_code is ExitCode.SECRETS_UNREADY


def test_every_required_reference_resolving_passes() -> None:
    """The state Phase 028 will make reachable."""
    outcome = secrets_outcome(SecretReadiness(required=("binance.api",)))
    assert outcome.status is CheckStatus.PASS


def test_a_secret_readiness_record_publishes_a_count_rather_than_identifiers() -> None:
    """A list of what a deployment holds is itself worth withholding."""
    record = SecretReadiness(required=("binance.api", "telegram.token")).as_record()
    assert record == {"required": 2, "unavailable": []}


# ---------------------------------------------------------------------------
# The outcome model
# ---------------------------------------------------------------------------


def passing(identifier: str) -> CheckOutcome:
    """One passing outcome."""
    return CheckOutcome(identifier=identifier, status=CheckStatus.PASS, summary="fine")


def test_a_non_passing_outcome_with_no_remediation_is_refused() -> None:
    """A failure a reader cannot act on is a failure reported twice."""
    with pytest.raises(ValidationError, match="offers no remediation"):
        CheckOutcome(identifier="runtime.host", status=CheckStatus.FAIL, summary="broken")


def test_an_outcome_for_a_check_nobody_registered_is_refused() -> None:
    """So that a typo in an identifier fails where it is written."""
    with pytest.raises(InternalError):
        CheckOutcome(identifier="invented.check", status=CheckStatus.PASS, summary="fine")


def test_a_report_that_concludes_twice_about_one_check_is_refused() -> None:
    """Two answers to one question is a defect in the pipeline, not a finding."""
    with pytest.raises(ValidationError, match="more than once"):
        BootstrapReport(outcomes=(passing("runtime.host"), passing("runtime.host")))


def test_a_report_missing_a_check_is_not_ready() -> None:
    """Stopping early and passing everything must never reduce to one answer."""
    assert not BootstrapReport(outcomes=(passing("project.root"),)).ready


def test_a_report_with_every_check_passing_is_ready() -> None:
    """The control."""
    report = BootstrapReport(outcomes=tuple(passing(name) for name in check_identifiers()))
    assert report.ready
    assert exit_code_for(report) is ExitCode.OK


def test_a_warning_does_not_stop_a_report_being_ready() -> None:
    """WARN means the check ran and starting anyway is defensible.

    The warning check is located by name rather than by index. This test held a
    literal `6` until Phase 028 registered a check ahead of it, at which point
    the index silently addressed a different check and the report concluded twice
    about one identifier — a failure whose message named neither this test's
    subject nor the change that caused it.
    """
    identifier = "project.identity"
    outcomes = [passing(name) for name in check_identifiers()]
    outcomes[check_identifiers().index(identifier)] = CheckOutcome(
        identifier=identifier,
        status=CheckStatus.WARN,
        summary="read from the source tree",
        remediation="install it",
    )
    report = BootstrapReport(outcomes=tuple(outcomes))
    assert report.ready
    assert exit_code_for(report) is ExitCode.OK


def test_the_earliest_failure_decides_the_exit_code() -> None:
    """So that a caller is told the first thing that was wrong, not an arbitrary one."""
    report = BootstrapReport(
        outcomes=(
            passing("project.root"),
            CheckOutcome(
                identifier="runtime.host",
                status=CheckStatus.FAIL,
                summary="wrong",
                remediation="fix it",
            ),
            CheckOutcome(
                identifier="runtime.architecture",
                status=CheckStatus.FAIL,
                summary="also wrong",
                remediation="fix it",
            ),
        )
    )
    assert exit_code_for(report) is ExitCode.HOST_UNSUPPORTED


def test_unmeasured_outranks_failed() -> None:
    """`tools/quality` already applies this rule, and ADR-0045 is why."""
    report = BootstrapReport(
        outcomes=(
            CheckOutcome(
                identifier="project.root",
                status=CheckStatus.FAIL,
                summary="wrong",
                remediation="fix it",
            ),
            CheckOutcome(
                identifier="runtime.host",
                status=CheckStatus.UNMEASURED,
                summary="could not look",
                remediation="fix the declaration",
            ),
        )
    )
    assert exit_code_for(report) is ExitCode.UNMEASURED


def test_every_exit_code_a_check_declares_is_distinct_from_the_generic_ones() -> None:
    """The two ranges cannot collide, which is why the second starts at ten."""
    generic = {ExitCode.OK, ExitCode.USAGE, ExitCode.UNMEASURED}
    for spec in checks():
        if spec.identifier != "bootstrap.ready":
            assert spec.exit_code not in generic


# ---------------------------------------------------------------------------
# The aggregate
# ---------------------------------------------------------------------------


def test_the_aggregate_cannot_answer_for_its_own_answer() -> None:
    """Handing it an outcome for itself is a bug in the pipeline."""
    with pytest.raises(InternalError):
        ready_outcome((passing("bootstrap.ready"),))


def test_an_incomplete_run_is_reported_as_incomplete() -> None:
    """Three of eleven checks is not eleven passes."""
    outcome = ready_outcome((passing("project.root"),))
    assert outcome.status is CheckStatus.FAIL
    assert "incomplete" in outcome.summary


def test_the_aggregate_names_what_did_not_pass() -> None:
    """So that the last line of the report is actionable on its own."""
    outcomes = [passing(name) for name in check_identifiers()[:-1]]
    outcomes[1] = CheckOutcome(
        identifier="runtime.host",
        status=CheckStatus.FAIL,
        summary="wrong",
        remediation="fix it",
    )
    outcome = ready_outcome(tuple(outcomes))
    assert outcome.status is CheckStatus.FAIL
    assert "runtime.host" in outcome.summary


def test_the_aggregate_stays_one_line_when_everything_fails() -> None:
    """The worst host, which is the one whose report most needs reading.

    Every check failing is the state a fresh clone with no environment is in, and
    the aggregate is the line an operator reads first. Joined whole it was 392
    characters against ``render_human``'s 200 -- the same defect as the
    ``dependency.lock`` row above, in the same function, reachable without adopting
    anything. Nothing is lost by counting: every failing check has its own row and
    its own remediation directly above this line.
    """
    outcomes = tuple(
        CheckOutcome(
            identifier=name, status=CheckStatus.FAIL, summary="wrong", remediation="fix it"
        )
        for name in check_identifiers()[:-1]
    )
    outcome = ready_outcome(outcomes)
    assert outcome.status is CheckStatus.FAIL
    assert len(outcome.summary) < 160
    assert f"{len(outcomes)} check(s)" in outcome.summary
    assert outcomes[NAMED_IN_SUMMARY].identifier not in outcome.summary


def test_the_aggregate_passes_when_everything_before_it_did() -> None:
    """The control."""
    outcomes = tuple(passing(name) for name in check_identifiers()[:-1])
    assert ready_outcome(outcomes).status is CheckStatus.PASS


def test_the_aggregate_warns_when_something_before_it_warned() -> None:
    """A warning is carried up rather than swallowed by a passing aggregate."""
    outcomes = [passing(name) for name in check_identifiers()[:-1]]
    outcomes[6] = CheckOutcome(
        identifier="project.identity",
        status=CheckStatus.WARN,
        summary="read from the source tree",
        remediation="install it",
    )
    outcome = ready_outcome(tuple(outcomes))
    assert outcome.status is CheckStatus.WARN
    assert "project.identity" in outcome.summary


# ---------------------------------------------------------------------------
# The context
# ---------------------------------------------------------------------------


def identity() -> ProjectIdentity:
    """An installed identity."""
    return ProjectIdentity(name="globin", version="0.1.0", source="metadata")


def test_the_fingerprint_is_deterministic_over_unchanged_facts() -> None:
    """Two runs on an unchanged host must agree, or the digest identifies nothing."""
    arguments = {
        "identity": identity(),
        "host": host(),
        "interpreter": interpreter(),
        "dependencies": DependencyReadiness(declared=("numpy",), locked=True),
    }
    assert context_fingerprint(**arguments) == context_fingerprint(**arguments)  # type: ignore[arg-type]


def test_the_fingerprint_changes_when_something_worth_knowing_about_changes() -> None:
    """A digest that ignored the interpreter would be a digest of nothing useful."""
    first = context_fingerprint(
        identity=identity(),
        host=host(),
        interpreter=interpreter(),
        dependencies=DependencyReadiness(),
    )
    second = context_fingerprint(
        identity=identity(),
        host=host(),
        interpreter=interpreter(version="3.14.9"),
        dependencies=DependencyReadiness(),
    )
    assert first != second


def test_the_fingerprint_never_contains_a_path_from_outside_the_project() -> None:
    """The recorded form participates, not the real one."""
    digest = context_fingerprint(
        identity=identity(),
        host=host(),
        interpreter=interpreter(base_prefix=recorded_outside("C:/Users/Someone/Python")),
        dependencies=DependencyReadiness(),
    )
    assert "Someone" not in digest


def test_an_outcome_cannot_carry_a_context_the_report_does_not_justify() -> None:
    """Fail-closed as a property of the type rather than of a function.

    A run that failed cannot hand anything downstream even if the pipeline tried,
    because the object that would authorise it refuses to exist.
    """
    with pytest.raises(ValidationError, match="not ready"):
        BootstrapOutcome(
            report=BootstrapReport(outcomes=(passing("project.root"),)),
            context=object(),  # type: ignore[arg-type]
        )


def test_an_outcome_with_no_context_is_not_ready() -> None:
    """`ready` is the presence of the context, not a flag beside it."""
    outcome = BootstrapOutcome(report=BootstrapReport(outcomes=(passing("project.root"),)))
    assert not outcome.ready
    assert outcome.exit_code is ExitCode.OK


# ---------------------------------------------------------------------------
# Phase 029: what the inventory adds to the dependency verdict
# ---------------------------------------------------------------------------


def _inventory(
    *observations: DependencyObservation,
    lock_state: LockState = LockState.PRESENT,
    lock_version: str = "1.0",
    unknown_keys: tuple[str, ...] = (),
) -> DependencyInventory:
    return DependencyInventory(
        observations=observations,
        lock_state=lock_state,
        lock_version=lock_version,
        unknown_keys=unknown_keys,
    )


def _ready(inventory: DependencyInventory) -> DependencyReadiness:
    """A readiness whose three original fields are all satisfied.

    Every test below therefore isolates the inventory: the older fields would
    have reported this host as ready, which is exactly the blindness Phase 029
    removes.
    """
    return DependencyReadiness(declared=("numpy",), locked=True, inventory=inventory)


def test_a_lock_version_this_globin_cannot_read_refuses_rather_than_guessing() -> None:
    """PEP 751 states this as a MUST, not as a warning."""
    outcome = dependency_outcome(
        _ready(_inventory(lock_state=LockState.UNSUPPORTED, lock_version="2.0"))
    )
    assert outcome.status is CheckStatus.FAIL
    assert "2.0" in outcome.summary


def test_a_lock_that_exists_and_cannot_be_read_refuses() -> None:
    outcome = dependency_outcome(_ready(_inventory(lock_state=LockState.UNREADABLE)))
    assert outcome.status is CheckStatus.FAIL
    assert "could not be read" in outcome.summary


def test_a_lock_resolved_for_another_interpreter_refuses() -> None:
    outcome = dependency_outcome(_ready(_inventory(lock_state=LockState.INTERPRETER_EXCLUDED)))
    assert outcome.status is CheckStatus.FAIL
    assert "different interpreter" in outcome.summary


def test_a_version_that_drifted_from_the_lock_refuses_and_names_it() -> None:
    """The finding the three original fields could not make.

    `declared`, `locked` and `missing` all say this host is ready: numpy is
    declared, a lock accompanies it, and it is installed. It is installed at the
    wrong version.
    """
    outcome = dependency_outcome(
        _ready(
            _inventory(
                DependencyObservation(
                    name="numpy",
                    state=DependencyState.VERSION_MISMATCH,
                    locked_version="2.5.2",
                    installed_version="2.6.0",
                )
            )
        )
    )
    assert outcome.status is CheckStatus.FAIL
    assert "numpy" in outcome.summary
    assert "bootstrap.ps1" in outcome.remediation


def test_an_unknown_key_warns_and_does_not_stop_a_start_up() -> None:
    """PEP 751 makes this a SHOULD-warn, and `exit_code_for` ignores a warning."""
    outcome = dependency_outcome(_ready(_inventory(unknown_keys=("future-key",))))
    assert outcome.status is CheckStatus.WARN
    assert "future-key" in outcome.summary


def test_an_environment_that_agrees_with_its_lock_passes() -> None:
    outcome = dependency_outcome(
        _ready(
            _inventory(
                DependencyObservation(
                    name="numpy",
                    state=DependencyState.SATISFIED,
                    locked_version="2.5.2",
                    installed_version="2.5.2",
                )
            )
        )
    )
    assert outcome.status is CheckStatus.PASS


def test_a_readiness_with_no_inventory_behaves_exactly_as_it_did_before() -> None:
    """`None` means not measured, and must not become a refusal by itself."""
    outcome = dependency_outcome(
        DependencyReadiness(declared=("numpy",), locked=True, inventory=None)
    )
    assert outcome.status is CheckStatus.PASS


# ---------------------------------------------------------------------------
# Phase 029: the exit code to readiness mapping
# ---------------------------------------------------------------------------


def test_every_exit_code_maps_to_a_readiness_reason() -> None:
    """Total by construction, and asserted anyway.

    A later phase adding an exit code cannot make this raise; what it can do is
    leave the new code reported as `unknown`, which this test makes visible.
    """
    for code in ExitCode:
        assert isinstance(readiness_for(code), ReadinessReason)


def test_the_dependency_exit_code_is_what_finally_sets_the_dependency_reason() -> None:
    """`ReadinessReason.DEPENDENCY_UNREADY` had no producer at all until now."""
    assert readiness_for(ExitCode.DEPENDENCY_UNREADY) is ReadinessReason.DEPENDENCY_UNREADY


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        pytest.param(ExitCode.OK, ReadinessReason.READY, id="ok"),
        pytest.param(
            ExitCode.CONFIGURATION_INVALID,
            ReadinessReason.CONFIGURATION_INVALID,
            id="configuration",
        ),
        pytest.param(ExitCode.SECRETS_UNREADY, ReadinessReason.SECRETS_UNREADY, id="secrets"),
        pytest.param(
            ExitCode.HOST_UNSUPPORTED,
            ReadinessReason.ENVIRONMENT_INCOMPATIBLE,
            id="host",
        ),
        pytest.param(
            ExitCode.ENVIRONMENT_INCOMPATIBLE,
            ReadinessReason.ENVIRONMENT_INCOMPATIBLE,
            id="capability",
        ),
        pytest.param(ExitCode.INTERNAL, ReadinessReason.UNKNOWN, id="internal-is-unknown"),
    ],
)
def test_an_exit_code_maps_to_the_class_a_reader_can_act_on(
    code: ExitCode, reason: ReadinessReason
) -> None:
    assert readiness_for(code) is reason


def test_every_reason_a_bootstrap_can_reach_is_produced_by_some_exit_code() -> None:
    """A member nothing can set is vocabulary rather than a capability.

    The three lifecycle reasons are excluded because they describe a running
    process rather than a start-up verdict, and nothing here can produce them.
    """
    lifecycle = {
        ReadinessReason.STARTING,
        ReadinessReason.STOPPING,
    }
    produced = {readiness_for(code) for code in ExitCode}
    assert set(ReadinessReason) - lifecycle == produced
