"""The measuring half: reading what is installed, and running the probes.

Split from `test_stack_plan.py` along the same seam the code is: everything here
either touches the environment or runs a real library, and everything there is a
judgement from literals.

**The probes that import `numpy` and `pandas` are guarded.** Neither is in
`pylock.dev.toml`, so the CI `quality` job — which installs the toolchain with
plain `pip` and never builds an environment — does not have them. The `runtime`
job does, and runs the gate itself. Guarding on
`running_from_the_project_environment()` rather than on a CI variable means a
developer who has not run the bootstrap gets the same skip and the same reason,
which is a true statement about their machine rather than a guess about where the
code is running.
"""

import pytest

from tests.support import running_from_the_project_environment
from tools.quality.stack.plan import Library, implemented_probes
from tools.quality.stack.probes import ProbeError, measure, registry, run, wheel_tag_of

needs_the_project_environment = pytest.mark.skipif(
    not running_from_the_project_environment(),
    reason="numpy and pandas arrive with the runtime lock, which only .venv installs",
)


def library(**overrides: object) -> Library:
    """A declared library, defaulting to the repository's real numpy entry."""
    fields: dict[str, object] = {
        "name": "numpy",
        "import_name": "numpy",
        "version": "2.5.2",
        "wheel_tag": "cp314-cp314-win_amd64",
        "role": "the numerical half",
        "probes": ("numpy.float64_is_binary64",),
    }
    fields.update(overrides)
    return Library(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Reading a wheel's own record of itself
# ---------------------------------------------------------------------------


def test_the_tag_is_read_out_of_a_wheel_record() -> None:
    text = (
        "Wheel-Version: 1.0\nGenerator: meson\nRoot-Is-Purelib: false\nTag: cp314-cp314-win_amd64"
    )
    assert wheel_tag_of(text) == "cp314-cp314-win_amd64"


def test_only_the_first_tag_is_taken() -> None:
    """A wheel may record several; the first is the one the installer matched."""
    text = "Tag: py3-none-any\nTag: py2-none-any"
    assert wheel_tag_of(text) == "py3-none-any"


def test_the_field_name_is_matched_without_regard_to_case() -> None:
    assert wheel_tag_of("tag: py3-none-any") == "py3-none-any"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        pytest.param(None, "no record at all", id="absent"),
        pytest.param("", "an empty record", id="empty"),
        pytest.param("Wheel-Version: 1.0\n", "no tag field", id="no tag line"),
        pytest.param("Tag:   \n", "a blank tag", id="blank tag"),
    ],
)
def test_a_record_with_no_usable_tag_reads_as_none(text: str | None, reason: str) -> None:
    """`None` rather than an empty string, so `provenance_problems` can say why.

    A distribution installed from a source tree legitimately has no `WHEEL` file,
    and that is a different finding from one whose tag disagrees.
    """
    assert wheel_tag_of(text) is None, reason


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_two_registries_agree() -> None:
    """`plan.implemented_probes` and `probes.registry` must name the same set.

    They are separate because one is a judgement registry and one is a callable
    registry, and a probe present in one but not the other is either a name the
    gate cannot run or a runnable probe nothing can describe.
    """
    assert set(registry()) == implemented_probes()


def test_an_unknown_probe_is_refused_rather_than_silently_passing() -> None:
    """A probe that returned no problems for an unknown name would read as a pass."""
    with pytest.raises(ProbeError, match="no probe is implemented"):
        run("numpy.does_not_exist")


# ---------------------------------------------------------------------------
# Reading the environment
# ---------------------------------------------------------------------------


def test_a_distribution_that_is_not_installed_is_a_finding_not_an_exception() -> None:
    """A broken host is an ordinary result here.

    Raising would replace a named check failure with a traceback, which is the
    outcome the whole gate exists to prevent.
    """
    facts = measure(library(name="globin-not-a-real-distribution", import_name="globin_absent"))
    assert facts.installed is None
    assert facts.wheel_tag is None
    assert facts.module_location is None


@needs_the_project_environment
def test_the_installed_library_is_measured() -> None:
    facts = measure(library())
    assert facts.installed == "2.5.2"
    assert facts.wheel_tag == "cp314-cp314-win_amd64"
    assert facts.module_location


@needs_the_project_environment
def test_a_distribution_present_under_another_import_name_is_still_located() -> None:
    """The distribution name and the module name are not always the same.

    `python-dateutil` installs `dateutil`, and the declaration carries both names
    for exactly this reason.
    """
    facts = measure(library(name="python-dateutil", import_name="dateutil"))
    assert facts.installed is not None
    assert facts.module_location


# ---------------------------------------------------------------------------
# The probes themselves, against the real libraries
# ---------------------------------------------------------------------------


@needs_the_project_environment
@pytest.mark.parametrize("identifier", sorted(implemented_probes()))
def test_every_probe_passes_on_this_host(identifier: str) -> None:
    """The measurement half of ADR-0058, run rather than assumed.

    This is the test that would go red if an upgrade changed a numeric behaviour
    GLOBIN depends on, and the identifier in the failure names which assumption.
    """
    assert run(identifier) == ()


@needs_the_project_environment
def test_the_overflow_probe_does_not_depend_on_an_earlier_overflow() -> None:
    """`simplefilter("always")` defeats once-per-location deduplication.

    Without it, a second run in one process sees no warning and the probe reports
    a silent overflow — a failure caused entirely by having run before.
    """
    assert run("numpy.integer_overflow_wraps_observably") == ()
    assert run("numpy.integer_overflow_wraps_observably") == ()


@needs_the_project_environment
def test_the_probes_are_deterministic_across_two_runs() -> None:
    """The manifest is rendered twice and compared, so a probe must not vary.

    The timestamp probe is the one at risk: a clock reading would still pass and
    would make two renderings of one run disagree.
    """
    first = {identifier: run(identifier) for identifier in sorted(implemented_probes())}
    second = {identifier: run(identifier) for identifier in sorted(implemented_probes())}
    assert first == second
