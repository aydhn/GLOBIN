"""Whether either provider library has spread beyond its one adapter.

`test_probe_discipline.py` states this rule for `psutil` and this states it for the
two libraries Phase 026 adopted. The rule is the same and the reason is the same:
the CI `quality` job installs neither, so the absence is handled in exactly one
place and every layer above is written as if the library were present.

**Why these are not in `stack-contract.toml`.** That contract's libraries feed
`test_stack_discipline.py`'s forbidden-import set, so listing an *adopted* library
there would forbid the adapter that exists to import it. The contract cannot
currently express "adopted **and** imported" — psutil is deliberately absent from
it for the same reason — so the rule lives here instead. Closing that gap by adding
an `adoption` field to the stack schema is named in ADR-0068 as the fix, and
deliberately left to whichever phase wants it.

Like its neighbours this is a proxy rather than a proof: an alias or an
`importlib.import_module` call defeats it. It catches the way a boundary is
realistically eroded, and it has its own failing cases in both directions below.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

GUARDED: Final[dict[str, str]] = {
    "opentelemetry": "globin.adapters.telemetry_otel",
    "prometheus_client": "globin.adapters.telemetry_prometheus",
}
"""Each guarded distribution's import name, and the one module that may name it."""

FORBIDDEN_LISTENERS: Final[tuple[str, ...]] = (
    "start_wsgi_server",
    "make_wsgi_app",
    "socketserver",
    "http.server",
)
"""Ways to open a socket that GLOBIN does not use.

`start_http_server` is deliberately absent from this list: it is used, once, in
`telemetry_prometheus.start_loopback_listener`, with `127.0.0.1` passed as a
literal. What is forbidden is every *other* route, because each would reintroduce
the `0.0.0.0` default this repository refuses to leave to memory.
"""


def _imports(tree: ast.AST, guarded: str) -> list[str]:
    """Every spelling of one guarded module in a parsed file.

    Args:
        tree: The parsed source.
        guarded: The top-level module name.

    Returns:
        The spellings found.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(a.name for a in node.names if a.name.split(".")[0] == guarded)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == guarded
        ):
            found.append(node.module)
    return found


def _modules(repo_root: Path) -> list[Path]:
    """Every module in the package, sorted so two runs report identically.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


@pytest.mark.parametrize("guarded", sorted(GUARDED))
def test_the_guarded_library_is_one_the_repository_declares(guarded: str) -> None:
    """Guard the guard: a rule about a library nobody depends on is not a rule."""
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = project.read_text(encoding="utf-8")
    distribution = guarded.replace("_", "-")
    assert distribution in text, f"{distribution} is guarded but not declared"


@pytest.mark.parametrize("guarded", sorted(GUARDED))
def test_only_one_adapter_names_each_library(repo_root: Path, guarded: str) -> None:
    """One module owns the absence, so every layer above ignores it.

    The CI `quality` job installs neither library, so this is not hypothetical:
    without a single owner, an import at module scope would make the package
    unimportable on the machine that runs the whole suite.
    """
    permitted = GUARDED[guarded]
    offenders = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE): found
        for path in _modules(repo_root)
        if (found := _imports(ast.parse(path.read_text(encoding="utf-8")), guarded))
        and module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE) != permitted
    }
    assert not offenders, f"{guarded} is imported outside {permitted}: {offenders}"


@pytest.mark.parametrize("guarded", sorted(GUARDED))
def test_the_permitted_adapter_does_name_it(repo_root: Path, guarded: str) -> None:
    """The other direction, so the check above is not vacuously true."""
    relative = GUARDED[guarded].removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/")
    path = repo_root / PACKAGE_RELATIVE_PATH / f"{relative}.py"
    assert _imports(ast.parse(path.read_text(encoding="utf-8")), guarded)


def test_no_module_opens_a_listener_by_another_route(repo_root: Path) -> None:
    """One function may bind a socket, and it binds loopback as a literal.

    `prometheus_client.start_http_server` defaults its address to `0.0.0.0` —
    every interface rather than this machine. GLOBIN passes `127.0.0.1`
    explicitly and exposes no address setting, so what has to be prevented is a
    *second* route appearing that does not carry that argument.
    """
    offenders: dict[str, list[str]] = {}
    for path in _modules(repo_root):
        text = path.read_text(encoding="utf-8")
        found = [name for name in FORBIDDEN_LISTENERS if name in text]
        if found:
            offenders[module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)] = found
    assert not offenders, f"a second way to open a listener appeared: {offenders}"


def test_the_one_listener_binds_loopback_as_a_literal(repo_root: Path) -> None:
    """The security posture of the whole feature, asserted rather than reviewed.

    An address that came from configuration would be one typo away from publishing
    this process's internals to the network, and there is no operational reason
    GLOBIN needs one.
    """
    path = repo_root / PACKAGE_RELATIVE_PATH / "adapters" / "telemetry_prometheus.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "127.0.0.1"
    ]
    assert literals, "the loopback address is not a literal in the module that binds"
    # A suppression is the honest form here: the wildcard address is the thing
    # being forbidden, so a test proving it absent has to be able to name it.
    # Spelling it obscurely to dodge the rule would make the test unreadable for
    # no gain -- the same trade the clock contract's operation matrix records.
    wildcard = "0.0.0.0"  # noqa: S104 -- named so its absence can be asserted
    assert wildcard not in path.read_text(encoding="utf-8").replace(f"`{wildcard}`", ""), (
        "the wildcard address appears outside the comment explaining why it is refused"
    )


@pytest.mark.parametrize(
    ("source", "caught"),
    [
        pytest.param("import opentelemetry\n", True, id="plain"),
        pytest.param("import opentelemetry as otel\n", True, id="aliased"),
        pytest.param("from opentelemetry import metrics\n", True, id="from-import"),
        pytest.param("from opentelemetry.sdk import x\n", True, id="submodule"),
        pytest.param("def f():\n    import opentelemetry\n", True, id="inside-a-function"),
        pytest.param("import opentelemetryish\n", False, id="prefix-only"),
        pytest.param("from . import telemetry\n", False, id="relative"),
        pytest.param("opentelemetry = 1\n", False, id="a-local-of-the-same-name"),
    ],
)
def test_the_detector_notices_a_reach_and_spares_everything_else(source: str, caught: bool) -> None:
    """Guard the guard, in both directions.

    The in-function form is caught on purpose: that is exactly how
    `opentelemetry_bridge` reaches the library, so a checker reading only the
    header would pass a module that had moved its import to the top.
    """
    assert bool(_imports(ast.parse(source), "opentelemetry")) is caught
