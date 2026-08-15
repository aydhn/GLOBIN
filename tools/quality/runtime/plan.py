r"""What the runtime baseline declares, and every judgement made about a host.

Pure. Every function here takes text or values and returns findings; nothing reads
a file, starts a process or looks at the clock. That is what lets the whole of the
reasoning be tested from literals, offline, in the way
``tools/quality/governance/plan.py`` separates its judgements from its gate.

The division matters more here than elsewhere, because the facts being judged are
facts about *this machine*. A test that had to observe a real host could only ever
assert what that host happens to be, which is why every observation below arrives
as an argument: a 32-bit interpreter, a free-threaded build and a Windows 8 host
are all testable here and none of them exists on the development machine.

**Paths are the privacy problem, and :func:`recorded_path` is the answer.** This
gate's manifest is uploaded as a CI artifact from a public repository, and on the
development host every absolute path outside the repository contains the account
holder's full name — ``pip`` resolves under ``AppData\Roaming`` and the base
interpreter under ``Program Files`` or a user directory. So a path inside the
repository is recorded relative to it, and a path outside is recorded as a
fingerprint and nothing else. There is no third option, and in particular no
option that writes the path out.

**Comparison is a floor, never equality.** ``minimum_patch`` is the oldest patch
the tree has been verified on. Requiring equality would fail the build on the day
a security patch was installed; requiring only the minor line would accept a patch
nobody had run the gates against. See ``docs/engineering/runtime-contract.toml``.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.quality.supply.secrets import fingerprint

CONFIGURATION_FILE: Final[str] = "docs/engineering/runtime-contract.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration format this module reads."""

FINAL_RELEASE: Final[str] = "final"
"""The value :data:`sys.version_info.releaselevel` carries for a real release.

Anything else — ``alpha``, ``beta``, ``candidate`` — is a prerelease, and the
contract refuses those by default because behaviour can still change underneath a
gate that passed on one.
"""

WINDOWS_KERNEL_FLOOR: Final[int] = 10
"""The kernel major version Windows 10 introduced.

The comparison is made against the kernel version from :func:`platform.win32_ver`
rather than against :func:`platform.release`, because the release string is not
ordered: Windows 11 reports ``"11"``, Windows 10 reports ``"10"``, and Windows
Server reports a *year*, so ``"2019" > "11"`` as text and as a number while being
older than Windows 11. The kernel version has no such problem — Windows 10 and 11
both report ``10.0``, and everything older reports ``6.x`` or less.
"""

VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MINOR_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)$")

LEGACY_RUNTIME_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-V:(?P<tag>\S+)(?P<default>\s+\*)?\s+(?P<path>\S.*?)\s*$"
)
"""One line of ``py -0p`` output, as the legacy launcher prints it.

Verified against this host and recorded in ``docs/research/phase_017_sources.md``
rather than taken from documentation, because the legacy launcher's output format
is not specified anywhere the Python documentation covers — it documents the
Python install manager, which prints something else entirely.
"""

VIRTUAL_ENV_RE: Final[re.Pattern[str]] = re.compile(
    r'^\s*set\s+"?VIRTUAL_ENV=(?P<path>[^"\r\n]+)"?\s*$', re.MULTILINE
)
"""The absolute location an environment was created at, as ``activate.bat`` records it.

This is the only artefact inside a virtual environment that remembers where it was
built, which makes it the only way to notice that one has been moved or copied.
:mod:`venv` states plainly that environments are "not considered as movable or
copyable", and a moved environment fails later, obscurely, in whichever script
still holds an absolute shebang.
"""


class RuntimeBaselineError(Exception):
    """The runtime baseline could not be read."""


class Launcher(StrEnum):
    """Which Python launching tool this host provides.

    Four states rather than the five a reader might expect. "The required runtime
    is not installed" is deliberately *not* one of them: that is a fact about the
    interpreters available, not about the tool used to find them, and it is
    reported by :func:`interpreter_problems` instead. Folding the two together
    would produce a value that could not distinguish "no manager" from "manager
    present, runtime absent", which are different problems with different fixes.
    """

    MANAGER = "python-install-manager"
    LEGACY = "legacy-launcher"
    INTERPRETER_ONLY = "interpreter-only"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True, order=True)
class Version:
    """A three-component release version.

    Args:
        major: The major version.
        minor: The minor version.
        micro: The patch version.

    ``order=True`` generates the comparisons from the field order, which is
    already major-then-minor-then-patch. Writing them by hand would be three
    chances to get an ordering wrong that nothing else in this file could catch.
    """

    major: int
    minor: int
    micro: int

    @property
    def text(self) -> str:
        """The version as it is written down."""
        return f"{self.major}.{self.minor}.{self.micro}"

    @property
    def line(self) -> str:
        """The minor line this version belongs to, such as ``"3.14"``."""
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True, slots=True)
class InterpreterPolicy:
    """What the contract requires of the interpreter.

    Args:
        implementation: The required implementation, such as ``"CPython"``.
        minor_line: The required series, such as ``"3.14"``. Exact, not a floor.
        minimum_patch: The oldest patch verified within that series.
        architecture: The required machine architecture.
        pointer_bits: The required interpreter width.
        free_threaded: Whether a free-threaded build is acceptable.
        allow_prerelease: Whether a prerelease is acceptable.
    """

    implementation: str
    minor_line: str
    minimum_patch: Version
    architecture: str
    pointer_bits: int
    free_threaded: bool
    allow_prerelease: bool


@dataclass(frozen=True, slots=True)
class HostPolicy:
    """What the contract requires of the operating system.

    Args:
        system: The required system name, as :func:`platform.system` spells it.
        minimum_release: The oldest supported release, as a human writes it.
    """

    system: str
    minimum_release: str


@dataclass(frozen=True, slots=True)
class EnvironmentPolicy:
    """What the contract requires of the project environment.

    Args:
        directory: The environment's directory name, at the repository root.
        system_site_packages: Whether the global site directory may be visible.
    """

    directory: str
    system_site_packages: bool


@dataclass(frozen=True, slots=True)
class Contract:
    """The whole declaration.

    Args:
        interpreter: The interpreter policy.
        host: The operating-system policy.
        environment: The project-environment policy.
    """

    interpreter: InterpreterPolicy
    host: HostPolicy
    environment: EnvironmentPolicy


@dataclass(frozen=True, slots=True)
class Interpreter:
    """What was observed about a running interpreter.

    Args:
        implementation: :data:`sys.implementation.name`.
        version: The three-component version.
        release_level: :data:`sys.version_info.releaselevel`.
        free_threaded: Whether the GIL is absent, from ``Py_GIL_DISABLED``.
        pointer_bits: The interpreter's width, from :func:`struct.calcsize`.
        machine: :func:`platform.machine`.
    """

    implementation: str
    version: Version
    release_level: str
    free_threaded: bool
    pointer_bits: int
    machine: str


@dataclass(frozen=True, slots=True)
class Host:
    """What was observed about the operating system.

    Args:
        system: :func:`platform.system`.
        release: :func:`platform.release`.
        kernel: The dotted kernel version, from :func:`platform.win32_ver`.
    """

    system: str
    release: str
    kernel: str


@dataclass(frozen=True, slots=True)
class Environment:
    """What was observed about the project environment on disk.

    Args:
        present: Whether the environment directory exists at all.
        location: Its resolved location, when it exists.
        recorded_location: Where ``activate.bat`` says it was created.
        config: The parsed ``pyvenv.cfg``.
        base_present: Whether the base interpreter ``pyvenv.cfg`` names still exists.
        interpreter_present: Whether ``Scripts/python.exe`` exists.
    """

    present: bool
    location: Path | None = None
    recorded_location: Path | None = None
    config: Mapping[str, str] = field(default_factory=dict)
    base_present: bool = False
    interpreter_present: bool = False


def parse_version(text: str) -> Version:
    """Read a three-component version.

    Args:
        text: The version, such as ``"3.14.5"``.

    Returns:
        The version.

    Raises:
        RuntimeBaselineError: If the text is not three dot-separated integers.

    A two-component version is refused rather than completed with a zero. ``3.14``
    and ``3.14.0`` mean different things in this file — one is a series and the
    other is a release — and quietly turning the first into the second would make
    the floor comparison assert something nobody wrote.
    """
    match = VERSION_RE.match(text.strip())
    if match is None:
        msg = f"not a three-component version: {text!r}"
        raise RuntimeBaselineError(msg)
    major, minor, micro = match.groups()
    return Version(int(major), int(minor), int(micro))


def parse_minor_line(text: str) -> tuple[int, int]:
    """Read a two-component series.

    Args:
        text: The series, such as ``"3.14"``.

    Returns:
        Its major and minor numbers.

    Raises:
        RuntimeBaselineError: If the text is not two dot-separated integers.
    """
    match = MINOR_RE.match(text.strip())
    if match is None:
        msg = f"not a two-component minor line: {text!r}"
        raise RuntimeBaselineError(msg)
    major, minor = match.groups()
    return int(major), int(minor)


def kernel_major(kernel: str) -> int | None:
    """Read the major number from a dotted kernel version.

    Args:
        kernel: The version, such as ``"10.0.26200"``.

    Returns:
        Its leading integer, or ``None`` when there is not one.

    ``None`` rather than a zero, because "this host did not report a kernel
    version" and "this host reported kernel 0" must not become the same finding.
    """
    head = kernel.strip().split(".", 1)[0]
    return int(head) if head.isdigit() else None


def interpreter_problems(observed: Interpreter, policy: InterpreterPolicy) -> tuple[str, ...]:
    """Report every way an interpreter fails the contract.

    Args:
        observed: What the interpreter reports about itself.
        policy: What the contract requires.

    Returns:
        One sentence per problem, in a stable order, empty when it complies.

    Every check runs; the function does not stop at the first failure. A 32-bit
    PyPy on the wrong minor line is three problems, and reporting one of them
    would send somebody round the loop three times.
    """
    problems: list[str] = []

    if observed.implementation.casefold() != policy.implementation.casefold():
        problems.append(
            f"implementation is {observed.implementation!r}, "
            f"and the contract requires {policy.implementation!r}"
        )

    if observed.version.line != policy.minor_line:
        problems.append(
            f"interpreter is on the {observed.version.line} line, "
            f"and the contract requires {policy.minor_line}"
        )
    elif observed.version < policy.minimum_patch:
        problems.append(
            f"interpreter is {observed.version.text}, which is older than the "
            f"verified baseline {policy.minimum_patch.text}"
        )

    if observed.release_level != FINAL_RELEASE and not policy.allow_prerelease:
        problems.append(
            f"interpreter is a prerelease ({observed.release_level}), "
            "and the contract requires a final release"
        )

    if observed.free_threaded and not policy.free_threaded:
        problems.append(
            "interpreter is a free-threaded build, and the contract requires the default build"
        )

    if observed.pointer_bits != policy.pointer_bits:
        problems.append(
            f"interpreter is {observed.pointer_bits}-bit, "
            f"and the contract requires {policy.pointer_bits}-bit"
        )

    if observed.machine.casefold() != policy.architecture.casefold():
        problems.append(
            f"machine architecture is {observed.machine!r}, "
            f"and the contract requires {policy.architecture!r}"
        )

    return tuple(problems)


def host_problems(observed: Host, policy: HostPolicy) -> tuple[str, ...]:
    """Report every way an operating system fails the contract.

    Args:
        observed: What the operating system reports about itself.
        policy: What the contract requires.

    Returns:
        One sentence per problem, empty when it complies.
    """
    problems: list[str] = []

    if observed.system.casefold() != policy.system.casefold():
        problems.append(
            f"operating system is {observed.system!r}, and the contract requires {policy.system!r}"
        )
        return tuple(problems)

    major = kernel_major(observed.kernel)
    if major is None:
        problems.append(
            f"the kernel version could not be read from {observed.kernel!r}, "
            "so the release floor is unmeasured"
        )
    elif major < WINDOWS_KERNEL_FLOOR:
        problems.append(
            f"kernel version {observed.kernel} is older than Windows {policy.minimum_release}"
        )

    return tuple(problems)


def parse_pyvenv_cfg(text: str) -> dict[str, str]:
    """Read the key-value file at the root of a virtual environment.

    Args:
        text: The contents of ``pyvenv.cfg``.

    Returns:
        Its settings, keys lower-cased, values stripped.

    Split on the first ``=`` only, because ``home`` and ``executable`` are Windows
    paths and a drive letter is followed by a colon rather than an equals sign —
    but ``command`` holds a whole command line and can contain a second one.
    """
    settings: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        settings[key.strip().casefold()] = value.strip()
    return settings


def environment_problems(
    observed: Environment,
    policy: EnvironmentPolicy,
    interpreter: InterpreterPolicy,
) -> tuple[str, ...]:
    """Report every way an existing environment fails the contract.

    Args:
        observed: What was found on disk.
        policy: What the contract requires of the environment.
        interpreter: What the contract requires of the interpreter, so that the
            version ``pyvenv.cfg`` records can be judged without launching it.

    Returns:
        One sentence per problem, empty when it complies. An absent environment is
        *not* a problem here — whether one is required is the caller's question,
        and ``bootstrap`` exists precisely to act on the absence.

    ``pyvenv.cfg`` is the load-bearing artefact. CPython writes the creating
    interpreter's full three-component version into it, which makes an exact-patch
    check a file read rather than a process launch, and it writes
    ``include-system-site-packages`` whether or not the flag was passed, which
    makes that setting checkable rather than merely intended.
    """
    if not observed.present:
        return ()

    problems: list[str] = []

    if not observed.interpreter_present:
        problems.append(
            f"{policy.directory} exists but has no Scripts/python.exe, "
            "so it is a partial or interrupted environment"
        )

    if not observed.config:
        problems.append(
            f"{policy.directory} has no readable pyvenv.cfg, so it cannot be "
            "identified as a virtual environment"
        )
        return tuple(problems)

    problems.extend(_site_packages_problems(observed.config, policy))
    problems.extend(_recorded_version_problems(observed.config, interpreter))

    if not observed.base_present:
        problems.append(
            "the base interpreter pyvenv.cfg names no longer exists, so this "
            "environment is stale and must be recreated"
        )

    problems.extend(_relocation_problems(observed))

    return tuple(problems)


def _site_packages_problems(
    config: Mapping[str, str], policy: EnvironmentPolicy
) -> tuple[str, ...]:
    """Judge the recorded global site-packages setting.

    Args:
        config: The parsed ``pyvenv.cfg``.
        policy: What the contract requires.

    Returns:
        One sentence per problem.

    A missing key is a problem rather than a default. :mod:`venv` writes the key
    unconditionally, so its absence means the file was written by something else
    or edited by hand, and neither is a state to assume ``false`` for.
    """
    recorded = config.get("include-system-site-packages")
    if recorded is None:
        return ("pyvenv.cfg does not record include-system-site-packages",)

    visible = recorded.strip().casefold() == "true"
    if visible and not policy.system_site_packages:
        return (
            "the environment was created with --system-site-packages, so the "
            "global site directory is visible and the contract forbids it",
        )
    return ()


def _recorded_version_problems(
    config: Mapping[str, str], interpreter: InterpreterPolicy
) -> tuple[str, ...]:
    """Judge the interpreter version ``pyvenv.cfg`` records.

    Args:
        config: The parsed ``pyvenv.cfg``.
        interpreter: What the contract requires.

    Returns:
        One sentence per problem.
    """
    recorded = config.get("version")
    if recorded is None:
        return ("pyvenv.cfg does not record the interpreter version",)

    try:
        version = parse_version(recorded)
    except RuntimeBaselineError:
        return (f"pyvenv.cfg records an unreadable interpreter version: {recorded!r}",)

    if version.line != interpreter.minor_line:
        return (
            f"the environment was created from Python {version.text}, and the "
            f"contract requires the {interpreter.minor_line} line",
        )
    if version < interpreter.minimum_patch:
        return (
            f"the environment was created from Python {version.text}, which is "
            f"older than the verified baseline {interpreter.minimum_patch.text}",
        )
    return ()


def _relocation_problems(observed: Environment) -> tuple[str, ...]:
    """Judge whether an environment is still where it was created.

    Args:
        observed: What was found on disk.

    Returns:
        One sentence per problem.

    A moved or copied environment is the failure this catches, and it is worth
    catching because it does not announce itself: the interpreter still runs, and
    only the console scripts — which hold absolute paths — misbehave.
    """
    if observed.recorded_location is None or observed.location is None:
        return ()
    if observed.recorded_location != observed.location:
        return (
            "this environment was created somewhere else and has been moved or "
            "copied, which venv does not support; recreate it in place",
        )
    return ()


def is_plain_directory_name(name: str) -> bool:
    """Whether a string names one directory and cannot escape its parent.

    Args:
        name: The candidate name.

    Returns:
        Whether it is a single component that is not a traversal.

    Written out rather than delegated to :class:`pathlib.PurePath`, because
    ``PurePosixPath("..").name`` is ``".."`` — so the obvious "is it its own final
    component?" test answers *yes* for the one input that most needs a *no*. A
    test caught that, which is the argument for the rule being a named function
    with its own cases rather than an expression inlined at two call sites.
    """
    return bool(name) and name not in {".", ".."} and "/" not in name and "\\" not in name


def deletion_problems(
    *,
    target: Path,
    root: Path,
    directory: str,
    is_reparse_point: bool,
) -> tuple[str, ...]:
    """Report every reason a directory must not be deleted.

    Args:
        target: The resolved directory a caller proposes to remove.
        root: The resolved repository root.
        directory: The environment directory name the contract declares.
        is_reparse_point: Whether the target is a symbolic link or junction.

    Returns:
        One sentence per reason, empty only when deletion is safe.

    **This function exists so that no recursive delete is ever decided in
    PowerShell.** ``Remove-Item -Recurse -Force`` against a path assembled from a
    variable is one bad join away from removing something that matters, and the
    check that prevents it belongs where a test can hold it rather than in a
    script nothing imports.

    The checks are deliberately redundant. Requiring the target to *equal*
    ``root/directory`` already implies it is inside the repository, and the
    containment check is written anyway — the two would have to fail together for
    a wrong path to get through, and they fail for different reasons.

    A reparse point is refused because deleting through one can remove the
    directory it points at rather than the link, and the link may point anywhere.
    """
    problems: list[str] = []
    expected = root / directory

    if not is_plain_directory_name(directory):
        problems.append(
            f"the declared environment directory {directory!r} is not a plain "
            "name, so it cannot be resolved safely"
        )
        return tuple(problems)

    if target != expected:
        problems.append(
            f"the target is not the declared environment directory "
            f"({directory!r} at the repository root)"
        )

    if root not in target.parents:
        problems.append("the target is outside the repository")

    if is_reparse_point:
        problems.append(
            "the target is a symbolic link or junction, and deleting through one "
            "can remove what it points at"
        )

    return tuple(problems)


def recorded_path(path: Path | None, *, root: Path) -> dict[str, str]:
    """Describe a path in a form that is safe to publish.

    Args:
        path: The path, already resolved, or ``None``.
        root: The resolved repository root.

    Returns:
        A record naming where the path is, and either its repository-relative
        spelling or a fingerprint — never an absolute path.

    Three outcomes and no fourth. A path inside the repository is recorded
    relative to it, because that is both meaningful to a reader and identical on
    every machine. A path outside is recorded as a fingerprint, because it is
    exactly the kind of value that carries an account name. Absence is recorded as
    absence rather than as an empty string, which would read as "a path that is
    the empty string".

    The fingerprint is stable, so two runs on one machine agree and a reader can
    tell "the same interpreter as last time" from "a different one" without ever
    being told which interpreter it is.
    """
    if path is None:
        return {"location": "absent"}
    try:
        relative = path.relative_to(root)
    except ValueError:
        return {"location": "outside", "fingerprint": fingerprint(str(path))}
    return {"location": "repository", "path": relative.as_posix()}


def parse_legacy_runtimes(text: str) -> tuple[dict[str, str], ...]:
    """Read the runtime list the legacy ``py.exe`` launcher prints.

    Args:
        text: The output of ``py -0p``.

    Returns:
        One entry per runtime, each carrying its tag and whether it is the
        default. **Paths are deliberately dropped** — the caller records them
        through :func:`recorded_path` or not at all, and returning them here would
        make it easy to write one into a manifest by accident.

    Lines that do not match are ignored rather than reported. The launcher prints
    a heading and, on some hosts, a warning; neither is a runtime and neither is a
    parse failure.
    """
    runtimes: list[dict[str, str]] = []
    for line in text.splitlines():
        match = LEGACY_RUNTIME_RE.match(line)
        if match is None:
            continue
        runtimes.append(
            {
                "tag": match.group("tag"),
                "default": "true" if match.group("default") else "false",
            }
        )
    return tuple(runtimes)


def parse_recorded_location(text: str) -> str | None:
    """Read the location an environment records for itself.

    Args:
        text: The contents of ``Scripts/activate.bat``.

    Returns:
        The absolute path the environment was created at, or ``None``.
    """
    match = VIRTUAL_ENV_RE.search(text)
    return match.group("path").strip() if match else None


def classify_launcher(*, manager: bool, legacy: bool, interpreter: bool) -> Launcher:
    """Decide which Python launching tool this host provides.

    Args:
        manager: Whether the Python install manager answered.
        legacy: Whether the legacy ``py.exe`` launcher answered.
        interpreter: Whether a bare ``python`` answered.

    Returns:
        The state, most capable first.

    Both launchers can be installed at once, and when they are, the legacy one
    takes precedence for the ``py`` command — which is why the manager is checked
    by a command the legacy launcher does not have rather than by ``py`` existing.
    """
    if manager:
        return Launcher.MANAGER
    if legacy:
        return Launcher.LEGACY
    if interpreter:
        return Launcher.INTERPRETER_ONLY
    return Launcher.ABSENT


def parse_declaration(text: str) -> Contract:
    """Read the runtime contract from TOML text.

    Args:
        text: The contents of ``runtime-contract.toml``.

    Returns:
        The contract.

    Raises:
        RuntimeBaselineError: If the text is not TOML, or the contract is
            malformed.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise RuntimeBaselineError(msg) from fault
    return read_declaration(document)


def read_declaration(document: Mapping[str, object]) -> Contract:
    """Read the runtime contract from a parsed document.

    Args:
        document: The parsed contract.

    Returns:
        The contract.

    Raises:
        RuntimeBaselineError: If the schema is unsupported or a table is
            malformed.

    Every value is required. There is no default for any of them, because a
    default here would be a policy decision made silently by whoever wrote this
    parser rather than deliberately by whoever wrote the contract.
    """
    schema = document.get("schema")
    if schema != SCHEMA:
        msg = (
            f"this tool reads {CONFIGURATION_FILE} schema {SCHEMA}, and the file "
            f"declares {schema!r}"
        )
        raise RuntimeBaselineError(msg)

    interpreter = _table(document, "interpreter")
    host = _table(document, "host")
    environment = _table(document, "environment")

    minor_line = _text(interpreter, "minor_line", "interpreter")
    parse_minor_line(minor_line)

    directory = _text(environment, "directory", "environment")
    if not is_plain_directory_name(directory):
        msg = f"[environment] directory must be a plain directory name, found {directory!r}"
        raise RuntimeBaselineError(msg)

    return Contract(
        interpreter=InterpreterPolicy(
            implementation=_text(interpreter, "implementation", "interpreter"),
            minor_line=minor_line,
            minimum_patch=parse_version(_text(interpreter, "minimum_patch", "interpreter")),
            architecture=_text(interpreter, "architecture", "interpreter"),
            pointer_bits=_integer(interpreter, "pointer_bits", "interpreter"),
            free_threaded=_flag(interpreter, "free_threaded", "interpreter"),
            allow_prerelease=_flag(interpreter, "allow_prerelease", "interpreter"),
        ),
        host=HostPolicy(
            system=_text(host, "system", "host"),
            minimum_release=_text(host, "minimum_release", "host"),
        ),
        environment=EnvironmentPolicy(
            directory=directory,
            system_site_packages=_flag(environment, "system_site_packages", "environment"),
        ),
    )


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Read a required sub-table.

    Args:
        document: The parsed contract.
        name: The table's name.

    Returns:
        The table.

    Raises:
        RuntimeBaselineError: If it is missing or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise RuntimeBaselineError(msg)
    return value


def _text(table: Mapping[str, object], key: str, name: str) -> str:
    """Read a required string.

    Args:
        table: The sub-table.
        key: The setting's name.
        name: The table's name, for the message.

    Returns:
        The value.

    Raises:
        RuntimeBaselineError: If it is missing or is not a string.
    """
    value = table.get(key)
    if not isinstance(value, str):
        msg = f"[{name}] {key} must be a string, found {value!r}"
        raise RuntimeBaselineError(msg)
    return value


def _integer(table: Mapping[str, object], key: str, name: str) -> int:
    """Read a required integer.

    Args:
        table: The sub-table.
        key: The setting's name.
        name: The table's name, for the message.

    Returns:
        The value.

    Raises:
        RuntimeBaselineError: If it is missing, is not an integer, or is a
            boolean — which TOML spells differently but Python does not.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"[{name}] {key} must be an integer, found {value!r}"
        raise RuntimeBaselineError(msg)
    return value


def _flag(table: Mapping[str, object], key: str, name: str) -> bool:
    """Read a required boolean.

    Args:
        table: The sub-table.
        key: The setting's name.
        name: The table's name, for the message.

    Returns:
        The value.

    Raises:
        RuntimeBaselineError: If it is missing or is not a boolean.
    """
    value = table.get(key)
    if not isinstance(value, bool):
        msg = f"[{name}] {key} must be a boolean, found {value!r}"
        raise RuntimeBaselineError(msg)
    return value


def toolchain_problems(pinned: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """Report why a set of toolchain pins cannot be installed.

    Args:
        pinned: Name and version pairs, as the workflow register declares them.

    Returns:
        One sentence per problem, empty when the set is usable.

    The pins are read from ``.github/workflows/`` rather than declared again here,
    so that bootstrapping an environment installs exactly what continuous
    integration measured. A fourth register would be a fourth thing to keep in
    step, and ``tools/quality/supply/inventory.py`` already reports when the three
    that exist disagree.
    """
    if not pinned:
        return ("no pinned toolchain was found in the workflow register",)

    problems: list[str] = []
    seen: dict[str, str] = {}
    for name, version in sorted(pinned):
        previous = seen.get(name)
        if previous is not None and previous != version:
            problems.append(f"the workflow register pins {name} at both {previous} and {version}")
        seen[name] = version
    return tuple(problems)
