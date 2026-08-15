"""Observing the host, judging it against the contract, and reducing that to one verdict.

**The judgement lives in :mod:`tools.quality.runtime.plan`; the observation and the
sequencing live here.** Every decision this file makes is delegated to a pure
function tested from literals. What this module adds is the reading of a real
machine, order, I/O, and the arithmetic that turns a set of answers into an exit
code — the same division ``tools/quality/governance/gate.py`` uses.

**Two subcommands, and only one of them changes anything.** ``check`` reads and
writes a manifest; it never creates, installs or deletes. ``bootstrap`` creates
the environment and installs the pinned toolchain into it. They are separate
because a doctor that might repair you is a doctor you cannot ask a question of,
and because ``check`` has to be safe to run from continuous integration, from a
pre-commit hook, and from a developer who only wants to know what is wrong.

**Neither reaches the network except to install.** ``check`` starts at most one
child process — the launcher, to enumerate runtimes — and opens no socket, so it
runs on an aeroplane and so do its tests. ``bootstrap`` calls ``pip``, which
plainly does reach an index; that is why the two are not one command.

**Nothing here changes the host.** No registry key is written, no PATH is edited,
no execution policy is relaxed, and no runtime is installed unless
``--install-python`` was passed and a manager exists to do it. Where a host
setting is wrong, this gate reports it and names the official remedy. A tool that
silently reconfigures the machine it is diagnosing destroys the evidence it was
run to collect.

**Determinism is checked rather than assumed.** The manifest is built twice and
the renderings compared byte for byte, exactly as the governance manifest is.
Asserting determinism in a docstring costs nothing and proves nothing.
"""

import importlib.util
import os
import platform
import shutil
import struct
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from tools.quality.evidence.redaction import describe as describe_findings
from tools.quality.evidence.redaction import scan as scan_for_secrets
from tools.quality.execution.plan import Verdict, combine
from tools.quality.runtime.manifest import (
    REASON_BOOTSTRAP_FAILED,
    REASON_DECLARATION_UNREADABLE,
    REASON_DELETION_REFUSED,
    REASON_ENVIRONMENT_ABSENT,
    REASON_ENVIRONMENT_NONCOMPLIANT,
    REASON_HOST_UNSUPPORTED,
    REASON_INTERPRETER_FOREIGN,
    REASON_INTERPRETER_NONCOMPLIANT,
    REASON_MANIFEST_LEAKAGE,
    REASON_MANIFEST_NONDETERMINISTIC,
    REASON_PIP_FOREIGN,
    REASON_TOOLCHAIN_UNAVAILABLE,
)
from tools.quality.runtime.manifest import build as build_manifest
from tools.quality.runtime.manifest import render as render_manifest
from tools.quality.runtime.plan import (
    CONFIGURATION_FILE,
    Contract,
    Environment,
    Host,
    Interpreter,
    Launcher,
    RuntimeBaselineError,
    Version,
    classify_launcher,
    deletion_problems,
    environment_problems,
    host_problems,
    interpreter_problems,
    parse_declaration,
    parse_legacy_runtimes,
    parse_pyvenv_cfg,
    parse_recorded_location,
    recorded_path,
    toolchain_problems,
)
from tools.quality.supply.inventory import (
    CONTINUOUS_INTEGRATION,
    PYPI,
    SupplyChainError,
    from_workflows,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository root, from this file's own location rather than the caller's
working directory."""

OUTPUT_DIRECTORY: Final[str] = ".globin/runtime"
"""Where the manifest is written, under the git-ignored evidence directory."""

MANIFEST_NAME: Final[str] = "runtime-manifest.json"

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_UNMEASURED: Final[int] = 3

DEFAULT_REPOSITORY: Final[str] = "aydhn/GLOBIN"
SHA_LENGTH: Final[int] = 40

MODE_CHECK: Final[str] = "check"
MODE_BOOTSTRAP: Final[str] = "bootstrap"

SCRIPTS_DIRECTORY: Final[str] = "Scripts"
"""Windows puts an environment's executables here; POSIX uses ``bin``.

Hard-coded rather than derived, because this repository declares exactly one
platform (ADR-0009) and a branch for a platform nobody runs is a branch nobody
tests.
"""

ENVIRONMENT_INTERPRETER: Final[str] = "python.exe"
ACTIVATE_SCRIPT: Final[str] = "activate.bat"
PYVENV_CONFIG: Final[str] = "pyvenv.cfg"

LONG_PATH_KEY: Final[str] = r"SYSTEM\CurrentControlSet\Control\FileSystem"
LONG_PATH_VALUE: Final[str] = "LongPathsEnabled"

PIP_ENVIRONMENT_PREFIX: Final[str] = "PIP_"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
"""How a child process is started.

Injected rather than called directly, for the reason
:mod:`tools.quality.supply.audit` gives about its own: the suite's offline guard
patches sockets in one interpreter and a child has its own view of the world, so a
function that starts one must be substitutable to be testable. The default is the
real thing, so no caller outside a test ever passes one.
"""


def _sha(root: Path) -> str:
    """The commit under test, read without starting a process.

    Args:
        root: The repository root.

    Returns:
        The forty-character SHA, or ``"unknown"``.

    Read from ``.git`` directly, exactly as ``tools/quality/governance/gate.py``
    does, so that a manifest can be produced in a tree without Git on the path.
    ``unknown`` is recorded as such rather than invented.
    """
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not text.startswith("ref:"):
        return text if len(text) == SHA_LENGTH else "unknown"
    reference = root / ".git" / text.removeprefix("ref:").strip()
    try:
        return reference.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _read(root: Path, relative: str) -> str | None:
    """Read a repository file.

    Args:
        root: The repository root.
        relative: The repository-relative path.

    Returns:
        Its contents, or ``None`` when it cannot be read.
    """
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _finding(problems: Sequence[str], *, measured: bool = True) -> dict[str, object]:
    """One check's entry in the manifest.

    Args:
        problems: What the check found.
        measured: Whether the check ran at all.

    Returns:
        The entry, carrying its own verdict.

    The order matters: an unmeasured check that also happens to have found nothing
    is unmeasured, not passed.
    """
    verdict = (
        Verdict.UNMEASURED if not measured else (Verdict.FAILED if problems else Verdict.PASSED)
    )
    return {"verdict": str(verdict), "problems": list(problems)}


def observe_interpreter() -> Interpreter:
    """Read what the running interpreter reports about itself.

    Returns:
        The observation.

    ``Py_GIL_DISABLED`` rather than :func:`sys._is_gil_enabled`, because the build
    configuration is the fact the contract is about: a free-threaded build with the
    GIL switched back on at run time is still a free-threaded build, with a
    free-threaded ABI and a different wheel set.
    """
    info = sys.version_info
    return Interpreter(
        implementation=sys.implementation.name,
        version=Version(info.major, info.minor, info.micro),
        release_level=info.releaselevel,
        free_threaded=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        pointer_bits=struct.calcsize("P") * 8,
        machine=platform.machine(),
    )


def observe_host() -> Host:
    """Read what the operating system reports about itself.

    Returns:
        The observation.

    The kernel version comes from :func:`platform.win32_ver`, whose second element
    is the dotted version that orders correctly. On anything that is not Windows it
    is empty, which :func:`~tools.quality.runtime.plan.host_problems` reports as
    unmeasured rather than treating as old.
    """
    _, build, _, _ = platform.win32_ver()
    return Host(system=platform.system(), release=platform.release(), kernel=build)


def observe_environment(root: Path, directory: str) -> Environment:
    """Read what is on disk at the declared environment directory.

    Args:
        root: The repository root.
        directory: The environment directory name the contract declares.

    Returns:
        The observation, with every path resolved.

    Nothing is launched. Everything this needs — the creating interpreter's exact
    version, whether the global site directory was made visible, and where the
    environment was built — is written into files by :mod:`venv` at creation time.
    """
    location = root / directory
    if not location.is_dir():
        return Environment(present=False)

    config = parse_pyvenv_cfg(_read(location, PYVENV_CONFIG) or "")
    home = config.get("home")

    activate = _read(location, f"{SCRIPTS_DIRECTORY}/{ACTIVATE_SCRIPT}") or ""
    recorded = parse_recorded_location(activate)

    return Environment(
        present=True,
        location=_resolve(location),
        recorded_location=_resolve(Path(recorded)) if recorded else None,
        config=config,
        base_present=home is not None and Path(home).is_dir(),
        interpreter_present=(location / SCRIPTS_DIRECTORY / ENVIRONMENT_INTERPRETER).is_file(),
    )


def _resolve(path: Path) -> Path | None:
    """Resolve a path, reporting an unresolvable one as absent.

    Args:
        path: The path.

    Returns:
        The resolved path, or ``None``.

    A path that cannot be resolved is recorded as absent rather than kept in its
    unresolved form, because an unresolved path is the one shape
    :func:`~tools.quality.runtime.plan.recorded_path` cannot reason about — it
    might be relative to a working directory nobody recorded.
    """
    try:
        return path.resolve(strict=False)
    except OSError:
        return None


def observe_pip(root: Path) -> dict[str, object]:
    """Describe where ``pip`` comes from and what is configured to change it.

    Args:
        root: The repository root.

    Returns:
        A record naming pip's version, where it lives, whether it belongs to the
        running interpreter, and which configuration sources exist.

    **No value is read, only whether a source exists.** An index URL is the single
    most likely place in this document for a credential to appear, so the way to
    keep one out is not to read it. ``PIP_*`` variables are recorded by name for
    the same reason: the name says an override is in force, which is the fact worth
    having, and the value says what it is, which is the fact worth not publishing.
    """
    origin = _pip_origin()
    prefix = _resolve(Path(sys.prefix))
    inside = bool(origin and prefix and origin.is_relative_to(prefix))

    return {
        "version": _pip_version(),
        "module": recorded_path(origin, root=root),
        "belongs_to_running_interpreter": inside,
        "configuration_sources": _pip_configuration_sources(),
        "environment_overrides": sorted(
            name for name in os.environ if name.startswith(PIP_ENVIRONMENT_PREFIX)
        ),
    }


def _pip_origin() -> Path | None:
    """Where ``pip`` would be imported from, without importing it.

    Returns:
        The package's location, or ``None`` when there is no pip.

    :func:`importlib.util.find_spec` locates the module without executing it, which
    matters because importing pip into the gate's own interpreter would be a side
    effect taken purely to answer a question about the filesystem.
    """
    try:
        spec = importlib.util.find_spec("pip")
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    return _resolve(Path(spec.origin).parent)


def _pip_version() -> str:
    """The installed pip version.

    Returns:
        The version, or ``"unknown"`` when pip's metadata cannot be read.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - importlib.metadata is stdlib
        return "unknown"
    try:
        return version("pip")
    except PackageNotFoundError:
        return "unknown"


def _pip_configuration_sources() -> list[dict[str, object]]:
    """Which pip configuration files exist on this host.

    Returns:
        One entry per documented location, naming its scope and whether it exists.
        **Never the path**, which on a user-scoped location contains the account
        name.

    The locations are the ones pip's own configuration documentation lists for
    Windows. They are computed rather than obtained from ``pip config debug``,
    because that command prints the settings as well as the paths, and a gate that
    captures a credential in order to report that a credential exists has already
    lost.
    """
    candidates: list[tuple[str, Path | None]] = [
        ("global", _joined(os.environ.get("PROGRAMDATA"), "pip", "pip.ini")),
        ("user", _joined(os.environ.get("APPDATA"), "pip", "pip.ini")),
        ("user-legacy", _joined(os.environ.get("HOME"), "pip", "pip.ini")),
        ("site", Path(sys.prefix) / "pip.ini"),
    ]
    return [{"scope": scope, "exists": bool(path and path.is_file())} for scope, path in candidates]


def _joined(base: str | None, *parts: str) -> Path | None:
    """Join a path under an environment variable that may be unset.

    Args:
        base: The variable's value, or ``None``.
        *parts: The path components beneath it.

    Returns:
        The path, or ``None`` when the variable is unset.
    """
    return Path(base).joinpath(*parts) if base else None


def observe_discovery(runner: Runner | None) -> dict[str, object]:
    """Find out which Python launching tool this host provides.

    Args:
        runner: How to start the launcher. Defaults to :func:`subprocess.run`.

    Returns:
        A record naming the launcher and what it reported.

    Presence is decided by :func:`shutil.which` rather than by running anything,
    because ``pymanager`` is the command the install manager documents as
    unambiguous and the legacy launcher does not have it. Only the enumeration
    starts a child.

    **The manager's runtimes are counted, not named.** Its ``--format=json`` output
    has a schema this repository has never seen on a host that has the manager, and
    inventing one would be exactly the guess ``AGENTS.md`` forbids. ``--format=exe``
    is documented to print one executable path per line, so the count is a fact and
    the paths are discarded rather than recorded.
    """
    manager = shutil.which("pymanager") is not None
    legacy = not manager and shutil.which("py") is not None
    launcher = classify_launcher(
        manager=manager, legacy=legacy, interpreter=shutil.which("python") is not None
    )

    record: dict[str, object] = {"launcher": str(launcher), "runtimes": [], "count": 0}

    if launcher is Launcher.LEGACY:
        listed = _launcher_output(("py", "-0p"), runner)
        if listed is not None:
            runtimes = parse_legacy_runtimes(listed)
            record["runtimes"] = list(runtimes)
            record["count"] = len(runtimes)
    elif launcher is Launcher.MANAGER:
        listed = _launcher_output(("py", "list", "--format=exe"), runner)
        if listed is not None:
            record["count"] = len([line for line in listed.splitlines() if line.strip()])

    return record


def _launcher_output(command: Sequence[str], runner: Runner | None) -> str | None:
    """Run a launcher and return what it printed.

    Args:
        command: The command and its arguments.
        runner: How to start it. Defaults to :func:`subprocess.run`.

    Returns:
        Its standard output, or ``None`` when it could not be run or refused.
    """
    try:
        completed = (runner or subprocess.run)(
            list(command),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def observe_long_paths() -> dict[str, object]:
    """Whether this host permits paths longer than the historic limit.

    Returns:
        A state and how it was established, never a bare pass.

    Read-only, and reported rather than fixed. Enabling long paths is a
    machine-wide registry change requiring administrator rights, and ADR-0045's
    rule applies exactly: an absence is recorded as an absence. A tool that quietly
    switched this on would be reconfiguring a machine it was asked to describe.
    """
    try:
        import winreg
    except ImportError:
        return {"state": "unmeasured", "reason": "this host has no Windows registry"}

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, LONG_PATH_KEY) as key:
            value, _ = winreg.QueryValueEx(key, LONG_PATH_VALUE)
    except OSError:
        return {"state": "unmeasured", "reason": "the registry value could not be read"}

    return {"state": "enabled" if value else "disabled", "reason": "read from the registry"}


def _contract_summary(contract: Contract) -> dict[str, object]:
    """The terms a manifest records so a reader need not open the contract.

    Args:
        contract: The parsed contract.

    Returns:
        The terms, as the contract states them.
    """
    return {
        "implementation": contract.interpreter.implementation,
        "minor_line": contract.interpreter.minor_line,
        "minimum_patch": contract.interpreter.minimum_patch.text,
        "architecture": contract.interpreter.architecture,
        "pointer_bits": contract.interpreter.pointer_bits,
        "free_threaded": contract.interpreter.free_threaded,
        "allow_prerelease": contract.interpreter.allow_prerelease,
        "system": contract.host.system,
        "minimum_release": contract.host.minimum_release,
        "directory": contract.environment.directory,
        "system_site_packages": contract.environment.system_site_packages,
    }


def _observed(
    root: Path,
    contract: Contract,
    interpreter: Interpreter,
    host: Host,
    environment: Environment,
    runner: Runner | None,
) -> dict[str, object]:
    """Everything the machine reports about itself, with paths made publishable.

    Args:
        root: The repository root.
        contract: The parsed contract.
        interpreter: The running interpreter.
        host: The operating system.
        environment: The project environment.
        runner: How to start the launcher.

    Returns:
        The record.
    """
    prefix = _resolve(Path(sys.prefix))
    base_prefix = _resolve(Path(sys.base_prefix))
    return {
        "host": {
            "system": host.system,
            "release": host.release,
            "kernel": host.kernel,
            "long_paths": observe_long_paths(),
        },
        "interpreter": {
            "implementation": interpreter.implementation,
            "version": interpreter.version.text,
            "release_level": interpreter.release_level,
            "free_threaded": interpreter.free_threaded,
            "pointer_bits": interpreter.pointer_bits,
            "machine": interpreter.machine,
            "executable": recorded_path(_resolve(Path(sys.executable)), root=root),
            "prefix": recorded_path(prefix, root=root),
            "base_prefix": recorded_path(base_prefix, root=root),
            "in_virtual_environment": prefix != base_prefix,
        },
        "environment": {
            "directory": contract.environment.directory,
            "present": environment.present,
            "location": recorded_path(environment.location, root=root),
            "created_from": environment.config.get("version", "unknown"),
            "system_site_packages": environment.config.get(
                "include-system-site-packages", "unknown"
            ),
            "base_present": environment.base_present,
            "interpreter_present": environment.interpreter_present,
        },
        "pip": observe_pip(root),
        "discovery": observe_discovery(runner),
    }


def _interpreter_is_environment(environment: Environment) -> bool:
    """Whether the running interpreter is the project environment's own.

    Args:
        environment: The observed environment.

    Returns:
        Whether the interpreter running this gate came out of the environment.

    The comparison is against :data:`sys.prefix`, which a virtual environment sets
    to its own directory, rather than against :data:`sys.executable`, which a
    launcher or a shim can make point somewhere surprising.
    """
    if not environment.present or environment.location is None:
        return False
    prefix = _resolve(Path(sys.prefix))
    if prefix is None or prefix != environment.location:
        return False
    return prefix != _resolve(Path(sys.base_prefix))


def run_runtime(
    *,
    root: Path | None = None,
    reports: Path | None = None,
    bootstrap: bool = False,
    recreate: bool = False,
    install_python: bool = False,
    runner: Runner | None = None,
) -> int:
    """Check the host against the runtime contract, and optionally build the environment.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.
        reports: Where to write. Defaults to :data:`OUTPUT_DIRECTORY` under root.
        bootstrap: Whether to create the environment and install the toolchain.
            False for the read-only check.
        recreate: Whether an existing environment may be removed and rebuilt.
            Only meaningful with ``bootstrap``.
        install_python: Whether a missing runtime may be installed through the
            Python install manager. Only meaningful with ``bootstrap``, and opt-in
            because installing a runtime changes the host.
        runner: How to start children. Defaults to :func:`subprocess.run`.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED` or :data:`EXIT_UNMEASURED`.
    """
    base = REPO_ROOT if root is None else root
    directory = (base / OUTPUT_DIRECTORY) if reports is None else reports
    directory.mkdir(parents=True, exist_ok=True)

    declared = _read(base, CONFIGURATION_FILE)
    if declared is None:
        problem = f"{CONFIGURATION_FILE} could not be read"
        return _fail_early(directory, base, problem, REASON_DECLARATION_UNREADABLE)

    try:
        contract = parse_declaration(declared)
    except RuntimeBaselineError as fault:
        return _fail_early(directory, base, str(fault), REASON_DECLARATION_UNREADABLE)

    interpreter = observe_interpreter()
    host = observe_host()
    findings: dict[str, object] = {}
    reasons: list[str] = []

    problems = host_problems(host, contract.host)
    findings["host"] = _finding(problems)
    if problems:
        reasons.append(REASON_HOST_UNSUPPORTED)

    problems = interpreter_problems(interpreter, contract.interpreter)
    findings["interpreter"] = _finding(problems)
    if problems:
        reasons.append(REASON_INTERPRETER_NONCOMPLIANT)

    if bootstrap and problems:
        # An environment inherits the interpreter it was built from, so building
        # one from an interpreter that already fails the contract would bake the
        # failure in and then report it as an environment problem on every run
        # afterwards. Refusing here keeps the diagnosis where the fault is.
        findings["environment_creation"] = _finding(
            (
                "refused to build an environment from an interpreter that does "
                "not satisfy the contract; fix the interpreter first, or pass a "
                "compliant one with -Interpreter",
            )
        )
        reasons.append(REASON_BOOTSTRAP_FAILED)
    elif bootstrap:
        _bootstrap(
            base,
            contract,
            findings,
            reasons,
            recreate=recreate,
            install_python=install_python,
            runner=runner,
        )

    environment = observe_environment(base, contract.environment.directory)
    _judge_environment(contract, environment, findings, reasons, bootstrapping=bootstrap)

    mode = MODE_BOOTSTRAP if bootstrap else MODE_CHECK
    run: dict[str, object] = {
        "repository": DEFAULT_REPOSITORY,
        "commit": _sha(base),
        "declaration": CONFIGURATION_FILE,
        "mode": mode,
        "contract": _contract_summary(contract),
    }
    observed = _observed(base, contract, interpreter, host, environment, runner)
    discovery = observed.get("discovery")
    launcher = discovery.get("launcher") if isinstance(discovery, dict) else None
    capability: dict[str, object] = {
        "python_install_manager": {
            "state": launcher if isinstance(launcher, str) else "unmeasured",
            "authority": "shutil.which, then the launcher's own listing",
            "reason": (
                "Recorded rather than required. The manager is the documented way "
                "to install a runtime on Windows, and its absence only removes "
                "--install-python; it does not make a compliant host non-compliant."
            ),
        },
        "long_paths": observe_long_paths(),
    }

    return _write(directory, run, observed, findings, capability, reasons)


def _judge_environment(
    contract: Contract,
    environment: Environment,
    findings: dict[str, object],
    reasons: list[str],
    *,
    bootstrapping: bool,
) -> None:
    """Judge the project environment and the interpreter that is running.

    Args:
        contract: The parsed contract.
        environment: The observed environment.
        findings: The findings so far, added to in place.
        reasons: The reason codes so far, added to in place.
        bootstrapping: Whether this run was allowed to change things, which
            decides whether running from outside the environment is a problem.

    ``bootstrap`` necessarily runs from the base interpreter, because the
    environment it is about to create does not exist yet. Reporting that as a
    foreign interpreter would be reporting the one thing that cannot be otherwise.
    """
    if not environment.present:
        findings["environment"] = _finding(
            (
                f"{contract.environment.directory} does not exist; "
                "run scripts/bootstrap.ps1 to create it",
            )
        )
        reasons.append(REASON_ENVIRONMENT_ABSENT)
    else:
        problems = environment_problems(environment, contract.environment, contract.interpreter)
        findings["environment"] = _finding(problems)
        if problems:
            reasons.append(REASON_ENVIRONMENT_NONCOMPLIANT)

    if bootstrapping:
        # Omitted rather than recorded as unmeasured, and the distinction is the
        # one `Status.NOT_APPLICABLE` draws in the release plan. "We could not
        # measure this" is a gap in the evidence and rightly outranks a failure;
        # "this cannot apply to this run" is neither. Bootstrap necessarily runs
        # from the base interpreter, so asking whether it is the environment's own
        # has no answer worth having — `bootstrap.ps1` asks it afterwards, through
        # the interpreter that now exists. `run.mode` records which run this was,
        # so a reader knows why the two keys are absent.
        return

    owned = _interpreter_is_environment(environment)
    if environment.present and not owned:
        findings["running_interpreter"] = _finding(
            (
                "this gate is not running from the project environment, so what it "
                f"measured is not what {contract.environment.directory} contains; "
                "invoke it as .venv\\Scripts\\python.exe -m tools.quality.runtime",
            )
        )
        reasons.append(REASON_INTERPRETER_FOREIGN)
    else:
        findings["running_interpreter"] = _finding(())

    origin = _pip_origin()
    prefix = _resolve(Path(sys.prefix))
    if origin is None:
        findings["pip_origin"] = _finding(("no pip is importable from this interpreter",))
        reasons.append(REASON_PIP_FOREIGN)
    elif prefix is not None and not origin.is_relative_to(prefix):
        findings["pip_origin"] = _finding(
            (
                "pip does not belong to the running interpreter, so `pip install` "
                "would write somewhere other than this environment",
            )
        )
        reasons.append(REASON_PIP_FOREIGN)
    else:
        findings["pip_origin"] = _finding(())


def _bootstrap(
    root: Path,
    contract: Contract,
    findings: dict[str, object],
    reasons: list[str],
    *,
    recreate: bool,
    install_python: bool,
    runner: Runner | None,
) -> None:
    """Create the environment and install the pinned toolchain into it.

    Args:
        root: The repository root.
        contract: The parsed contract.
        findings: The findings so far, added to in place.
        reasons: The reason codes so far, added to in place.
        recreate: Whether an existing environment may be removed first.
        install_python: Whether a missing runtime may be installed.
        runner: How to start children.

    The order is deliberate: remove only if asked and only if safe, create only if
    absent, install only if created or already present. Each step records its own
    finding, so a failure names the step rather than the phase.
    """
    directory = contract.environment.directory
    location = root / directory

    if install_python:
        findings["runtime_installation"] = _finding(
            (
                "--install-python was requested; this host's launcher cannot "
                "install a runtime, and no runtime was installed. See "
                "docs/engineering/RUNTIME_BASELINE.md for the manual route.",
            ),
            measured=shutil.which("pymanager") is not None,
        )

    if recreate and location.exists():
        problems = _remove(root, location, directory)
        findings["environment_removal"] = _finding(problems)
        if problems:
            reasons.append(REASON_DELETION_REFUSED)
            return
    elif recreate:
        findings["environment_removal"] = _finding(())

    if not location.exists():
        problems = _create(location, runner)
        findings["environment_creation"] = _finding(problems)
        if problems:
            reasons.append(REASON_BOOTSTRAP_FAILED)
            return
    else:
        findings["environment_creation"] = _finding(())

    problems = _install_toolchain(root, location, runner)
    findings["toolchain"] = _finding(problems)
    if problems:
        reasons.append(REASON_TOOLCHAIN_UNAVAILABLE)


def _remove(root: Path, location: Path, directory: str) -> tuple[str, ...]:
    """Remove an existing environment, but only after proving it is safe to.

    Args:
        root: The repository root.
        location: The directory proposed for removal.
        directory: The environment directory name the contract declares.

    Returns:
        One sentence per reason it was not removed, empty when it was.

    The decision is :func:`~tools.quality.runtime.plan.deletion_problems`, which is
    pure and tested from literals. This function only supplies the two facts that
    need a filesystem — where the path actually resolves to, and whether it is a
    reparse point — and then does what it is told.
    """
    resolved = _resolve(location)
    resolved_root = _resolve(root)
    if resolved is None or resolved_root is None:
        return ("the environment directory could not be resolved, so it was not removed",)

    problems = deletion_problems(
        target=resolved,
        root=resolved_root,
        directory=directory,
        is_reparse_point=location.is_symlink(),
    )
    if problems:
        return problems

    try:
        shutil.rmtree(resolved)
    except OSError as fault:
        return (f"the environment could not be removed: {fault}",)
    return ()


def _create(location: Path, runner: Runner | None) -> tuple[str, ...]:
    """Create a virtual environment at a location.

    Args:
        location: Where to create it.
        runner: How to start the child.

    Returns:
        One sentence per problem, empty on success.

    ``--copies`` is not passed because copies are already the Windows default, and
    ``--system-site-packages`` is not passed because the contract forbids it. Both
    are stated here rather than left implicit, since the whole point of this gate is
    that the environment's properties are decided rather than inherited.
    """
    try:
        completed = (runner or subprocess.run)(
            [sys.executable, "-m", "venv", str(location)],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as fault:
        return (f"the environment could not be created: {fault}",)
    if completed.returncode != 0:
        return (f"python -m venv exited {completed.returncode}: {_tail(completed.stderr)}",)
    return ()


def _install_toolchain(root: Path, location: Path, runner: Runner | None) -> tuple[str, ...]:
    """Install the pinned development toolchain into an environment.

    Args:
        root: The repository root.
        location: The environment.
        runner: How to start the child.

    Returns:
        One sentence per problem, empty on success.

    **The versions come from the workflow register, not from here.**
    ``.github/workflows/`` already pins them exactly, and
    :func:`tools.quality.supply.inventory.from_workflows` already parses them, so
    an environment built by this function contains exactly what continuous
    integration measured. Declaring them again would be a fourth register for
    ``tools/quality/supply`` to find disagreeing with the other three.
    """
    try:
        declared = from_workflows(root)
    except (SupplyChainError, OSError) as fault:
        return (f"the workflow register could not be read: {fault}",)

    pinned = tuple(
        (entry.name, entry.version)
        for entry in declared
        if entry.ecosystem == PYPI and entry.scope == CONTINUOUS_INTEGRATION
    )
    problems = toolchain_problems(pinned)
    if problems:
        return problems

    interpreter = location / SCRIPTS_DIRECTORY / ENVIRONMENT_INTERPRETER
    requirements = [f"{name}=={version}" for name, version in sorted(set(pinned))]
    try:
        completed = (runner or subprocess.run)(
            [
                str(interpreter),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *requirements,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as fault:
        return (f"the toolchain could not be installed: {fault}",)
    if completed.returncode != 0:
        return (f"pip install exited {completed.returncode}: {_tail(completed.stderr)}",)
    return ()


def _tail(text: str | None, limit: int = 400) -> str:
    """The end of a child's error output, short enough to put in a finding.

    Args:
        text: What the child wrote, or ``None``.
        limit: How many characters to keep.

    Returns:
        The last ``limit`` characters, with newlines flattened.
    """
    if not text:
        return "no output"
    flattened = " ".join(text.split())
    return flattened[-limit:]


def _write(
    directory: Path,
    run: dict[str, object],
    observed: dict[str, object],
    findings: dict[str, object],
    capability: dict[str, object],
    reasons: list[str],
) -> int:
    """Seal the manifest, check it, write it and report.

    Args:
        directory: Where to write.
        run: What was judged.
        observed: What the machine reported.
        findings: Every check's entry.
        capability: The platform states.
        reasons: The reason codes so far.

    Returns:
        The exit code.
    """
    verdict = combine([_verdict_of(entry) for entry in findings.values()])

    def document() -> dict[str, object]:
        return build_manifest(
            run=run,
            observed=observed,
            findings=findings,
            capability=capability,
            verdict={"verdict": str(verdict), "reasons": sorted(set(reasons))},
        )

    rendered = render_manifest(document())
    if rendered != render_manifest(document()):
        reasons.append(REASON_MANIFEST_NONDETERMINISTIC)
        verdict = Verdict.FAILED

    leaks = scan_for_secrets(MANIFEST_NAME, rendered)
    if leaks:
        reasons.append(REASON_MANIFEST_LEAKAGE)
        verdict = Verdict.FAILED
        print("runtime: the manifest carries something it must not:")
        print(describe_findings(leaks))

    if REASON_MANIFEST_NONDETERMINISTIC in reasons or REASON_MANIFEST_LEAKAGE in reasons:
        rendered = render_manifest(document())

    (directory / MANIFEST_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    _report(findings, verdict, reasons)
    return _exit_code(verdict)


def _verdict_of(entry: object) -> Verdict:
    """Read one finding's verdict back out of the manifest entry.

    Args:
        entry: The finding.

    Returns:
        Its verdict, defaulting to unmeasured for anything unrecognised.
    """
    if isinstance(entry, dict):
        recorded = entry.get("verdict")
        for verdict in (Verdict.PASSED, Verdict.FAILED, Verdict.UNMEASURED):
            if recorded == str(verdict):
                return verdict
    return Verdict.UNMEASURED


def _exit_code(verdict: Verdict) -> int:
    """Turn a verdict into a process exit code.

    Args:
        verdict: The gate's conclusion.

    Returns:
        The code.
    """
    if verdict is Verdict.PASSED:
        return EXIT_OK
    return EXIT_GATE_FAILED if verdict is Verdict.FAILED else EXIT_UNMEASURED


def _fail_early(directory: Path, root: Path, problem: str, reason: str) -> int:
    """Write a manifest recording that the gate could not read its own input.

    Args:
        directory: Where to write.
        root: The repository root.
        problem: What went wrong.
        reason: The stable reason code.

    Returns:
        :data:`EXIT_GATE_FAILED`.

    A manifest is still written. A gate that failed silently and left no artefact
    would be indistinguishable, to anything reading the evidence afterwards, from a
    gate that never ran.
    """
    document = build_manifest(
        run={
            "repository": DEFAULT_REPOSITORY,
            "commit": _sha(root),
            "declaration": CONFIGURATION_FILE,
            "mode": MODE_CHECK,
        },
        observed={},
        findings={"declaration": _finding((problem,))},
        capability={},
        verdict={"verdict": str(Verdict.FAILED), "reasons": [reason]},
    )
    (directory / MANIFEST_NAME).write_text(
        render_manifest(document), encoding="utf-8", newline="\n"
    )
    print(f"runtime: {problem}")
    return EXIT_GATE_FAILED


def _report(findings: dict[str, object], verdict: Verdict, reasons: Sequence[str]) -> None:
    """Print what the gate established.

    Args:
        findings: Every check's entry.
        verdict: The conclusion.
        reasons: The stable reason codes behind it.

    ASCII only, because everything a gate prints must be — a Windows console
    encodes its output with the active code page, and a character it cannot
    represent turns a report into a traceback.
    """
    for name, entry in sorted(findings.items()):
        if not isinstance(entry, dict):
            continue
        print(f"runtime: {name}: {entry.get('verdict')}")
        problems = entry.get("problems")
        if isinstance(problems, list):
            for problem in problems:
                print(f"  - {problem}")
    print(f"runtime: manifest {OUTPUT_DIRECTORY}/{MANIFEST_NAME}")
    print(f"runtime: verdict {verdict}")
    if reasons:
        print(f"runtime: reasons {', '.join(sorted(set(reasons)))}")
