"""The bootstrap's contract: the exit codes, the entry points, and the leak gate.

Three kinds of assertion live here. The **exit-code contract** is the promise a
launcher branches on, so it is pinned to literal numbers rather than derived from
the enum it is checking. The **entry-point parity** is that ``globin`` and
``python -m globin`` reach one function, asserted rather than assumed. And the
**leak gate** applies the verifier's own scanner to what the product actually
wrote — the second, independent mechanism the adapter's docstring promises.
"""

import ast
import json
import tomllib
from pathlib import Path

import pytest

from globin.adapters import bootstrap as adapters
from globin.adapters.bootstrap import MANIFEST_NAME, build, load, render
from globin.domain.bootstrap import (
    AGGREGATE_CHECK,
    CheckStatus,
    ExitCode,
    RuntimePaths,
    check_identifiers,
    checks,
)
from globin.domain.environment import FINGERPRINT_LENGTH
from globin.runtime.composition import build_bootstrap
from tests.support import REPO_ROOT, running_from_the_project_environment
from tools.quality.evidence.redaction import describe, scan

#: The exit code every failure class produces, written out rather than derived.
#: A test that computed these from the enum would pass whatever the enum said,
#: which is the opposite of pinning a contract. A launcher reads these numbers,
#: and changing one is a breaking change to a published interface.
EXPECTED_CODES: dict[str, int] = {
    "OK": 0,
    "GATE_FAILED": 1,
    "USAGE": 2,
    "UNMEASURED": 3,
    "HOST_UNSUPPORTED": 10,
    "INTERPRETER_MISMATCH": 11,
    "ENVIRONMENT_MISMATCH": 12,
    "DEPENDENCY_UNREADY": 13,
    "CONFIGURATION_INVALID": 14,
    "SECRETS_UNREADY": 15,
    "PATHS_UNUSABLE": 16,
    "INTERNAL": 17,
    "PROJECT_UNIDENTIFIED": 18,
    # Phase 022. Three failure classes the runtime filesystem introduced: a
    # lifecycle record that cannot be read, a machine that already has a
    # coordinator, and a tree that cannot be written to.
    "RUNTIME_STATE_CORRUPT": 19,
    "INSTANCE_ALREADY_ACTIVE": 20,
    "RUNTIME_PERSISTENCE_FAILED": 21,
    # Phase 024's, and the only one here that is not about starting up. A
    # diagnostic that could not be produced is a failure to measure a health
    # state rather than a health state, and `diagnostics snapshot` reports the
    # state itself through 0, 1 and 3 like every other gate.
    "DIAGNOSTICS_FAILED": 22,
    # Phase 025. The one value no command returns: the watchdog ends the process
    # rather than letting it exit, so nothing in `globin.runtime.cli` can produce
    # this and a launcher seeing it knows the run did not choose its own ending.
    "WATCHDOG_STALLED": 23,
    "ENVIRONMENT_INCOMPATIBLE": 24,
    "CREDENTIAL_NOT_ENTITLED": 25,
}

#: Which check answers for which failure class. A launcher that saw code 12 must
#: be able to conclude "wrong environment" without reading English, and this is
#: what makes that true.
EXPECTED_MAPPING: dict[str, str] = {
    "project.root": "PATHS_UNUSABLE",
    "runtime.host": "HOST_UNSUPPORTED",
    "runtime.architecture": "HOST_UNSUPPORTED",
    "python.implementation": "INTERPRETER_MISMATCH",
    "python.version": "INTERPRETER_MISMATCH",
    "python.environment": "ENVIRONMENT_MISMATCH",
    "project.identity": "PROJECT_UNIDENTIFIED",
    "dependency.lock": "DEPENDENCY_UNREADY",
    "config.valid": "CONFIGURATION_INVALID",
    "paths.runtime": "PATHS_UNUSABLE",
    "paths.boundary": "PATHS_UNUSABLE",
    "state.persistence": "RUNTIME_PERSISTENCE_FAILED",
    "state.previous_run": "RUNTIME_STATE_CORRUPT",
    "instance.lock": "INSTANCE_ALREADY_ACTIVE",
    "environment.capability": "ENVIRONMENT_INCOMPATIBLE",
    "secrets.required": "SECRETS_UNREADY",
    "secrets.entitlement": "CREDENTIAL_NOT_ENTITLED",
    "bootstrap.ready": "GATE_FAILED",
}


@pytest.fixture(scope="module")
def manifest_text() -> str:
    """One real bootstrap run's evidence, rendered."""
    outcome = build_bootstrap(REPO_ROOT).run(stop_at_first_refusal=False)
    return render(build(outcome))


# ---------------------------------------------------------------------------
# The exit-code contract
# ---------------------------------------------------------------------------


def test_every_exit_code_has_the_value_it_promised() -> None:
    """Pinned to literals, because this is what a launcher branches on."""
    assert {code.name: int(code) for code in ExitCode} == EXPECTED_CODES


def test_every_check_maps_to_the_failure_class_it_promised() -> None:
    """The same class of failure always produces the same code."""
    assert {spec.identifier: spec.exit_code.name for spec in checks()} == EXPECTED_MAPPING


def test_the_generic_codes_keep_the_meanings_every_gate_gives_them() -> None:
    """A reader who knows one command under `tools/` knows this one."""
    assert int(ExitCode.OK) == 0
    assert int(ExitCode.GATE_FAILED) == 1
    assert int(ExitCode.USAGE) == 2
    assert int(ExitCode.UNMEASURED) == 3


def test_no_two_failure_classes_share_a_number() -> None:
    """Two names for one number would make the contract unreadable from outside."""
    values = [int(code) for code in ExitCode]
    assert len(set(values)) == len(values)


# ---------------------------------------------------------------------------
# The entry points
# ---------------------------------------------------------------------------


def test_one_console_script_is_declared_and_it_delegates() -> None:
    """`globin` and `python -m globin` must reach one function, not two."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    assert pyproject["project"]["scripts"] == {"globin": "globin.runtime.cli:main"}


def test_the_module_guard_holds_no_logic() -> None:
    """A wrapper with a decision in it is a second implementation waiting to differ.

    Checked structurally rather than by counting lines: the module may import, and
    it may raise `SystemExit(main(...))` under the guard. Anything else is logic
    that `globin` — which never runs this file — would not perform.
    """
    tree = ast.parse((REPO_ROOT / "src" / "globin" / "__main__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        assert isinstance(node, ast.Import | ast.ImportFrom | ast.Expr | ast.If), (
            f"__main__.py performs {type(node).__name__}, which the console script never would"
        )


def test_the_console_script_target_exists_and_takes_no_required_argument() -> None:
    """A build backend generates a wrapper calling `main()` with nothing."""
    from globin.runtime.cli import main

    signature = ast.parse(
        (REPO_ROOT / "src" / "globin" / "runtime" / "cli.py").read_text(encoding="utf-8")
    )
    assert callable(main)
    functions = [node for node in signature.body if isinstance(node, ast.FunctionDef)]
    entry = next(node for node in functions if node.name == "main")
    assert all(argument.annotation is not None for argument in entry.args.args)
    assert len(entry.args.defaults) == len(entry.args.args), (
        "main() must be callable with no arguments, because the console script wrapper is"
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_aggregate_is_last_and_is_named_once() -> None:
    """It answers for the others, so it cannot run before them."""
    assert check_identifiers()[-1] == AGGREGATE_CHECK
    assert check_identifiers().count(AGGREGATE_CHECK) == 1


def test_every_identifier_is_a_lower_case_dotted_pair() -> None:
    """Stable and machine-readable, because runbooks and evidence both carry them."""
    for identifier in check_identifiers():
        area, _, subject = identifier.partition(".")
        assert area
        assert subject
        assert identifier.islower()
        assert identifier.replace(".", "").replace("_", "").isalnum()


def test_no_module_under_the_package_carries_a_credential_shaped_name() -> None:
    """`docs/security/SECRET_STORE_CONTRACT.md` §1, checked rather than remembered.

    **Phase 028 narrowed this rule rather than removing it, and the narrowing is
    the point.** The rule was always conditional — "until `README.md` says the
    capability exists, nothing here may be named as though it does" — and this is
    the phase that makes the store exist. So `secret` left the list, `README.md`
    gained a maturity row pointing at the evidence, and the four
    `globin.*.secrets` modules are now legitimate.

    Everything else stays forbidden, because everything else is still absent.
    `credential` in particular remains listed: `ABSENT_CAPABILITIES` in
    `test_documentation_contract.py` still pairs *credential handling* with that
    fragment, Phase 029 owns collection and validation, and a module named for it
    would be claiming a capability nothing has built.

    The two halves are deliberately different words for deliberately different
    things: this phase stores material it is given, and has no way to obtain any.
    """
    forbidden = ("credential", "password", "token", "keyring", "apikey")
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "src" / "globin").rglob("*.py"))
        if any(word in path.stem.lower() for word in forbidden)
    ]
    assert not offenders


# ---------------------------------------------------------------------------
# The leak gate
# ---------------------------------------------------------------------------


def test_the_evidence_carries_nothing_the_verifier_recognises(manifest_text: str) -> None:
    """The second, independent mechanism.

    The product redacts at the point a record is built; this applies the scanner
    `tools/quality/evidence` uses on published artefacts. Two mechanisms, neither
    importing the other, which is the arrangement `redaction.py` argues for.
    """
    findings = scan(MANIFEST_NAME, manifest_text)
    assert not findings, describe(findings)


@pytest.mark.parametrize(
    "sentinel",
    [
        pytest.param("api_key", id="api-key"),
        pytest.param("password", id="password"),
        pytest.param("secret", id="secret"),
        pytest.param("token", id="token"),
        pytest.param("private_key", id="private-key"),
    ],
)
def test_a_sentinel_value_never_reaches_the_evidence(sentinel: str) -> None:
    """Injected deliberately, and asserted absent by its own text.

    Not by looking for `[redacted]`: a marker appearing proves something was
    replaced, and what has to be proved is that the original is gone.
    """
    from globin.domain.bootstrap import BootstrapOutcome, BootstrapReport, CheckOutcome

    needle = "GLOBIN-SENTINEL-c3f1a9-never-published"
    outcome = BootstrapOutcome(
        report=BootstrapReport(
            outcomes=(
                CheckOutcome(
                    identifier="project.root",
                    status=CheckStatus.PASS,
                    summary="found",
                ),
            )
        ),
        observed={"host": {sentinel: needle}},
    )
    rendered = render(build(outcome))
    assert needle not in rendered
    assert not scan(MANIFEST_NAME, rendered)


def test_the_evidence_carries_no_path_from_outside_the_project(manifest_text: str) -> None:
    """Structural rather than pattern-based: the recorded form cannot be absolute."""
    document = load(manifest_text)
    observed = document["observed"]
    assert isinstance(observed, dict)
    rendered = str(observed)
    for fragment in ("C:\\", "C:/", "/home/", "/Users/", "AppData"):
        assert fragment not in rendered, fragment


def test_the_evidence_is_written_only_inside_the_ignored_run_directory() -> None:
    """`.globin/` is git-ignored, and nothing here writes anywhere else."""
    assert RuntimePaths().evidence.startswith(".globin/")
    source = (REPO_ROOT / "src" / "globin" / "adapters" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "write_text" in source
    assert source.count("write_text") == 1, "one write, and it is the manifest"


def test_the_gate_and_the_diagnostic_describe_one_host() -> None:
    """Same pipeline, same judgements — only the stopping rule differs."""
    gate = build_bootstrap(REPO_ROOT).run(stop_at_first_refusal=True)
    doctor = build_bootstrap(REPO_ROOT).run(stop_at_first_refusal=False)
    if gate.report.ready:
        assert gate.report == doctor.report


@pytest.mark.skipif(
    not running_from_the_project_environment(),
    reason="this asserts about the project's own .venv, which this interpreter is not",
)
def test_this_repository_bootstraps(manifest_text: str) -> None:
    """The phase's own subject: if this fails, the environment has drifted.

    Read from the manifest rather than from the outcome, so that what is asserted
    is what would be published rather than what was computed.
    """
    document = load(manifest_text)
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["ready"] is True, verdict["reasons"]
    assert verdict["exit_code"] == int(ExitCode.OK)


def test_the_adapter_does_not_import_the_verification_tooling() -> None:
    """A verifier does not import the package it verifies, and the reverse holds."""
    source = Path(adapters.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(name.startswith("tools") for name in imported)


def test_the_manifest_carries_the_environment_snapshot_and_its_fingerprint(
    manifest_text: str,
) -> None:
    """Phase 028's evidence, in the document every other observation already reaches.

    A separate `.globin/environment/` manifest was not built, deliberately: the
    capability snapshot is a fact *about this start-up*, and the bootstrap
    manifest is where this repository already records those. A second artefact
    would need its own schema, its own digest and its own reader for a section
    that fits in the one that exists.

    The fingerprint is what makes the section worth publishing — two runs on an
    unchanged host produce the same value, so a reader comparing two manifests
    learns whether the environment moved without reading five checks.
    """
    observed = json.loads(manifest_text)["observed"]
    environment = observed["environment"]
    assert environment is not None
    assert environment["compatibility"] in {"ready", "degraded", "blocked"}
    assert len(environment["fingerprint"]) == FINGERPRINT_LENGTH
    assert environment["architecture"].keys() == {"process", "native", "emulation"}
    assert all(set(entry) == {"name", "present"} for entry in environment["toolchain"])


def test_the_environment_section_publishes_no_path(manifest_text: str) -> None:
    """The privacy property, asserted on real published bytes rather than a type.

    `test_the_snapshot_has_no_field_that_could_hold_a_path` asserts it
    structurally; this asserts it about what a run actually wrote, which is the
    thing an operator would send to somebody.
    """
    section = json.dumps(json.loads(manifest_text)["observed"]["environment"])
    assert ":\\" not in section
    assert ":/" not in section
    assert "/Users/" not in section
