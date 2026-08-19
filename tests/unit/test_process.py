"""What a bounded command is, and what a host was found to have.

Pure types, tested from literals. **Every validation rule is exercised twice** ---
once against something it must accept and once against something it must refuse
--- because a validator only ever seen to accept is a validator nobody has
established can refuse, and these particular refusals are the ones standing
between GLOBIN and a shell.
"""

import pytest

from globin.domain.process import (
    DEFAULT_TIMEOUT_MILLIS,
    MAX_ARGUMENTS,
    MAX_CAPTURED_BYTES,
    MAX_TIMEOUT_MILLIS,
    MIN_TIMEOUT_MILLIS,
    SHELL_METACHARACTERS,
    CommandRequest,
    CommandResult,
    HostCapability,
    Tool,
    ToolPresence,
    probe_commands,
    version_probe,
)
from globin.errors import ValidationError

# ---------------------------------------------------------------------------
# CommandRequest
# ---------------------------------------------------------------------------


def test_an_ordinary_command_is_accepted() -> None:
    request = CommandRequest(executable="py", arguments=("-0p",))
    assert request.display() == "py -0p"
    assert request.timeout_millis == DEFAULT_TIMEOUT_MILLIS


def test_a_path_with_a_space_is_accepted() -> None:
    r"""A space is deliberately absent from the metacharacter set.

    Refusing one would refuse Windows, where `C:\\Program Files\\...` is ordinary.
    """
    request = CommandRequest(executable=r"C:\Program Files\Python\python.exe")
    assert "Program Files" in request.display()


def test_an_empty_executable_is_refused() -> None:
    with pytest.raises(ValidationError, match="needs an executable"):
        CommandRequest(executable="")


@pytest.mark.parametrize("character", sorted(set(SHELL_METACHARACTERS) - set("\n\r\t\0")))
def test_every_declared_metacharacter_is_refused_in_an_argument(character: str) -> None:
    """Each one, written out, because a set with a gap fails open."""
    with pytest.raises(ValidationError, match="means something to a shell"):
        CommandRequest(executable="py", arguments=(f"a{character}b",))


def test_a_metacharacter_in_the_executable_is_refused_too() -> None:
    """Both fields, not only the arguments a caller thinks of as data."""
    with pytest.raises(ValidationError, match="means something to a shell"):
        CommandRequest(executable="py|cat")


def test_a_newline_in_an_argument_is_refused() -> None:
    """The one metacharacter a reader does not picture as one."""
    with pytest.raises(ValidationError, match="means something to a shell"):
        CommandRequest(executable="py", arguments=("first\nsecond",))


def test_too_many_arguments_are_refused() -> None:
    """A vector this long is a caller building a command rather than naming one."""
    with pytest.raises(ValidationError, match=f"at most {MAX_ARGUMENTS} arguments"):
        CommandRequest(executable="py", arguments=tuple(str(n) for n in range(MAX_ARGUMENTS + 1)))


def test_exactly_the_maximum_number_of_arguments_is_accepted() -> None:
    """Guard the boundary, so the bound is a bound rather than an off-by-one."""
    request = CommandRequest(executable="py", arguments=tuple(str(n) for n in range(MAX_ARGUMENTS)))
    assert len(request.arguments) == MAX_ARGUMENTS


@pytest.mark.parametrize("timeout", [0, -1, MIN_TIMEOUT_MILLIS - 1, MAX_TIMEOUT_MILLIS + 1])
def test_a_timeout_outside_the_declared_range_is_refused(timeout: int) -> None:
    with pytest.raises(ValidationError, match="must be between"):
        CommandRequest(executable="py", timeout_millis=timeout)


def test_a_boolean_timeout_is_refused() -> None:
    """`bool` is an `int`, so `True` would otherwise mean one millisecond."""
    with pytest.raises(ValidationError, match="not a boolean"):
        CommandRequest(executable="py", timeout_millis=True)


@pytest.mark.parametrize("timeout", [MIN_TIMEOUT_MILLIS, MAX_TIMEOUT_MILLIS])
def test_both_ends_of_the_declared_range_are_accepted(timeout: int) -> None:
    assert CommandRequest(executable="py", timeout_millis=timeout).timeout_millis == timeout


def test_a_request_records_what_it_is_without_rendering_a_shell_line() -> None:
    record = CommandRequest(executable="py", arguments=("-0p",)).as_record()
    assert record == {"executable": "py", "arguments": ["-0p"], "timeout_millis": 60_000}


def test_a_request_has_no_shell_field_at_all() -> None:
    """Not a field defaulting to False. None.

    A caller cannot ask for a shell because the type cannot describe one, which
    is a stronger guarantee than a default nobody is supposed to change.
    """
    assert "shell" not in CommandRequest.__dataclass_fields__


# ---------------------------------------------------------------------------
# CommandResult
# ---------------------------------------------------------------------------


def request() -> CommandRequest:
    """One ordinary request."""
    return CommandRequest(executable="py", arguments=("--version",))


def test_a_zero_exit_that_did_not_time_out_is_ok() -> None:
    assert CommandResult(request=request(), exit_code=0).ok


@pytest.mark.parametrize(
    ("code", "timed_out"),
    [(1, False), (0, True), (-1, True)],
)
def test_anything_else_is_not_ok(code: int, timed_out: bool) -> None:
    """A timed-out child with a zero code is not a success.

    The code is meaningless once the child was ended rather than finished, and
    reading it as a success is exactly the mistake the flag exists to prevent.
    """
    assert not CommandResult(request=request(), exit_code=code, timed_out=timed_out).ok


def test_a_result_records_how_much_came_back_and_not_what_it_said() -> None:
    """Redaction matches field names, so a child's stream cannot be made safe.

    `stdout` matches no sensitive fragment, so passing it through the redactor
    would look like a protection and be none.
    """
    record = CommandResult(request=request(), exit_code=0, stdout="abc", stderr="de").as_record()
    assert record["stdout_bytes"] == 3
    assert record["stderr_bytes"] == 2
    assert "stdout" not in record
    assert "stderr" not in record


def test_a_result_records_whether_it_was_cut() -> None:
    record = CommandResult(request=request(), exit_code=0, truncated=True).as_record()
    assert record["truncated"] is True


# ---------------------------------------------------------------------------
# ToolPresence
# ---------------------------------------------------------------------------


def test_a_measured_absent_tool_is_recorded_as_absent() -> None:
    presence = ToolPresence(tool=Tool.WINGET, present=False)
    assert presence.measured
    assert not presence.present


def test_an_unmeasured_probe_may_not_claim_presence() -> None:
    """A probe that could not run establishes nothing.

    Recording that as presence, or as a version, would make a broken PATH
    indistinguishable from a host that has the tool.
    """
    with pytest.raises(ValidationError, match="was not measured"):
        ToolPresence(tool=Tool.WINGET, present=True, measured=False)


def test_an_unmeasured_probe_may_not_claim_a_version() -> None:
    with pytest.raises(ValidationError, match="was not measured"):
        ToolPresence(tool=Tool.WINGET, version="1.0", measured=False)


def test_a_presence_records_all_four_fields() -> None:
    record = ToolPresence(tool=Tool.LEGACY_LAUNCHER, present=True, version="3.14").as_record()
    assert record == {"tool": "py", "present": True, "version": "3.14", "measured": True}


def test_presences_sort_stably() -> None:
    """Evidence is written in a stable order, so two runs compare."""
    entries = [ToolPresence(tool=tool) for tool in reversed(list(Tool))]
    assert [entry.tool for entry in sorted(entries)] == sorted(entry.tool for entry in entries)


# ---------------------------------------------------------------------------
# HostCapability
# ---------------------------------------------------------------------------


def inventory(**present: bool) -> HostCapability:
    """One entry per tool, with the named ones present."""
    return HostCapability(
        tools=tuple(ToolPresence(tool=tool, present=present.get(tool.name, False)) for tool in Tool)
    )


def test_an_empty_inventory_reports_every_tool_as_unmeasured() -> None:
    """Absent and not-asked-about must not be the same shape."""
    capability = HostCapability()
    assert not capability.presence(Tool.WINGET).measured
    assert not capability.has(Tool.WINGET)
    assert capability.launcher() is None


def test_a_repeated_tool_is_refused() -> None:
    with pytest.raises(ValidationError, match="records each tool once"):
        HostCapability(tools=(ToolPresence(tool=Tool.WINGET), ToolPresence(tool=Tool.WINGET)))


def test_an_inventory_missing_a_tool_is_refused() -> None:
    """Absence and silence must not be the same shape.

    An inventory that omitted what it did not find would make them one.
    """
    with pytest.raises(ValidationError, match="records every tool"):
        HostCapability(tools=(ToolPresence(tool=Tool.WINGET),))


def test_the_manager_is_preferred_over_the_legacy_launcher() -> None:
    """Both answer to `py`; only the manager answers to `pymanager`."""
    both = inventory(PYTHON_MANAGER=True, LEGACY_LAUNCHER=True)
    assert both.launcher() is Tool.PYTHON_MANAGER
    assert both.can_install_a_runtime()


def test_the_legacy_launcher_alone_cannot_install_a_runtime() -> None:
    """The legacy launcher cannot install a runtime.

    Measured on this host rather than remembered: `py install` is not a command
    it has.
    """
    legacy = inventory(LEGACY_LAUNCHER=True)
    assert legacy.launcher() is Tool.LEGACY_LAUNCHER
    assert not legacy.can_install_a_runtime()


def test_an_inventory_records_every_tool_in_a_stable_order() -> None:
    record = inventory(WINGET=True).as_record()
    tools = record["tools"]
    assert isinstance(tools, list)
    assert [entry["tool"] for entry in tools] == sorted(tool.value for tool in Tool)


# ---------------------------------------------------------------------------
# The probes
# ---------------------------------------------------------------------------


def test_there_is_one_probe_per_declared_tool() -> None:
    assert len(probe_commands()) == len(Tool)
    assert {request.executable for request in probe_commands()} == {tool.value for tool in Tool}


def test_every_probe_asks_only_for_a_version() -> None:
    """What makes a read-only run read-only: nothing here can change a host."""
    for probe in probe_commands():
        assert probe.arguments == ("--version",)


def test_the_probes_are_built_fresh_rather_than_shared() -> None:
    """Built fresh on each call, rather than shared.

    A function rather than a constant, because a layer package performs no call
    at import.
    """
    assert probe_commands() == probe_commands()
    assert probe_commands() is not probe_commands()


def test_a_version_probe_is_refused_for_a_shell_shaped_name() -> None:
    with pytest.raises(ValidationError, match="means something to a shell"):
        version_probe("py && rm")


def test_the_capture_ceiling_is_declared_rather_than_guessed() -> None:
    assert MAX_CAPTURED_BYTES == 65_536
