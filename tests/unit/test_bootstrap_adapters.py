"""Reading a real machine, a real tree, and turning both into recordable facts.

:mod:`globin.adapters.bootstrap` is the only part of the bootstrap that touches
the world, so this is where a temporary tree is built and where the interpreter
running the suite is asked about itself. Every judgement it feeds is tested from
literals elsewhere; what is tested here is the reading.
"""

import sys
from pathlib import Path

import pytest

from globin.adapters.bootstrap import (
    DeclaredDependencyProbe,
    FilesystemProjectProbe,
    ProjectRuntimeTree,
    StoreBackedSecrets,
    SystemHostProbe,
    TomlRuntimeBaselineSource,
    distribution_name,
    find_project_root,
    installed_distributions,
    normalise,
    parse_baseline,
    reason_for,
    reasons,
    record,
)
from globin.adapters.secrets import UnavailableSecretStore
from globin.domain.bootstrap import (
    CREATED_PATHS,
    MAX_ROOT_SEARCH_DEPTH,
    PathLocation,
    RuntimePaths,
    check_identifiers,
)
from globin.domain.identifiers import environment_id
from globin.domain.secrets import SecretKind, SecretReference
from globin.errors import ConfigurationError
from tests.support import running_from_the_project_environment

CONTRACT = """\
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

PROJECT = """\
[project]
name = "globin"
dependencies = ["numpy>=2.5.2", "pandas>=3.0.5"]
"""


def tree(root: Path, *, project: str = PROJECT, lock: bool = True) -> Path:
    """A checkout with the files the bootstrap reads."""
    (root / "pyproject.toml").write_text(project, encoding="utf-8", newline="\n")
    contract = root / "docs" / "engineering"
    contract.mkdir(parents=True, exist_ok=True)
    (contract / "runtime-contract.toml").write_text(CONTRACT, encoding="utf-8", newline="\n")
    if lock:
        (root / "pylock.toml").write_text('lock-version = "1.0"\n', encoding="utf-8", newline="\n")
    return root


# ---------------------------------------------------------------------------
# Recording a path
# ---------------------------------------------------------------------------


def test_a_path_inside_the_root_is_recorded_relative_to_it(tmp_path: Path) -> None:
    """Meaningful to a reader, and identical on every machine."""
    recorded = record(tmp_path / "src" / "globin", root=tmp_path)
    assert recorded.location is PathLocation.REPOSITORY
    assert recorded.path == "src/globin"


def test_the_root_itself_is_recorded_as_a_dot(tmp_path: Path) -> None:
    """Rather than as an empty string, which is not a path."""
    assert record(tmp_path, root=tmp_path).path == "."


def test_a_path_outside_the_root_is_recorded_as_a_fingerprint(tmp_path: Path) -> None:
    """The privacy invariant, at the moment the path is observed."""
    recorded = record(Path("C:/Users/Someone/Python"), root=tmp_path)
    assert recorded.location is PathLocation.OUTSIDE
    assert recorded.path is None


def test_with_no_root_nothing_can_be_inside_one(tmp_path: Path) -> None:
    """Which is true, and is why it is not an error."""
    assert record(tmp_path, root=None).location is PathLocation.OUTSIDE


def test_no_path_at_all_is_recorded_as_absent() -> None:
    """The third outcome, and there is no fourth."""
    assert record(None, root=None).location is PathLocation.ABSENT


# ---------------------------------------------------------------------------
# Finding the project
# ---------------------------------------------------------------------------


def test_the_root_is_found_from_the_root_itself(tmp_path: Path) -> None:
    """The ordinary case."""
    assert find_project_root(tree(tmp_path)) == tmp_path


def test_the_root_is_found_from_a_nested_directory(tmp_path: Path) -> None:
    """This is the working-directory independence the phase is for."""
    tree(tmp_path)
    nested = tmp_path / "src" / "globin" / "domain"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path


def test_a_tree_with_no_project_file_yields_no_root(tmp_path: Path) -> None:
    """Refused rather than guessed at."""
    assert find_project_root(tmp_path) is None


def test_a_project_file_naming_another_project_is_not_this_root(tmp_path: Path) -> None:
    """A checkout nested inside an unrelated repository must not borrow its parent."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "other"\n', encoding="utf-8")
    assert find_project_root(tmp_path) is None


def test_a_malformed_project_file_does_not_stop_the_search(tmp_path: Path) -> None:
    """A directory the search walks through is not one it owns."""
    (tmp_path / "pyproject.toml").write_text("this is not toml [[[", encoding="utf-8")
    inner = tmp_path / "inner"
    inner.mkdir()
    tree(inner)
    assert find_project_root(inner) == inner


def test_the_search_is_bounded(tmp_path: Path) -> None:
    """An unbounded walk finds a project file eventually, and the wrong one.

    Single-character directory names, because Windows still enforces MAX_PATH for
    `mkdir` here and a descriptive name twenty levels deep exceeds it — which
    would make this test fail for a reason that has nothing to do with the bound.
    """
    tree(tmp_path)
    deep = tmp_path.joinpath(*(f"{index:x}" for index in range(MAX_ROOT_SEARCH_DEPTH + 4)))
    deep.mkdir(parents=True)
    assert find_project_root(deep) is None


def test_the_search_reaches_exactly_as_deep_as_it_declares(tmp_path: Path) -> None:
    """The boundary itself, so the constant is a rule rather than a suggestion."""
    tree(tmp_path)
    reachable = tmp_path.joinpath(*(f"{index:x}" for index in range(MAX_ROOT_SEARCH_DEPTH)))
    reachable.mkdir(parents=True)
    assert find_project_root(reachable) == tmp_path


# ---------------------------------------------------------------------------
# The declared baseline
# ---------------------------------------------------------------------------


def test_the_contract_parses_into_what_it_says(tmp_path: Path) -> None:
    """The values are Phase 017's; reading them is this module's."""
    baseline = TomlRuntimeBaselineSource(
        path=tree(tmp_path) / "docs/engineering/runtime-contract.toml"
    ).baseline()
    assert baseline.system == "Windows"
    assert baseline.minor_line == "3.14"
    assert baseline.minimum_patch == "3.14.5"
    assert baseline.pointer_bits == 64
    assert baseline.free_threaded is False
    assert baseline.environment_directory == ".venv"


def test_a_contract_that_is_not_there_is_a_configuration_error(tmp_path: Path) -> None:
    """A bootstrap that cannot read what it must enforce has measured nothing."""
    with pytest.raises(ConfigurationError, match="could not be read"):
        TomlRuntimeBaselineSource(path=tmp_path / "absent.toml").baseline()


def test_a_contract_that_is_not_toml_is_a_configuration_error(tmp_path: Path) -> None:
    """Named as malformed rather than as absent, which is a different fix."""
    path = tmp_path / "runtime-contract.toml"
    path.write_text("[interpreter\nbroken", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="not valid TOML"):
        TomlRuntimeBaselineSource(path=path).baseline()


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({}, id="no-tables"),
        pytest.param({"interpreter": {}, "host": {}, "environment": {}}, id="empty-tables"),
        pytest.param(
            {"interpreter": "text", "host": {}, "environment": {}}, id="interpreter-not-a-table"
        ),
    ],
)
def test_a_contract_with_a_hole_in_it_is_refused(document: dict[str, object]) -> None:
    """Nothing is defaulted: a contract with a hole has not declared the thing."""
    with pytest.raises(ConfigurationError):
        parse_baseline(document)


def test_a_boolean_is_not_an_integer_here() -> None:
    """Python makes `True` an integer, and `pointer_bits = true` is not 64."""
    document = {
        "interpreter": {
            "implementation": "CPython",
            "minor_line": "3.14",
            "minimum_patch": "3.14.5",
            "architecture": "AMD64",
            "pointer_bits": True,
            "free_threaded": False,
            "allow_prerelease": False,
        },
        "host": {"system": "Windows", "minimum_release": "10"},
        "environment": {"directory": ".venv"},
    }
    with pytest.raises(ConfigurationError, match="integer"):
        parse_baseline(document)


def test_a_string_where_a_boolean_belongs_is_refused() -> None:
    """`free_threaded = "no"` is not false."""
    document = {
        "interpreter": {
            "implementation": "CPython",
            "minor_line": "3.14",
            "minimum_patch": "3.14.5",
            "architecture": "AMD64",
            "pointer_bits": 64,
            "free_threaded": "no",
            "allow_prerelease": False,
        },
        "host": {"system": "Windows", "minimum_release": "10"},
        "environment": {"directory": ".venv"},
    }
    with pytest.raises(ConfigurationError, match="boolean"):
        parse_baseline(document)


# ---------------------------------------------------------------------------
# The host
# ---------------------------------------------------------------------------


def test_the_host_probe_reads_this_machine(tmp_path: Path) -> None:
    """Whatever this machine is, it says so rather than defaulting."""
    facts = SystemHostProbe(root=tmp_path).host()
    assert facts.system
    assert facts.pointer_bits in {32, 64}


def test_the_interpreter_probe_reads_this_interpreter(tmp_path: Path) -> None:
    """And records the three paths rather than spelling them out."""
    facts = SystemHostProbe(root=tmp_path).interpreter()
    assert facts.implementation == sys.implementation.name
    assert facts.version.startswith(f"{sys.version_info.major}.{sys.version_info.minor}.")
    assert facts.in_virtual_environment == (sys.prefix != sys.base_prefix)
    assert facts.executable.path is None or not facts.executable.path.startswith("/")


@pytest.mark.skipif(
    not running_from_the_project_environment(),
    reason="this asserts about the project's own .venv, which this interpreter is not",
)
def test_the_suite_runs_inside_a_virtual_environment_and_the_probe_sees_it() -> None:
    """A guard on the phase's own premise: the gates run from `.venv`."""
    facts = SystemHostProbe(root=Path(sys.prefix).parent).interpreter()
    assert facts.prefix.location is PathLocation.REPOSITORY


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not running_from_the_project_environment(),
    reason="this asserts about the project's own .venv, which this interpreter is not",
)
def test_an_installed_distribution_is_read_from_its_metadata(tmp_path: Path) -> None:
    """GLOBIN is installed into `.venv` since Phase 021, so this is the live case."""
    identity = FilesystemProjectProbe(location=tmp_path, started_from=tmp_path).identity()
    assert identity is not None
    assert identity.name == "globin"
    assert identity.source == "metadata"


def test_the_root_of_a_located_project_is_recorded_as_a_dot(tmp_path: Path) -> None:
    """The root is the root, whatever it is called on this machine."""
    probe = FilesystemProjectProbe(location=tmp_path, started_from=tmp_path)
    assert probe.root().path == "."


def test_a_project_that_was_not_located_records_no_root(tmp_path: Path) -> None:
    """And its origin does not name the working directory either."""
    probe = FilesystemProjectProbe(location=None, started_from=tmp_path)
    assert probe.root().location is PathLocation.ABSENT
    assert tmp_path.name not in probe.origin()


def test_an_origin_inside_the_project_names_the_relative_directory(tmp_path: Path) -> None:
    """Useful, and still not an absolute path."""
    nested = tmp_path / "src"
    nested.mkdir()
    probe = FilesystemProjectProbe(location=tmp_path, started_from=nested)
    assert "'src'" in probe.origin()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        pytest.param("numpy", "numpy", id="bare"),
        pytest.param("numpy>=2.5.2", "numpy", id="lower-bound"),
        pytest.param("pandas[performance]>=3.0", "pandas", id="extras"),
        pytest.param("pandas >= 3.0 ; python_version >= '3.12'", "pandas", id="marker"),
        pytest.param("Typing_Extensions==4.0", "typing-extensions", id="normalised"),
        pytest.param("ruff @ https://example.invalid/ruff.whl", "ruff", id="direct-reference"),
    ],
)
def test_a_requirement_string_yields_its_distribution(requirement: str, expected: str) -> None:
    """Deliberately shallow: GLOBIN declares these and this reads them back."""
    assert distribution_name(requirement) == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        pytest.param("PyYAML", "pyyaml", id="case"),
        pytest.param("typing_extensions", "typing-extensions", id="underscore"),
        pytest.param("zope.interface", "zope-interface", id="dot"),
        pytest.param("a--_..b", "a-b", id="runs-collapse"),
    ],
)
def test_a_distribution_name_is_normalised_as_pep_503_says(written: str, expected: str) -> None:
    """Written out rather than imported: ADR-0003 makes four lines cheaper."""
    assert normalise(written) == expected


def test_what_is_declared_locked_and_installed_is_reported(tmp_path: Path) -> None:
    """The control, with the environment substituted rather than built."""
    tree(tmp_path)
    probe = DeclaredDependencyProbe(
        project_file=tmp_path / "pyproject.toml",
        lock_file=tmp_path / "pylock.toml",
        installed=lambda: {"numpy": "2.5.2", "pandas": "3.0.5"},
    )
    readiness = probe.readiness()
    assert readiness.declared == ("numpy", "pandas")
    assert readiness.locked is True
    assert readiness.missing == ()


def test_a_declared_distribution_that_is_absent_is_reported_as_missing(tmp_path: Path) -> None:
    """Read locally: start-up must work without a network."""
    tree(tmp_path)
    probe = DeclaredDependencyProbe(
        project_file=tmp_path / "pyproject.toml",
        lock_file=tmp_path / "pylock.toml",
        installed=lambda: {"numpy": "2.5.2"},
    )
    assert probe.readiness().missing == ("pandas",)


def test_a_tree_with_no_runtime_lock_reports_that(tmp_path: Path) -> None:
    """Which the judgement turns into a refusal, and this only observes."""
    tree(tmp_path, lock=False)
    probe = DeclaredDependencyProbe(
        project_file=tmp_path / "pyproject.toml",
        lock_file=tmp_path / "pylock.toml",
        installed=lambda: {"numpy": "2.5.2", "pandas": "3.0.5"},
    )
    assert probe.readiness().locked is False


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("", id="empty"),
        pytest.param("not toml [[[", id="malformed"),
        pytest.param("[project]\nname = 'globin'\n", id="no-dependencies-key"),
        pytest.param("[project]\ndependencies = 'numpy'\n", id="dependencies-not-a-list"),
        pytest.param("[tool.other]\nx = 1\n", id="no-project-table"),
    ],
)
def test_a_project_file_this_reader_cannot_use_declares_nothing(tmp_path: Path, body: str) -> None:
    """`project.root` is what refuses first, and it already has."""
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    probe = DeclaredDependencyProbe(
        project_file=tmp_path / "pyproject.toml",
        lock_file=tmp_path / "pylock.toml",
        installed=dict,
    )
    assert probe.readiness().declared == ()


@pytest.mark.skipif(
    not running_from_the_project_environment(),
    reason="this asserts about the project's own .venv, which this interpreter is not",
)
def test_the_installed_set_is_read_through_the_standard_library() -> None:
    """No child process, so it cannot become a network call by accident."""
    found = installed_distributions()
    assert "globin" in found
    assert all(name == normalise(name) for name in found)


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def test_starting_globin_requires_no_secret_because_it_requires_none() -> None:
    """The honest implementation of a fact, not a stub for a missing store.

    Phase 028 replaced `NoSecretsRequired` with a probe backed by the real
    store, and the behaviour on an empty required set is deliberately identical:
    a vacuous pass. This asserts that equivalence, because the whole argument for
    the substitution was that nothing observable changed on a host holding no
    credentials.

    The store is the unavailable one, which is what CI gets, so this also pins
    that an absent backend does not turn an empty requirement into a failure.
    """
    readiness = StoreBackedSecrets(store=UnavailableSecretStore()).readiness()
    assert readiness.required == ()
    assert readiness.unavailable == ()


def test_a_required_reference_that_does_not_resolve_is_reported_not_raised() -> None:
    """The readiness probe reports; only `require` refuses.

    A start-up check that raised would make an absent credential indistinguishable
    from a broken bootstrap, and `secrets_outcome` could never produce its
    "N required reference(s) could not be resolved" summary.
    """
    reference = SecretReference(
        environment=environment_id("paper"),
        kind=SecretKind.API_KEY,
        name="absent_here",
    )
    readiness = StoreBackedSecrets(
        store=UnavailableSecretStore(), required=(reference,)
    ).readiness()
    assert readiness.required == ("absent_here",)
    assert readiness.unavailable == ("absent_here",)


# ---------------------------------------------------------------------------
# The runtime tree
# ---------------------------------------------------------------------------


def test_only_the_allowlisted_roots_are_created(tmp_path: Path) -> None:
    """A declared root is a reservation, not a claim that anything writes there."""
    paths = RuntimePaths()
    assert ProjectRuntimeTree(root=tmp_path).prepare(paths) == ()
    for name, relative in paths.declared().items():
        created = (tmp_path / relative).is_dir()
        assert created is (name in CREATED_PATHS), f"{name} was {'' if created else 'not '}created"


def test_preparing_twice_changes_nothing(tmp_path: Path) -> None:
    """Idempotent, so a doctor run is safe to repeat."""
    tree_maker = ProjectRuntimeTree(root=tmp_path)
    assert tree_maker.prepare(RuntimePaths()) == ()
    assert tree_maker.prepare(RuntimePaths()) == ()


def test_a_declared_root_that_is_a_file_is_reported(tmp_path: Path) -> None:
    """Rather than raising out of a check that is meant to report."""
    (tmp_path / ".globin").write_text("not a directory", encoding="utf-8")
    problems = ProjectRuntimeTree(root=tmp_path).prepare(RuntimePaths())
    assert any("is not a directory" in problem for problem in problems)


def test_a_declared_root_that_escapes_the_project_is_refused(tmp_path: Path) -> None:
    """Nothing is created outside the project, ever."""
    paths = RuntimePaths(evidence="../outside/evidence")
    problems = ProjectRuntimeTree(root=tmp_path).prepare(paths)
    assert any("resolves outside the project" in problem for problem in problems)
    assert not (tmp_path.parent / "outside").exists()


def test_a_root_that_cannot_be_created_is_reported_rather_than_raised(tmp_path: Path) -> None:
    """An unwritable location is a finding, not a traceback."""
    (tmp_path / ".globin").write_text("a file where a directory belongs", encoding="utf-8")
    paths = RuntimePaths(artifacts=".globin/nested", evidence=".globin/nested/bootstrap")
    problems = ProjectRuntimeTree(root=tmp_path).prepare(paths)
    assert problems


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------


def test_a_reason_code_is_derived_from_its_check() -> None:
    """Derived rather than declared, so a new check cannot arrive without one."""
    assert reason_for("python.environment") == "BOOTSTRAP_PYTHON_ENVIRONMENT"


def test_every_check_contributes_exactly_one_reason() -> None:
    """Complete by construction, which a hand-written table would not be."""
    derived = {reason_for(identifier) for identifier in check_identifiers()}
    assert derived <= reasons()
    assert len(reasons()) == len(derived) + 1


def test_every_reason_is_an_upper_case_bootstrap_identifier() -> None:
    """So that a reader can tell which gate produced one from the code alone."""
    for reason in reasons():
        assert reason.startswith("BOOTSTRAP_")
        assert reason.isupper()
        assert reason.replace("_", "").isalnum()
