"""Judging a host against the runtime baseline, from literals.

Every function in :mod:`tools.quality.runtime.plan` takes text or values and
returns findings, so the whole of the reasoning is testable offline with no
repository, no network and no temporary tree.

**This is the only place several of these rules can be tested at all.** A 32-bit
interpreter, a free-threaded build, a PyPy, a prerelease and a Windows 8 host are
each a rule the contract carries and none of them exists on the machine running
this suite. Observing the real host could only ever assert what the real host
happens to be, which is why every observation here arrives as an argument.

**Each checker is exercised twice: once against something correct, and once
against something deliberately broken.** A checker only ever seen to pass is a
checker nobody has established can fail, and ``docs/engineering/QUALITY_GATES.md``
is explicit that a gate that cannot fail is decoration.
"""

from pathlib import Path

import pytest

from tools.quality.runtime import plan
from tools.quality.runtime.plan import (
    Environment,
    EnvironmentPolicy,
    Host,
    HostPolicy,
    Interpreter,
    InterpreterPolicy,
    Launcher,
    RuntimeBaselineError,
    Version,
)

CONTRACT_TOML = """\
schema = 1

[interpreter]
implementation = "CPython"
minor_line = "3.14"
minimum_patch = "3.14.5"
architecture = "AMD64"
pointer_bits = 64
free_threaded = false
allow_prerelease = false

[host]
system = "Windows"
minimum_release = "10"

[environment]
directory = ".venv"
system_site_packages = false
"""


def interpreter_policy(**overrides: object) -> InterpreterPolicy:
    """The contract's interpreter policy, with any field replaced."""
    defaults: dict[str, object] = {
        "implementation": "CPython",
        "minor_line": "3.14",
        "minimum_patch": Version(3, 14, 5),
        "architecture": "AMD64",
        "pointer_bits": 64,
        "free_threaded": False,
        "allow_prerelease": False,
    }
    return InterpreterPolicy(**{**defaults, **overrides})  # type: ignore[arg-type]


def observed_interpreter(**overrides: object) -> Interpreter:
    """A compliant interpreter, with any field replaced."""
    defaults: dict[str, object] = {
        "implementation": "cpython",
        "version": Version(3, 14, 5),
        "release_level": "final",
        "free_threaded": False,
        "pointer_bits": 64,
        "machine": "AMD64",
    }
    return Interpreter(**{**defaults, **overrides})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def test_a_three_component_version_is_read_and_rendered_back() -> None:
    version = plan.parse_version("3.14.5")
    assert (version.major, version.minor, version.micro) == (3, 14, 5)
    assert version.text == "3.14.5"
    assert version.line == "3.14"


@pytest.mark.parametrize("text", ["3.14", "3", "3.14.5.1", "3.14.x", "", "v3.14.5"])
def test_a_version_that_is_not_three_integers_is_refused(text: str) -> None:
    """A two-component version is refused rather than completed with a zero.

    ``3.14`` is a series and ``3.14.0`` is a release. Quietly turning the first
    into the second would make the floor comparison assert something nobody wrote.
    """
    with pytest.raises(RuntimeBaselineError):
        plan.parse_version(text)


def test_versions_order_by_major_then_minor_then_patch() -> None:
    assert Version(3, 14, 5) < Version(3, 14, 7)
    assert Version(3, 14, 20) > Version(3, 14, 9), "patch must order numerically, not as text"
    assert Version(3, 9, 0) < Version(3, 14, 0), "minor must order numerically, not as text"
    assert Version(2, 99, 99) < Version(3, 0, 0)


@pytest.mark.parametrize("text", ["3.14.5", "3", "3.x", ""])
def test_a_minor_line_that_is_not_two_integers_is_refused(text: str) -> None:
    with pytest.raises(RuntimeBaselineError):
        plan.parse_minor_line(text)


def test_a_minor_line_is_read() -> None:
    assert plan.parse_minor_line("3.14") == (3, 14)


# ---------------------------------------------------------------------------
# The interpreter
# ---------------------------------------------------------------------------


def test_a_compliant_interpreter_has_no_problems() -> None:
    assert plan.interpreter_problems(observed_interpreter(), interpreter_policy()) == ()


def test_a_later_patch_in_the_same_line_is_accepted() -> None:
    """The floor is a floor. A security patch must not fail the build.

    This is the case an exact pin would get wrong, and it is the reason the
    contract names ``minimum_patch`` rather than a single version.
    """
    observed = observed_interpreter(version=Version(3, 14, 9))
    assert plan.interpreter_problems(observed, interpreter_policy()) == ()


def test_a_patch_below_the_floor_is_refused() -> None:
    observed = observed_interpreter(version=Version(3, 14, 4))
    problems = plan.interpreter_problems(observed, interpreter_policy())
    assert len(problems) == 1
    assert "older than the verified baseline" in problems[0]


def test_a_different_minor_line_is_refused_even_when_newer() -> None:
    """3.15 is not 3.14, and being newer does not make it verified."""
    observed = observed_interpreter(version=Version(3, 15, 0))
    problems = plan.interpreter_problems(observed, interpreter_policy())
    assert len(problems) == 1
    assert "3.15 line" in problems[0]


def test_a_prerelease_is_refused_by_default_and_accepted_when_permitted() -> None:
    observed = observed_interpreter(release_level="candidate")
    assert any(
        "prerelease" in problem
        for problem in plan.interpreter_problems(observed, interpreter_policy())
    )
    assert plan.interpreter_problems(observed, interpreter_policy(allow_prerelease=True)) == ()


def test_a_free_threaded_build_is_refused_by_default_and_accepted_when_permitted() -> None:
    observed = observed_interpreter(free_threaded=True)
    assert any(
        "free-threaded" in problem
        for problem in plan.interpreter_problems(observed, interpreter_policy())
    )
    assert plan.interpreter_problems(observed, interpreter_policy(free_threaded=True)) == ()


def test_a_thirty_two_bit_interpreter_is_refused() -> None:
    observed = observed_interpreter(pointer_bits=32)
    problems = plan.interpreter_problems(observed, interpreter_policy())
    assert len(problems) == 1
    assert "32-bit" in problems[0]


def test_another_implementation_is_refused() -> None:
    observed = observed_interpreter(implementation="pypy")
    problems = plan.interpreter_problems(observed, interpreter_policy())
    assert len(problems) == 1
    assert "pypy" in problems[0]


def test_implementation_comparison_ignores_case() -> None:
    """``sys.implementation.name`` is lower case; the contract is written as CPython."""
    assert (
        plan.interpreter_problems(
            observed_interpreter(implementation="CPython"), interpreter_policy()
        )
        == ()
    )


def test_another_architecture_is_refused() -> None:
    observed = observed_interpreter(machine="ARM64")
    problems = plan.interpreter_problems(observed, interpreter_policy())
    assert len(problems) == 1
    assert "ARM64" in problems[0]


def test_every_problem_is_reported_rather_than_only_the_first() -> None:
    """A wrong interpreter is usually wrong in more than one way at once.

    Stopping at the first would send somebody round the diagnose-and-retry loop
    once per fault.
    """
    observed = observed_interpreter(
        implementation="pypy", version=Version(3, 12, 0), pointer_bits=32, machine="x86"
    )
    assert len(plan.interpreter_problems(observed, interpreter_policy())) == 4


# ---------------------------------------------------------------------------
# The host
# ---------------------------------------------------------------------------


def test_a_supported_windows_has_no_problems() -> None:
    observed = Host(system="Windows", release="11", kernel="10.0.26200")
    assert plan.host_problems(observed, HostPolicy("Windows", "10")) == ()


def test_windows_ten_is_supported() -> None:
    observed = Host(system="Windows", release="10", kernel="10.0.19045")
    assert plan.host_problems(observed, HostPolicy("Windows", "10")) == ()


def test_a_kernel_older_than_windows_ten_is_refused() -> None:
    """Windows 8.1 reports kernel 6.3."""
    observed = Host(system="Windows", release="8.1", kernel="6.3.9600")
    problems = plan.host_problems(observed, HostPolicy("Windows", "10"))
    assert len(problems) == 1
    assert "older than Windows 10" in problems[0]


def test_a_server_release_orders_by_kernel_rather_than_by_its_year() -> None:
    """Windows Server reports a year, so the release string does not order.

    ``"2019" > "11"`` as text and as a number while being older than Windows 11.
    Comparing kernel versions is what makes this checkable at all.
    """
    observed = Host(system="Windows", release="2019", kernel="10.0.17763")
    assert plan.host_problems(observed, HostPolicy("Windows", "10")) == ()


def test_another_operating_system_is_refused_and_stops_further_checks() -> None:
    """A Linux host has no Windows kernel version.

    That is why reporting one as missing too would be two findings about one fact.
    """
    observed = Host(system="Linux", release="6.8.0", kernel="")
    problems = plan.host_problems(observed, HostPolicy("Windows", "10"))
    assert len(problems) == 1
    assert "Linux" in problems[0]


def test_an_unreadable_kernel_version_is_reported_rather_than_assumed() -> None:
    observed = Host(system="Windows", release="11", kernel="")
    problems = plan.host_problems(observed, HostPolicy("Windows", "10"))
    assert len(problems) == 1
    assert "unmeasured" in problems[0]


@pytest.mark.parametrize(
    ("kernel", "expected"), [("10.0.26200", 10), ("6.3.9600", 6), ("", None), ("x.y", None)]
)
def test_the_kernel_major_is_read_or_reported_absent(kernel: str, expected: int | None) -> None:
    assert plan.kernel_major(kernel) == expected


# ---------------------------------------------------------------------------
# pyvenv.cfg
# ---------------------------------------------------------------------------


def test_pyvenv_cfg_is_parsed_and_windows_paths_survive_it() -> None:
    """The values are Windows paths.

    That is why splitting on every ``=`` would truncate ``command``, which holds a whole command
    line.
    """
    parsed = plan.parse_pyvenv_cfg(
        "home = C:\\Python314\n"
        "include-system-site-packages = false\n"
        "version = 3.14.5\n"
        "executable = C:\\Python314\\python.exe\n"
        "command = C:\\Python314\\python.exe -m venv C:\\repo\\.venv\n"
    )
    assert parsed["home"] == "C:\\Python314"
    assert parsed["version"] == "3.14.5"
    assert parsed["command"].endswith("C:\\repo\\.venv")


def test_pyvenv_cfg_ignores_lines_without_a_separator() -> None:
    assert plan.parse_pyvenv_cfg("nonsense\n\nversion = 3.14.5\n") == {"version": "3.14.5"}


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


def environment(**overrides: object) -> Environment:
    """A compliant environment, with any field replaced."""
    defaults: dict[str, object] = {
        "present": True,
        "location": Path("C:/repo/.venv"),
        "recorded_location": Path("C:/repo/.venv"),
        "config": {"include-system-site-packages": "false", "version": "3.14.5"},
        "base_present": True,
        "interpreter_present": True,
    }
    return Environment(**{**defaults, **overrides})  # type: ignore[arg-type]


ENVIRONMENT_POLICY = EnvironmentPolicy(directory=".venv", system_site_packages=False)


def test_a_compliant_environment_has_no_problems() -> None:
    assert plan.environment_problems(environment(), ENVIRONMENT_POLICY, interpreter_policy()) == ()


def test_an_absent_environment_is_not_a_problem_for_this_function() -> None:
    """Whether one is required is the caller's question.

    ``bootstrap`` exists to act on the absence.
    """
    assert (
        plan.environment_problems(
            Environment(present=False), ENVIRONMENT_POLICY, interpreter_policy()
        )
        == ()
    )


def test_a_system_site_packages_environment_is_refused() -> None:
    observed = environment(config={"include-system-site-packages": "true", "version": "3.14.5"})
    problems = plan.environment_problems(observed, ENVIRONMENT_POLICY, interpreter_policy())
    assert any("--system-site-packages" in problem for problem in problems)


def test_a_missing_site_packages_key_is_a_problem_rather_than_a_default() -> None:
    """:mod:`venv` writes the key unconditionally.

    That is why its absence means the file was written by something else or edited by hand.
    """
    observed = environment(config={"version": "3.14.5"})
    problems = plan.environment_problems(observed, ENVIRONMENT_POLICY, interpreter_policy())
    assert any("does not record include-system-site-packages" in problem for problem in problems)


def test_an_environment_built_from_the_wrong_line_is_refused() -> None:
    observed = environment(config={"include-system-site-packages": "false", "version": "3.12.8"})
    problems = plan.environment_problems(observed, ENVIRONMENT_POLICY, interpreter_policy())
    assert any("created from Python 3.12.8" in problem for problem in problems)


def test_an_environment_built_below_the_patch_floor_is_refused() -> None:
    observed = environment(config={"include-system-site-packages": "false", "version": "3.14.1"})
    problems = plan.environment_problems(observed, ENVIRONMENT_POLICY, interpreter_policy())
    assert any("older than the verified baseline" in problem for problem in problems)


def test_an_unreadable_recorded_version_is_reported() -> None:
    observed = environment(
        config={"include-system-site-packages": "false", "version": "not-a-version"}
    )
    problems = plan.environment_problems(observed, ENVIRONMENT_POLICY, interpreter_policy())
    assert any("unreadable interpreter version" in problem for problem in problems)


def test_a_missing_recorded_version_is_a_problem_rather_than_a_default() -> None:
    """:mod:`venv` writes it unconditionally.

    That is why its absence means the file was written by something else.
    """
    observed = environment(config={"include-system-site-packages": "false"})
    problems = plan.environment_problems(observed, ENVIRONMENT_POLICY, interpreter_policy())
    assert any("does not record the interpreter version" in problem for problem in problems)


def test_an_environment_with_no_recorded_location_is_not_called_moved() -> None:
    """An environment predating ``activate.bat``.

    One whose script could not be read, is unknown rather than moved.

    Reporting it as moved would send somebody to recreate a working environment.
    """
    assert (
        plan.environment_problems(
            environment(recorded_location=None), ENVIRONMENT_POLICY, interpreter_policy()
        )
        == ()
    )


def test_an_environment_whose_base_interpreter_is_gone_is_stale() -> None:
    problems = plan.environment_problems(
        environment(base_present=False), ENVIRONMENT_POLICY, interpreter_policy()
    )
    assert any("stale" in problem for problem in problems)


def test_a_moved_or_copied_environment_is_detected() -> None:
    """Venv states plainly that environments are not movable.

    A moved one still runs, and only the console scripts — which hold absolute paths —
    misbehave.
    """
    observed = environment(recorded_location=Path("C:/somewhere-else/.venv"))
    problems = plan.environment_problems(observed, ENVIRONMENT_POLICY, interpreter_policy())
    assert any("moved or copied" in problem for problem in problems)


def test_an_environment_with_no_interpreter_is_reported_as_partial() -> None:
    problems = plan.environment_problems(
        environment(interpreter_present=False), ENVIRONMENT_POLICY, interpreter_policy()
    )
    assert any("partial or interrupted" in problem for problem in problems)


def test_an_environment_without_a_config_stops_after_saying_so() -> None:
    """Everything else this function checks is read out of that file."""
    problems = plan.environment_problems(
        environment(config={}), ENVIRONMENT_POLICY, interpreter_policy()
    )
    assert any("no readable pyvenv.cfg" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Deletion safety
# ---------------------------------------------------------------------------


ROOT = Path("C:/repo")


def test_the_declared_environment_directory_may_be_deleted() -> None:
    assert (
        plan.deletion_problems(
            target=ROOT / ".venv", root=ROOT, directory=".venv", is_reparse_point=False
        )
        == ()
    )


def test_a_path_outside_the_repository_is_never_a_deletion_target() -> None:
    """The check this whole function exists for."""
    problems = plan.deletion_problems(
        target=Path("C:/Windows/System32"), root=ROOT, directory=".venv", is_reparse_point=False
    )
    assert any("outside the repository" in problem for problem in problems)


def test_a_sibling_of_the_environment_is_not_a_deletion_target() -> None:
    """Inside the repository is not sufficient. `src` is inside it too."""
    problems = plan.deletion_problems(
        target=ROOT / "src", root=ROOT, directory=".venv", is_reparse_point=False
    )
    assert any("not the declared environment directory" in problem for problem in problems)


def test_a_nested_environment_is_not_a_deletion_target() -> None:
    problems = plan.deletion_problems(
        target=ROOT / "sub" / ".venv", root=ROOT, directory=".venv", is_reparse_point=False
    )
    assert any("not the declared environment directory" in problem for problem in problems)


def test_a_link_is_never_deleted_through() -> None:
    """Deleting through a junction can remove what it points at, and it may point anywhere."""
    problems = plan.deletion_problems(
        target=ROOT / ".venv", root=ROOT, directory=".venv", is_reparse_point=True
    )
    assert any("symbolic link or junction" in problem for problem in problems)


def test_the_repository_root_itself_is_never_a_deletion_target() -> None:
    problems = plan.deletion_problems(
        target=ROOT, root=ROOT, directory=".venv", is_reparse_point=False
    )
    assert problems, "deleting the repository root must never be permitted"


@pytest.mark.parametrize("directory", ["", "..", "a/b", "a\\b", "."])
def test_a_directory_name_that_is_not_plain_is_refused(directory: str) -> None:
    problems = plan.deletion_problems(
        target=ROOT / ".venv", root=ROOT, directory=directory, is_reparse_point=False
    )
    assert any("not a plain" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Recording a path
# ---------------------------------------------------------------------------


def test_a_path_inside_the_repository_is_recorded_relative_to_it() -> None:
    recorded = plan.recorded_path(ROOT / ".venv" / "Scripts" / "python.exe", root=ROOT)
    assert recorded == {"location": "repository", "path": ".venv/Scripts/python.exe"}


def test_a_path_outside_the_repository_is_recorded_only_as_a_fingerprint() -> None:
    """The whole privacy contract.

    On the development host these paths carry the account holder's full name.
    """
    recorded = plan.recorded_path(Path("C:/Users/Someone/AppData/Roaming"), root=ROOT)
    assert recorded["location"] == "outside"
    assert "path" not in recorded
    assert "Someone" not in str(recorded)
    assert "AppData" not in str(recorded)


def test_an_absent_path_is_recorded_as_absent_rather_than_as_an_empty_string() -> None:
    assert plan.recorded_path(None, root=ROOT) == {"location": "absent"}


def test_the_same_outside_path_fingerprints_the_same_way_twice() -> None:
    """Two runs on one machine must agree.

    That is why a reader can tell "the same interpreter as last time" from "a different one".
    """
    first = plan.recorded_path(Path("C:/Python314"), root=ROOT)
    second = plan.recorded_path(Path("C:/Python314"), root=ROOT)
    assert first == second


def test_two_different_outside_paths_fingerprint_differently() -> None:
    first = plan.recorded_path(Path("C:/Python314"), root=ROOT)
    second = plan.recorded_path(Path("C:/Python312"), root=ROOT)
    assert first != second


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


LEGACY_LISTING = """\
 -V:3.14 *        C:\\Python314\\python.exe
 -V:3.12          C:\\Users\\Someone\\AppData\\Local\\Programs\\Python\\Python312\\python.exe
"""


def test_the_legacy_launcher_listing_is_parsed_into_tags() -> None:
    runtimes = plan.parse_legacy_runtimes(LEGACY_LISTING)
    assert runtimes == (
        {"tag": "3.14", "default": "true"},
        {"tag": "3.12", "default": "false"},
    )


def test_the_legacy_listing_parser_never_returns_a_path() -> None:
    """Returning them would make it easy to write one into a manifest by accident."""
    runtimes = plan.parse_legacy_runtimes(LEGACY_LISTING)
    assert not any("Someone" in str(entry) for entry in runtimes)
    assert not any("path" in entry for entry in runtimes)


def test_the_legacy_listing_parser_finds_its_own_failing_case() -> None:
    """A parser that silently matches nothing passes everything."""
    assert plan.parse_legacy_runtimes("WARNING: the 'list' command is unavailable\n") == ()


def test_the_recorded_environment_location_is_read_from_activate() -> None:
    assert (
        plan.parse_recorded_location('@echo off\nset "VIRTUAL_ENV=C:\\repo\\.venv"\n')
        == "C:\\repo\\.venv"
    )


def test_the_recorded_location_parser_finds_its_own_failing_case() -> None:
    assert plan.parse_recorded_location("@echo off\n") is None


@pytest.mark.parametrize(
    ("manager", "legacy", "interpreter", "expected"),
    [
        (True, True, True, Launcher.MANAGER),
        (False, True, True, Launcher.LEGACY),
        (False, False, True, Launcher.INTERPRETER_ONLY),
        (False, False, False, Launcher.ABSENT),
    ],
)
def test_the_launcher_is_classified_most_capable_first(
    manager: bool, legacy: bool, interpreter: bool, expected: Launcher
) -> None:
    assert (
        plan.classify_launcher(manager=manager, legacy=legacy, interpreter=interpreter) == expected
    )


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


def test_the_contract_is_read() -> None:
    contract = plan.parse_declaration(CONTRACT_TOML)
    assert contract.interpreter.minimum_patch == Version(3, 14, 5)
    assert contract.interpreter.minor_line == "3.14"
    assert contract.host.system == "Windows"
    assert contract.environment.directory == ".venv"
    assert contract.environment.system_site_packages is False


def test_a_declaration_that_is_not_toml_is_refused() -> None:
    with pytest.raises(RuntimeBaselineError, match="not valid TOML"):
        plan.parse_declaration("schema = = 1")


def test_an_unsupported_schema_is_refused_rather_than_read_anyway() -> None:
    with pytest.raises(RuntimeBaselineError, match="schema"):
        plan.parse_declaration(CONTRACT_TOML.replace("schema = 1", "schema = 2"))


@pytest.mark.parametrize("table", ["interpreter", "host", "environment"])
def test_a_missing_table_is_refused(table: str) -> None:
    with pytest.raises(RuntimeBaselineError, match=table):
        plan.parse_declaration(CONTRACT_TOML.replace(f"[{table}]", "[unused]"))


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('implementation = "CPython"', "implementation = 3"),
        ('architecture = "AMD64"', "architecture = true"),
        ('system = "Windows"', "system = 10"),
    ],
)
def test_a_string_setting_of_the_wrong_type_is_refused(original: str, replacement: str) -> None:
    with pytest.raises(RuntimeBaselineError, match="must be a string"):
        plan.parse_declaration(CONTRACT_TOML.replace(original, replacement))


def test_a_setting_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(RuntimeBaselineError, match="pointer_bits"):
        plan.parse_declaration(CONTRACT_TOML.replace("pointer_bits = 64", 'pointer_bits = "64"'))


def test_a_boolean_is_not_accepted_where_an_integer_is_required() -> None:
    """TOML spells them differently.

    Python's ``bool`` is an ``int`` and would otherwise slip through.
    """
    with pytest.raises(RuntimeBaselineError, match="pointer_bits"):
        plan.parse_declaration(CONTRACT_TOML.replace("pointer_bits = 64", "pointer_bits = true"))


def test_a_flag_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(RuntimeBaselineError, match="free_threaded"):
        plan.parse_declaration(
            CONTRACT_TOML.replace("free_threaded = false", 'free_threaded = "no"')
        )


@pytest.mark.parametrize("directory", ['""', '"../escape"', '"a/b"', '"."'])
def test_an_environment_directory_that_is_not_a_plain_name_is_refused(directory: str) -> None:
    """Refused at the point it is read, so that no later code has to defend against it."""
    with pytest.raises(RuntimeBaselineError, match="plain directory name"):
        plan.parse_declaration(
            CONTRACT_TOML.replace('directory = ".venv"', f"directory = {directory}")
        )


def test_a_malformed_minimum_patch_is_refused() -> None:
    with pytest.raises(RuntimeBaselineError):
        plan.parse_declaration(
            CONTRACT_TOML.replace('minimum_patch = "3.14.5"', 'minimum_patch = "3.14"')
        )


def test_a_malformed_minor_line_is_refused() -> None:
    with pytest.raises(RuntimeBaselineError):
        plan.parse_declaration(
            CONTRACT_TOML.replace('minor_line = "3.14"', 'minor_line = "3.14.5"')
        )


# ---------------------------------------------------------------------------
# The toolchain register
# ---------------------------------------------------------------------------


def test_a_pinned_toolchain_is_usable() -> None:
    assert plan.toolchain_problems([("ruff", "0.15.14"), ("mypy", "2.1.0")]) == ()


def test_an_empty_register_is_refused_rather_than_installing_nothing() -> None:
    problems = plan.toolchain_problems([])
    assert any("no pinned toolchain" in problem for problem in problems)


def test_one_package_pinned_twice_at_two_versions_is_reported() -> None:
    problems = plan.toolchain_problems([("ruff", "0.15.14"), ("ruff", "0.16.0")])
    assert any("both" in problem for problem in problems)


def test_one_package_pinned_twice_at_one_version_is_not_a_problem() -> None:
    """Several CI jobs install the same tool; agreeing is not a disagreement."""
    assert plan.toolchain_problems([("ruff", "0.15.14"), ("ruff", "0.15.14")]) == ()
