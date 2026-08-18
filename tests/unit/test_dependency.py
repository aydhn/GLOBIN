"""Dependency judgement: how a divergence is classified, and what stays stable.

Every environment below is a literal. A package excluded by a Linux marker, a
lock resolved for an interpreter this is not, and a distribution installed two
patch releases away from what the lock names are all exercised here and none of
them exists on this machine -- which is the whole reason the judgement lives in
the domain and the reading lives in the adapter.

Two properties carry the most weight, and both are about *not* reporting a
difference that is not there: a package a marker excludes is `not_applicable`
rather than `missing`, and the fingerprint does not move when the lock's producer
does.
"""

import dataclasses

import pytest

from globin.domain.dependency import (
    FINGERPRINT_LENGTH,
    FINGERPRINT_SCHEMA,
    DependencyInventory,
    DependencyObservation,
    DependencyProjection,
    DependencyState,
    LockedEntry,
    LockReading,
    LockState,
    admits_python,
    applies_here,
    canonical_name,
    dependency_fingerprint,
    inventory_from,
    requirement_name,
    versions_agree,
)

WINDOWS = {"sys_platform": "win32", "platform_system": "Windows"}
LINUX_ONLY = "sys_platform == 'linux'"
HERE = "3.14.5"


def reading(*entries: LockedEntry, **kwargs: object) -> LockReading:
    """A present lock carrying the given entries."""
    return LockReading(
        state=kwargs.pop("state", LockState.PRESENT),  # type: ignore[arg-type]
        lock_version=kwargs.pop("lock_version", "1.0"),  # type: ignore[arg-type]
        entries=entries,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# The five states
# ---------------------------------------------------------------------------


def test_a_locked_and_installed_distribution_at_the_same_release_is_satisfied() -> None:
    inventory = inventory_from(
        declared=(),
        reading=reading(LockedEntry(name="numpy", version="2.5.2")),
        installed={"numpy": "2.5.2"},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert [observation.state for observation in inventory.observations] == [
        DependencyState.SATISFIED
    ]


def test_a_locked_distribution_that_is_not_installed_is_missing() -> None:
    inventory = inventory_from(
        declared=(),
        reading=reading(LockedEntry(name="numpy", version="2.5.2")),
        installed={},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert inventory.observations[0].state is DependencyState.MISSING


def test_a_distribution_installed_at_another_version_is_a_mismatch() -> None:
    """The state Phase 029 exists to make visible.

    Before this phase it was not merely unreported but unrepresentable, because
    the installed version was read and then discarded.
    """
    inventory = inventory_from(
        declared=(),
        reading=reading(LockedEntry(name="numpy", version="2.5.2")),
        installed={"numpy": "2.6.0"},
        environment=WINDOWS,
        python_version=HERE,
    )
    observation = inventory.observations[0]
    assert observation.state is DependencyState.VERSION_MISMATCH
    assert observation.locked_version == "2.5.2"
    assert observation.installed_version == "2.6.0"


def test_a_declared_root_the_lock_does_not_name_is_unlocked() -> None:
    inventory = inventory_from(
        declared=("brand-new>=1.0",),
        reading=reading(LockedEntry(name="numpy", version="2.5.2")),
        installed={"numpy": "2.5.2"},
        environment=WINDOWS,
        python_version=HERE,
    )
    states = {observation.name: observation.state for observation in inventory.observations}
    assert states["brand-new"] is DependencyState.UNLOCKED


def test_a_package_a_marker_excludes_is_not_applicable_rather_than_missing() -> None:
    """The state that stops the inventory crying wolf.

    Without it, a package legitimately absent on this platform is a false
    refusal -- and this repository would ship one the day it declares its first
    marked dependency.
    """
    inventory = inventory_from(
        declared=(),
        reading=reading(LockedEntry(name="posix-thing", version="1.0", marker=LINUX_ONLY)),
        installed={},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert inventory.observations[0].state is DependencyState.NOT_APPLICABLE


def test_a_package_whose_requires_python_excludes_this_interpreter_is_not_applicable() -> None:
    inventory = inventory_from(
        declared=(),
        reading=reading(LockedEntry(name="old-only", version="1.0", requires_python="<3.10")),
        installed={},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert inventory.observations[0].state is DependencyState.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Lock states that short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(LockState.ABSENT, id="absent"),
        pytest.param(LockState.UNREADABLE, id="unreadable"),
        pytest.param(LockState.UNSUPPORTED, id="unsupported"),
    ],
)
def test_an_unusable_lock_reports_its_state_and_no_observations(
    state: LockState,
) -> None:
    """Reporting every declared root as unlocked would drown the real finding."""
    inventory = inventory_from(
        declared=("numpy>=2.5.2", "pandas>=3.0.5"),
        reading=LockReading(state=state),
        installed={},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert inventory.lock_state is state
    assert inventory.observations == ()


def test_a_lock_resolved_for_another_interpreter_says_so_rather_than_comparing() -> None:
    inventory = inventory_from(
        declared=(),
        reading=reading(LockedEntry(name="numpy", version="2.5.2"), requires_python=">=3.20"),
        installed={},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert inventory.lock_state is LockState.INTERPRETER_EXCLUDED
    assert inventory.observations == ()


def test_a_newer_minor_lock_still_compares_its_packages() -> None:
    """PEP 751 makes an unknown key a warning, not a refusal, so entries survive."""
    inventory = inventory_from(
        declared=(),
        reading=reading(
            LockedEntry(name="numpy", version="2.5.2"),
            state=LockState.NEWER_MINOR,
            unknown_keys=("wat",),
        ),
        installed={"numpy": "2.5.2"},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert inventory.lock_state is LockState.NEWER_MINOR
    assert inventory.unknown_keys == ("wat",)
    assert inventory.observations[0].state is DependencyState.SATISFIED


def test_a_declared_requirement_that_cannot_be_parsed_is_skipped() -> None:
    """A malformed `pyproject.toml` is a real possibility on somebody's machine.

    Reporting it as a distribution named the empty string would put a fiction in
    the inventory; raising would report a crash where a refusal belongs.
    """
    inventory = inventory_from(
        declared=(">=not a requirement", "numpy>=2.5.2"),
        reading=reading(LockedEntry(name="numpy", version="2.5.2")),
        installed={"numpy": "2.5.2"},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert [observation.name for observation in inventory.observations] == ["numpy"]


def test_an_installed_distribution_nothing_declares_is_not_reported() -> None:
    """A capability limit, stated rather than hidden.

    Deciding an extra distribution is unexpected needs the seeded-package list,
    which lives in a file the wheel does not ship.
    """
    inventory = inventory_from(
        declared=(),
        reading=reading(LockedEntry(name="numpy", version="2.5.2")),
        installed={"numpy": "2.5.2", "pip": "26.1.2", "setuptools": "80.0"},
        environment=WINDOWS,
        python_version=HERE,
    )
    assert [observation.name for observation in inventory.observations] == ["numpy"]


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("locked", "installed", "expected"),
    [
        pytest.param("1.0", "1.0", True, id="identical"),
        pytest.param("1.0", "1.0.0", True, id="same-release-different-spelling"),
        pytest.param("1.0.0", "1.0", True, id="same-release-reversed"),
        pytest.param("1.0", "1.0.1", False, id="different-release"),
        pytest.param("", "1.0", False, id="nothing-locked"),
        pytest.param("1.0", "", False, id="nothing-installed"),
        pytest.param("", "", False, id="neither"),
        pytest.param("not-a-version", "not-a-version", True, id="unparseable-but-equal"),
        pytest.param("not-a-version", "other", False, id="unparseable-and-different"),
    ],
)
def test_versions_are_compared_as_releases_rather_than_as_text(
    locked: str, installed: str, expected: bool
) -> None:
    assert versions_agree(locked, installed) is expected


@pytest.mark.parametrize(
    ("specifier", "version", "expected"),
    [
        pytest.param("", HERE, True, id="empty-admits-everything"),
        pytest.param(">=3.12", HERE, True, id="admitted"),
        pytest.param(">=3.20", HERE, False, id="excluded"),
        pytest.param("<3.10", HERE, False, id="excluded-upper"),
        pytest.param("not a specifier", HERE, True, id="unparseable-admits"),
        pytest.param(">=3.12", "3.15.0a1", True, id="prerelease-still-compared"),
    ],
)
def test_requires_python_admits_rather_than_excludes_when_it_cannot_decide(
    specifier: str, version: str, expected: bool
) -> None:
    """Excluding would drop a package out of the inventory and report nothing."""
    assert admits_python(specifier, version) is expected


def test_an_unparseable_marker_admits_so_a_real_absence_is_still_seen() -> None:
    entry = LockedEntry(name="x", version="1", marker="this is not a marker")
    assert applies_here(entry, WINDOWS, HERE) is True


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("Foo.Bar", "foo-bar", id="dot-and-case"),
        pytest.param("foo_bar", "foo-bar", id="underscore"),
        pytest.param("FOO---BAR", "foo-bar", id="runs-collapse"),
        pytest.param("numpy", "numpy", id="already-canonical"),
    ],
)
def test_names_are_normalised_to_their_pep_503_form(raw: str, expected: str) -> None:
    assert canonical_name(raw) == expected


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        pytest.param("numpy>=2.5.2", "numpy", id="simple"),
        pytest.param("Foo_Bar >= 1", "foo-bar", id="normalised"),
        pytest.param("foo[extra]>=1", "foo", id="with-extra"),
        pytest.param("foo>=1; sys_platform == 'linux'", "foo", id="with-marker"),
        pytest.param("", "", id="empty"),
        pytest.param(">=not a requirement", "", id="unparseable"),
    ],
)
def test_a_requirement_name_is_parsed_rather_than_split(requirement: str, expected: str) -> None:
    """The parser the predecessor's docstring predicted would one day be needed."""
    assert requirement_name(requirement) == expected


# ---------------------------------------------------------------------------
# The fingerprint
# ---------------------------------------------------------------------------


def projection(*observations: DependencyObservation) -> DependencyProjection:
    return DependencyProjection(observations=observations, lock_state=LockState.PRESENT)


SATISFIED_NUMPY = DependencyObservation(
    name="numpy",
    state=DependencyState.SATISFIED,
    locked_version="2.5.2",
    installed_version="2.5.2",
)
SATISFIED_PANDAS = DependencyObservation(
    name="pandas",
    state=DependencyState.SATISFIED,
    locked_version="3.0.5",
    installed_version="3.0.5",
)


def test_a_fingerprint_is_thirty_two_hexadecimal_characters() -> None:
    value = dependency_fingerprint(projection(SATISFIED_NUMPY))
    assert len(value) == FINGERPRINT_LENGTH
    assert set(value) <= set("0123456789abcdef")


def test_the_schema_is_mixed_into_the_digest() -> None:
    assert FINGERPRINT_SCHEMA in projection(SATISFIED_NUMPY).canonical()


def test_the_same_environment_fingerprints_the_same_twice() -> None:
    first = projection(SATISFIED_NUMPY, SATISFIED_PANDAS)
    second = projection(SATISFIED_NUMPY, SATISFIED_PANDAS)
    assert dependency_fingerprint(first) == dependency_fingerprint(second)


def test_the_order_observations_arrive_in_does_not_move_the_fingerprint() -> None:
    """A relock that reorders `[[packages]]` must not look like a changed environment."""
    forwards = projection(SATISFIED_NUMPY, SATISFIED_PANDAS)
    backwards = projection(SATISFIED_PANDAS, SATISFIED_NUMPY)
    assert dependency_fingerprint(forwards) == dependency_fingerprint(backwards)


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param(dataclasses.replace(SATISFIED_NUMPY, name="scipy"), id="name"),
        pytest.param(
            dataclasses.replace(SATISFIED_NUMPY, state=DependencyState.MISSING),
            id="state",
        ),
        pytest.param(
            dataclasses.replace(SATISFIED_NUMPY, locked_version="2.5.3"),
            id="locked-version",
        ),
        pytest.param(
            dataclasses.replace(SATISFIED_NUMPY, installed_version="2.5.3"),
            id="installed-version",
        ),
    ],
)
def test_changing_any_field_of_any_observation_moves_the_fingerprint(
    changed: DependencyObservation,
) -> None:
    before = projection(SATISFIED_NUMPY)
    after = projection(changed)
    assert dependency_fingerprint(before) != dependency_fingerprint(after)


def test_the_lock_state_is_part_of_the_fingerprint() -> None:
    present = DependencyProjection(observations=(SATISFIED_NUMPY,), lock_state=LockState.PRESENT)
    newer = DependencyProjection(observations=(SATISFIED_NUMPY,), lock_state=LockState.NEWER_MINOR)
    assert dependency_fingerprint(present) != dependency_fingerprint(newer)


def test_the_producers_own_fields_cannot_move_the_fingerprint() -> None:
    """The test that fails the day somebody adds a volatile field to the projection.

    A lock regenerated by a newer pip, with not one name or version changed, has
    not changed which dependencies this environment has.
    """
    inventory = DependencyInventory(
        observations=(SATISFIED_NUMPY,),
        lock_state=LockState.PRESENT,
        lock_version="1.0",
        unknown_keys=(),
    )
    relocked = dataclasses.replace(inventory, lock_version="1.1", unknown_keys=("something-new",))
    assert dependency_fingerprint(inventory.projection()) == dependency_fingerprint(
        relocked.projection()
    )


# ---------------------------------------------------------------------------
# The inventory's own reporting
# ---------------------------------------------------------------------------


def test_unsatisfied_reports_divergence_and_excludes_an_answered_question() -> None:
    inventory = DependencyInventory(
        observations=(
            SATISFIED_NUMPY,
            DependencyObservation(name="gone", state=DependencyState.MISSING),
            DependencyObservation(name="drift", state=DependencyState.VERSION_MISMATCH),
            DependencyObservation(name="new", state=DependencyState.UNLOCKED),
            DependencyObservation(name="linux", state=DependencyState.NOT_APPLICABLE),
        ),
        lock_state=LockState.PRESENT,
    )
    assert [observation.name for observation in inventory.unsatisfied()] == [
        "drift",
        "gone",
        "new",
    ]


def test_the_record_carries_the_fingerprint_and_no_path_or_url() -> None:
    inventory = DependencyInventory(
        observations=(SATISFIED_NUMPY,),
        lock_state=LockState.PRESENT,
        lock_version="1.0",
    )
    record = inventory.as_record()
    assert record["fingerprint"] == dependency_fingerprint(inventory.projection())
    assert record["lock_state"] == "present"
    rendered = repr(record)
    assert "http" not in rendered
    assert ":\\" not in rendered
    assert "/" not in rendered
