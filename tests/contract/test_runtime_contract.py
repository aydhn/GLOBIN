"""The runtime baseline, asserted against this repository rather than a fixture.

``tests/integration/test_runtime_end_to_end.py`` establishes that the gate reaches
the right verdict about *a* tree. This asserts the facts about *this* one, and it
lives at the contract level so that it runs inside the ordinary suite — which means
every ``full`` run and every pre-commit run gates on it, without anybody
remembering to invoke a separate command.

**Offline and read-only.** Nothing here starts a process, reaches the network, or
looks at the machine it is running on. Whether *this host* satisfies the contract
is a different question, asked by ``python -m tools.quality runtime``; asserting it
here would make the suite fail on a machine that had not been bootstrapped yet,
which is the machine most in need of running the suite.

**The PowerShell scripts spell ``.venv`` and so does the contract.** That
duplication is deliberate and is a tripwire rather than a second source, in the
sense ``docs/engineering/SOURCE_OF_TRUTH.md`` describes: the copies are compared
here, and a rename that touched only one of them fails. Windows PowerShell 5.1 has
no TOML reader, and adding one to parse a single string would be more machinery
than the problem has.
"""

import re
import tomllib
from pathlib import Path

import pytest

from tools.quality.commands import COMMANDS, find
from tools.quality.runtime import gate, manifest, plan

SCRIPTS = ("scripts/bootstrap.ps1", "scripts/preflight.ps1", "scripts/verify.ps1")

NEW_SCRIPTS = ("scripts/bootstrap.ps1", "scripts/preflight.ps1")
"""The scripts Phase 017 added, which use strict mode.

``verify.ps1`` predates the convention and is not retrofitted here: changing how an
existing gate handles errors is a change to the gate, not a tidy-up, and it would
belong to its own phase with its own argument.
"""


@pytest.fixture(scope="module")
def declaration(repo_root: Path) -> plan.Contract:
    """The contract this repository actually carries."""
    return plan.parse_declaration((repo_root / plan.CONFIGURATION_FILE).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The contract is readable, and says what this repository decided
# ---------------------------------------------------------------------------


def test_the_contract_parses(declaration: plan.Contract) -> None:
    """A contract nothing can read is a document, not a contract."""
    assert declaration.interpreter.implementation == "CPython"
    assert declaration.environment.directory == ".venv"


def test_the_contract_forbids_the_global_site_directory(declaration: plan.Contract) -> None:
    """The setting that makes an environment's contents depend on its machine."""
    assert declaration.environment.system_site_packages is False


def test_the_contract_refuses_a_prerelease_and_a_free_threaded_build(
    declaration: plan.Contract,
) -> None:
    """Both are refusals to assume an answer nobody has looked up.

    Phase 018 owns the wheel-availability survey that could change either.
    """
    assert declaration.interpreter.allow_prerelease is False
    assert declaration.interpreter.free_threaded is False


def test_the_contract_requires_a_sixty_four_bit_interpreter(
    declaration: plan.Contract,
) -> None:
    assert declaration.interpreter.pointer_bits == 64
    assert declaration.interpreter.architecture == "AMD64"


def test_the_contract_is_windows_only(declaration: plan.Contract) -> None:
    """GLOBIN declares one platform (ADR-0009), and CI runs on it alone."""
    assert declaration.host.system == "Windows"


def test_the_patch_floor_belongs_to_the_declared_minor_line(
    declaration: plan.Contract,
) -> None:
    """A floor on another line would accept nothing.

    Would say so only at run time on somebody else's machine.
    """
    assert declaration.interpreter.minimum_patch.line == declaration.interpreter.minor_line


def test_the_patch_floor_satisfies_the_packaging_metadata(
    repo_root: Path, declaration: plan.Contract
) -> None:
    """Two different facts that must not contradict each other.

    ``requires-python`` is the range the *package* supports, and is evidence-based:
    XGBoost, due in Phase 182, is the strictest constraint at >=3.12. The runtime
    contract is the baseline the *development host* must meet, which is narrower on
    purpose. Narrower is fine; outside is a contradiction, and would mean the host
    this repository is verified on is one the package declares it does not support.
    """
    document = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    requires = document["project"]["requires-python"]
    floor = tuple(int(part) for part in requires.removeprefix(">=").split("."))

    baseline = declaration.interpreter.minimum_patch
    assert (baseline.major, baseline.minor) >= floor, (
        f"the runtime baseline {baseline.text} is below requires-python {requires}"
    )


# ---------------------------------------------------------------------------
# The command is registered exactly once, and is not in fast or full
# ---------------------------------------------------------------------------


def test_the_gate_is_registered_in_the_one_command_table() -> None:
    """Every check is a name in ``tools/quality/commands.py`` and nowhere else."""
    command = find("runtime")
    assert command is not None
    assert [step.argv for step in command.steps] == [("-m", "tools.quality.runtime")]


def test_the_gate_declares_no_modules() -> None:
    """It starts no *Python* child.

    The launcher it consults is an executable, and a host without one records that as a state
    rather than as a missing tool.
    """
    command = find("runtime")
    assert command is not None
    assert all(step.modules == () for step in command.steps)


def test_the_gate_is_absent_from_fast_and_full() -> None:
    """It writes an artefact.

    ``full`` runs before every commit and reports rather than produces.

    What must gate a commit is this file, which the coverage step already runs.
    """
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert all(step.name != "runtime" for step in command.steps)


def test_the_gate_does_not_modify_the_tree_when_it_is_run_by_the_table() -> None:
    """``bootstrap`` can create an environment.

    The registered step never asks for it, so no gate run can build one as a side effect.
    """
    command = find("runtime")
    assert command is not None
    for step in command.steps:
        assert "bootstrap" not in step.argv
        assert "--recreate" not in step.argv


def test_the_command_summary_is_ascii_like_every_other() -> None:
    command = find("runtime")
    assert command is not None
    assert command.summary.isascii()


def test_the_command_name_appears_once_in_the_table() -> None:
    assert [command.name for command in COMMANDS].count("runtime") == 1


# ---------------------------------------------------------------------------
# Where it writes, and that the tree ignores it
# ---------------------------------------------------------------------------


def test_the_gate_writes_under_the_ignored_evidence_directory(repo_root: Path) -> None:
    assert gate.OUTPUT_DIRECTORY.startswith(".globin/")
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".globin/" in ignored


def test_the_environment_directory_is_ignored(repo_root: Path, declaration: plan.Contract) -> None:
    """An environment is disposable local state.

    Not a build artefact and not something to commit.

    The rule must exist before the first byte is written.
    """
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert f"{declaration.environment.directory}/" in ignored


def test_the_environment_is_not_tracked(declaration: plan.Contract) -> None:
    """The ignore rule is what should prevent this; this is what establishes it did."""
    from tests.support import git_committable_files

    directory = f"{declaration.environment.directory}/"
    offenders = [path for path in git_committable_files() if path.startswith(directory)]
    assert not offenders, f"the environment is committable: {offenders[:5]}"


# ---------------------------------------------------------------------------
# Reason codes are a closed set
# ---------------------------------------------------------------------------


def test_every_reason_the_gate_can_emit_is_declared() -> None:
    """A new failure mode must not arrive with an undeclared name.

    That is because a reason code is what a machine reads.
    """
    source = Path(gate.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r"REASON_[A-Z_]+", source))
    declared = {name for name in dir(manifest) if name.startswith("REASON_")}
    assert emitted <= declared, (
        f"the gate names reasons the manifest does not declare: {sorted(emitted - declared)}"
    )
    for name in emitted:
        assert getattr(manifest, name) in manifest.REASONS


def test_no_declared_reason_is_unreachable() -> None:
    """The other direction.

    A code no gate can emit is a code that describes nothing, and it would sit in the closed set
    looking like coverage.
    """
    source = Path(gate.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r"REASON_[A-Z_]+", source))
    declared = {name for name in dir(manifest) if name.startswith("REASON_")}
    assert declared <= emitted, (
        f"the manifest declares reasons no gate emits: {sorted(declared - emitted)}"
    )


# ---------------------------------------------------------------------------
# The scripts agree with the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative", SCRIPTS)
def test_every_script_spells_the_declared_environment_directory(
    repo_root: Path, declaration: plan.Contract, relative: str
) -> None:
    """The tripwire.

    PowerShell cannot read the contract, so it carries a copy, and a rename that touched only
    one of them fails here.
    """
    source = (repo_root / relative).read_text(encoding="utf-8")
    assert f"$EnvironmentDirectory = '{declaration.environment.directory}'" in source


@pytest.mark.parametrize("relative", SCRIPTS)
def test_every_script_resolves_the_repository_from_its_own_location(
    repo_root: Path, relative: str
) -> None:
    """So the scripts work from any working directory, and on any drive."""
    source = (repo_root / relative).read_text(encoding="utf-8")
    assert "$PSScriptRoot" in source


@pytest.mark.parametrize("relative", SCRIPTS)
def test_no_script_composes_a_recursive_delete(repo_root: Path, relative: str) -> None:
    """Every deletion decision lives in ``plan.deletion_problems``, where a test can hold it.

    A ``Remove-Item -Recurse`` built from a variable in PowerShell is one bad join away from
    removing something that matters.
    """
    source = (repo_root / relative).read_text(encoding="utf-8")
    assert "Remove-Item" not in source


@pytest.mark.parametrize("relative", NEW_SCRIPTS)
def test_the_new_scripts_use_strict_mode(repo_root: Path, relative: str) -> None:
    source = (repo_root / relative).read_text(encoding="utf-8")
    assert "Set-StrictMode -Version Latest" in source
    assert "$ErrorActionPreference = 'Stop'" in source


def test_the_verification_gate_uses_the_environment_interpreter(repo_root: Path) -> None:
    """Before Phase 017 this script invoked whichever ``python`` the PATH resolved first.

    On the development host that is one of two, and "the checks passed" named neither.
    """
    source = (repo_root / "scripts" / "verify.ps1").read_text(encoding="utf-8")
    assert "& $Python -m tools.quality $Command" in source
    assert "\npython -m tools.quality" not in source


def test_the_verification_gate_has_no_fallback_to_a_path_interpreter(
    repo_root: Path,
) -> None:
    """An escape hatch would be used on exactly the day the environment was wrong.

    That is the day the gate's answer matters most.
    """
    source = (repo_root / "scripts" / "verify.ps1").read_text(encoding="utf-8")
    assert "bootstrap.ps1" in source, "the refusal must name the way out of it"
    assert "-AllowSystemPython" not in source


def test_the_preflight_script_changes_nothing(repo_root: Path) -> None:
    """A diagnostic that might also repair you is one you cannot safely ask a question of."""
    source = (repo_root / "scripts" / "preflight.ps1").read_text(encoding="utf-8")
    assert "tools.quality.runtime check" in source
    assert "tools.quality.runtime bootstrap" not in source
    assert "--recreate" not in source
    assert "--install-python" not in source
    assert "New-Item" not in source


@pytest.mark.parametrize("relative", SCRIPTS)
def test_no_script_changes_the_host(repo_root: Path, relative: str) -> None:
    """No registry key, no PATH, no execution policy.

    Where a host setting is wrong the gate reports it and names the official remedy.
    """
    source = (repo_root / relative).read_text(encoding="utf-8")
    for forbidden in (
        "Set-ItemProperty",
        "New-ItemProperty",
        "Set-ExecutionPolicy",
        "setx",
        "[Environment]::SetEnvironmentVariable",
    ):
        assert forbidden not in source, f"{relative} changes the host with {forbidden}"


# ---------------------------------------------------------------------------
# The gate's own shape
# ---------------------------------------------------------------------------


def test_the_manifest_records_the_phase_that_introduced_it() -> None:
    assert manifest.PHASE == 17


def test_the_exit_codes_are_the_three_every_other_gate_uses() -> None:
    assert (gate.EXIT_OK, gate.EXIT_GATE_FAILED, gate.EXIT_UNMEASURED) == (0, 1, 3)


def test_the_gate_reads_the_contract_from_the_documented_location() -> None:
    assert plan.CONFIGURATION_FILE == "docs/engineering/runtime-contract.toml"


def test_the_contract_file_is_named_as_a_machine_readable_contract(repo_root: Path) -> None:
    """``docs/engineering/REPOSITORY_LAYOUT.md``: a file that tools parse is not a document.

    Naming it like one invites a reader to edit it as prose.
    """
    name = Path(plan.CONFIGURATION_FILE).name
    assert name.endswith(".toml")
    assert name.islower()
    assert (repo_root / plan.CONFIGURATION_FILE).is_file()
