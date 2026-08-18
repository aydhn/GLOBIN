"""What a bounded child process is, and what a host was found to have.

**A command is a value type that cannot express a shell.** :class:`CommandRequest`
holds an executable and an argument vector, and there is no ``shell`` field --- not
a field defaulting to ``False``, but no field at all, so no call site can set one
and no future edit can add one without changing this class. Shell metacharacters
are refused in construction rather than escaped, because escaping is a thing
somebody has to get right every time and refusing is a thing that is right once.
This is the shape ``LoopbackAddress`` uses in
:mod:`globin.domain.diagnostics_http`, and for the same reason: the dangerous
value is made unrepresentable rather than policed.

**Every command is bounded twice.** A timeout, so a wedged child cannot hold the
process for ever, and a capture ceiling, so a child that prints without stopping
cannot exhaust memory. Both are validated here, so a caller cannot construct an
unbounded request and discover the problem at the point it matters least.

**A capability that could not be measured is not an absent one.**
:class:`ToolPresence` carries ``measured`` alongside ``present``, because a probe
that failed to run and a tool that is not installed are different facts, and
collapsing them makes a host with a broken PATH indistinguishable from a host
that simply lacks a launcher.

This module performs no I/O and knows nothing about how a process is started;
:mod:`globin.adapters.provisioning` is the one place in the package that does.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.errors import ValidationError

MAX_TIMEOUT_MILLIS: Final[int] = 900_000
"""Fifteen minutes, which is longer than any command this phase runs.

A ceiling rather than a guess at the right value: the point is that *some* bound
exists and is declared, so a caller cannot pass a number that amounts to none.
"""

MIN_TIMEOUT_MILLIS: Final[int] = 1_000
"""One second. Below this a timeout is a race rather than a bound."""

DEFAULT_TIMEOUT_MILLIS: Final[int] = 60_000
"""What a command gets when its caller has no opinion."""

MAX_CAPTURED_BYTES: Final[int] = 65_536
"""How much of a child's output is kept.

Sixty-four kilobytes is far more than any diagnostic needs and far less than a
runaway child can produce. Output beyond it is dropped and the result says so,
because silently truncating and reporting the whole is how a reader concludes a
build succeeded from the last line of a log that was cut.
"""

MAX_ARGUMENTS: Final[int] = 64
"""How many arguments a command may carry.

Windows has a command-line length limit that a long argument vector can reach,
and a vector this long is a caller building a command rather than naming one.
"""

SHELL_METACHARACTERS: Final[str] = "&|;<>$`\n\r\t\0"
"""Characters that mean something to a shell, and nothing to an argument vector.

Refused in construction. Nothing here ever reaches a shell --- the adapter passes
an argument vector and never a string --- so a metacharacter arriving in one of
these fields is evidence that a caller *believes* it is composing a shell command,
and that belief is the defect worth catching. Refusing costs a caller nothing that
this phase legitimately needs, and the alternative is a rule somebody has to
remember at every call site.

A space is deliberately absent: a path with a space in it is ordinary on Windows,
and refusing one would refuse the platform.
"""


class Tool(StrEnum):
    """A host tool this phase can detect, and the name it is detected under.

    Closed, and short on purpose. Each member is something a provisioning
    decision might legitimately turn on; a member nobody branches on is
    vocabulary rather than a capability.
    """

    WINGET = "winget"
    """Windows' package manager. **Detected and never invoked** --- see
    ``docs/engineering/PROVISIONING.md``. Its presence is published so the phase
    that has a use for it inherits a measurement rather than a guess."""

    PYTHON_MANAGER = "pymanager"
    """The Python install manager, which is the *only* command that distinguishes
    it from the legacy launcher: both answer to ``py``, and this one does not."""

    LEGACY_LAUNCHER = "py"
    """The legacy ``py.exe`` launcher. Present on most Windows hosts, including
    this one, and unable to install a runtime."""


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """One child process, bounded and shell-free by construction.

    Args:
        executable: The program to run. A name to be resolved on ``PATH``, or a
            path to one.
        arguments: Everything after it, as a vector. Never a string, and never
            joined into one.
        timeout_millis: How long the child may run.

    Raises:
        ValidationError: If the executable is empty, any field carries a shell
            metacharacter, there are too many arguments, or the timeout is
            outside :data:`MIN_TIMEOUT_MILLIS` to :data:`MAX_TIMEOUT_MILLIS`.

    **There is no ``shell`` field, and that is the type's whole point.** A caller
    cannot ask for a shell because this class cannot describe one.
    """

    executable: str
    arguments: tuple[str, ...] = ()
    timeout_millis: int = DEFAULT_TIMEOUT_MILLIS

    def __post_init__(self) -> None:
        """Refuse anything this type is not willing to describe."""
        if not self.executable:
            msg = "a command needs an executable, and this one is empty"
            raise ValidationError(msg)
        if len(self.arguments) > MAX_ARGUMENTS:
            msg = (
                f"a command may carry at most {MAX_ARGUMENTS} arguments, "
                f"and this one carries {len(self.arguments)}"
            )
            raise ValidationError(msg)
        for word in (self.executable, *self.arguments):
            offending = sorted({char for char in word if char in SHELL_METACHARACTERS})
            if offending:
                msg = (
                    f"{word!r} carries {offending!r}, which means something to a shell. "
                    f"Nothing here reaches one, so this is a caller composing a shell "
                    f"command where an argument vector is wanted"
                )
                raise ValidationError(msg)
        # `bool` is an `int`, so a caller passing `True` would otherwise be
        # accepted and produce a one-millisecond timeout.
        if isinstance(self.timeout_millis, bool):
            msg = "a timeout is a number of milliseconds, not a boolean"
            raise ValidationError(msg)
        if not MIN_TIMEOUT_MILLIS <= self.timeout_millis <= MAX_TIMEOUT_MILLIS:
            msg = (
                f"a timeout must be between {MIN_TIMEOUT_MILLIS} and "
                f"{MAX_TIMEOUT_MILLIS} milliseconds, and this one is {self.timeout_millis}"
            )
            raise ValidationError(msg)

    def display(self) -> str:
        """This command as one line, for a human reading a plan.

        Returns:
            The executable and its arguments, space-separated.

        Rendered for reading and never for running: nothing takes this string and
        executes it, because the adapter is handed the vector. Producing it is
        safe precisely because :data:`SHELL_METACHARACTERS` cannot appear in it.
        """
        return " ".join((self.executable, *self.arguments))

    def as_record(self) -> dict[str, object]:
        """This command as the mapping evidence carries.

        Returns:
            The executable, the arguments and the timeout.
        """
        return {
            "executable": self.executable,
            "arguments": list(self.arguments),
            "timeout_millis": self.timeout_millis,
        }


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What a child process did.

    Args:
        request: What was asked for.
        exit_code: What it returned. Meaningless when ``timed_out``.
        stdout: What it printed, truncated to the capture ceiling.
        stderr: What it printed to standard error, likewise.
        timed_out: Whether it was ended rather than finished.
        truncated: Whether either stream was cut at the ceiling.

    A timeout is a **result, not an exception**. A caller deciding what to do
    about a provisioning action needs the same shape of answer whether the child
    failed or hung, and raising for one of the two would make every call site
    carry a try block that means "treat it the same way".
    """

    request: CommandRequest
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        """Whether the child finished, and finished successfully.

        Returns:
            ``True`` only for a child that ran to completion and returned zero.
        """
        return not self.timed_out and self.exit_code == 0

    def as_record(self) -> dict[str, object]:
        """This result as the mapping evidence carries.

        Returns:
            The request, the code, how much each stream carried, and the two
            flags. **Neither stream's text is included.**

        **A child's output is never published, and redaction is why.**
        :func:`globin.domain.observability.redact` matches field *names*, and a
        child's standard output is not a name GLOBIN chose --- it is text GLOBIN
        did not write, arriving under a key (``stdout``) that matches no
        sensitive fragment. Passing it through the redactor would look like a
        protection and be none: a tool echoing an environment variable would have
        published a credential verbatim.

        GLOBIN cannot know what a child printed, so it records what it does know
        --- which command, which code, how much came back --- and the text goes to
        the operator's terminal, which is where it is useful and is not a document
        anybody forwards.
        """
        return {
            "request": self.request.as_record(),
            "exit_code": self.exit_code,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "timed_out": self.timed_out,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True, order=True)
class ToolPresence:
    """Whether one tool is on this host.

    Args:
        tool: Which tool.
        present: Whether it was found.
        version: What it reported, when it was asked and answered.
        measured: Whether the probe ran at all.

    Raises:
        ValidationError: If an unmeasured presence claims to be present, or
            carries a version.

    **``measured=False`` is not ``present=False``.** A probe that could not run
    establishes nothing, and recording that as absence would make a host with a
    broken PATH indistinguishable from one that lacks the tool. This is the same
    separation ``Availability`` makes in :mod:`globin.domain.health`, and the
    same one ADR-0045 makes for a platform capability.
    """

    tool: Tool
    present: bool = False
    version: str = ""
    measured: bool = True

    def __post_init__(self) -> None:
        """Refuse a claim an unmeasured probe cannot support."""
        if not self.measured and (self.present or self.version):
            msg = (
                f"{self.tool.value} was not measured, so it can claim neither presence "
                f"nor a version"
            )
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This presence as the mapping evidence carries.

        Returns:
            The tool, whether it is present, its version and whether it was
            measured at all.
        """
        return {
            "tool": self.tool.value,
            "present": self.present,
            "version": self.version,
            "measured": self.measured,
        }


@dataclass(frozen=True, slots=True)
class HostCapability:
    """Which of the declared tools this host has.

    Args:
        tools: One entry per member of :class:`Tool`, in member order.

    Raises:
        ValidationError: If a tool is recorded twice, or one is missing.

    Every tool is always recorded, present or not. A capability inventory that
    omitted what it did not find would make "absent" and "not asked about"
    the same shape, which is the distinction :class:`ToolPresence` exists for.
    """

    tools: tuple[ToolPresence, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an inventory that is not exactly one entry per tool."""
        seen = [entry.tool for entry in self.tools]
        if len(seen) != len(set(seen)):
            msg = "a capability inventory records each tool once, and this one repeats"
            raise ValidationError(msg)
        if self.tools and set(seen) != set(Tool):
            missing = sorted(tool.value for tool in Tool if tool not in set(seen))
            msg = f"a capability inventory records every tool, and this one omits {missing}"
            raise ValidationError(msg)

    def presence(self, tool: Tool) -> ToolPresence:
        """What was recorded about one tool.

        Args:
            tool: Which tool.

        Returns:
            Its recorded presence, or an unmeasured one when the inventory is
            empty.
        """
        for entry in self.tools:
            if entry.tool is tool:
                return entry
        return ToolPresence(tool=tool, measured=False)

    def has(self, tool: Tool) -> bool:
        """Whether one tool was found.

        Args:
            tool: Which tool.

        Returns:
            ``True`` only when it was measured *and* found.
        """
        entry = self.presence(tool)
        return entry.measured and entry.present

    def launcher(self) -> Tool | None:
        """Which Python launcher this host has, preferring the manager.

        Returns:
            :attr:`Tool.PYTHON_MANAGER`, :attr:`Tool.LEGACY_LAUNCHER`, or
            ``None`` when neither was found.

        **The manager is detected by ``pymanager``, never by ``py`` existing.**
        Both launchers answer to ``py`` and both can be installed at once, so a
        host with the legacy one would otherwise be read as having the manager.
        This restates the rule ``tools/quality/runtime/plan.py`` applies on the
        gate side --- that package and this one cannot import each other, so the
        copy is deliberate and a contract test compares the two vocabularies.
        """
        if self.has(Tool.PYTHON_MANAGER):
            return Tool.PYTHON_MANAGER
        if self.has(Tool.LEGACY_LAUNCHER):
            return Tool.LEGACY_LAUNCHER
        return None

    def can_install_a_runtime(self) -> bool:
        """Whether anything on this host could install a Python runtime.

        Returns:
            ``True`` only when the install manager is present.

        The legacy launcher cannot install, which is measured rather than
        remembered: this host has it, and ``py install`` is not a command it has.
        """
        return self.has(Tool.PYTHON_MANAGER)

    def as_record(self) -> dict[str, object]:
        """This inventory as the mapping evidence carries.

        Returns:
            One entry per tool, in a stable order.
        """
        return {"tools": [entry.as_record() for entry in sorted(self.tools)]}


def version_probe(executable: str) -> CommandRequest:
    """The read-only command that asks one tool for its version.

    Args:
        executable: The tool's command name.

    Returns:
        A bounded request for ``<executable> --version``.

    Raises:
        ValidationError: If the name is empty or shell-shaped.
    """
    return CommandRequest(
        executable=executable, arguments=("--version",), timeout_millis=MIN_TIMEOUT_MILLIS * 10
    )


def probe_commands() -> tuple[CommandRequest, ...]:
    """Every command a read-only inspection is permitted to run.

    Returns:
        One version probe per declared tool, in member order.

    A function rather than a constant because building a
    :class:`CommandRequest` is a call, and a layer package performs none at
    import --- the rule :func:`globin.domain.bootstrap.checks` states about
    itself.

    This tuple is what :class:`globin.adapters.provisioning.ReadOnlyProcessRunner`
    admits, which is what makes ``bootstrap check`` and ``bootstrap plan``
    read-only in production rather than only under test.
    """
    return tuple(version_probe(tool.value) for tool in Tool)
