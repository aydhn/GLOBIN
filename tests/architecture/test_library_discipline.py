"""Whether either provider library has spread beyond its one adapter, and who may bind.

`test_probe_discipline.py` states this rule for `psutil` and this states it for the
two libraries Phase 026 adopted. The rule is the same and the reason is the same:
the CI `quality` job installs neither, so the absence is handled in exactly one
place and every layer above is written as if the library were present.

**The listener half of this file changed shape in Phase 027, and did not relax.**
Phase 026 forbade `socketserver` and `http.server` outright and permitted one
library function; GLOBIN had no server of its own, so "which module may bind" was
implied by which library call was exempt. It has one now, so the rule says what it
always meant: exactly one module may reach a socket, it is named, and the address it
binds comes from a type that has already refused everything but loopback. Every
library route is forbidden, including the one that used to be permitted. ADR-0072
records the exchange.

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
import ipaddress
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
    "start_http_server",
    "start_wsgi_server",
    "make_wsgi_app",
)
"""Ways to open a socket that GLOBIN does not use, anywhere, including the one
module that is allowed to open one.

All three are `prometheus_client`'s, and all three default their bind address to
every interface rather than to this machine. Phase 026 permitted `start_http_server`
in one place with the loopback address passed as a literal; Phase 027 retired that
listener — it served a registry GLOBIN never populated and had no production caller —
so the exception went with it. What replaced it opens its socket through the standard
library and binds a *validated* address, which is why the exception is no longer
needed rather than merely no longer used.
"""

LISTENER_MODULE: Final[str] = "globin.adapters.diagnostics_http"
"""The one module in GLOBIN that may open a listening socket."""

LISTENER_IMPORTS: Final[tuple[str, ...]] = ("socketserver", "http.server", "socket")
"""Standard-library routes to a socket, permitted only in :data:`LISTENER_MODULE`.

Phase 026 forbade the first two outright, when GLOBIN had no server of its own and
the only sanctioned listener came from a library. Phase 027 has one, so the rule
changed shape rather than relaxing: the count of modules that can open a socket is
still exactly one, and it is now named here instead of being implied by which
library function was exempt.

`socket` joins them because it is the route the other two are built on: a module
that could not import `socketserver` but could import `socket` would be one
`bind()` away from the thing this rule exists to prevent.
"""

WILDCARD_ADDRESS_TOKENS: Final[tuple[str, ...]] = (
    "0.0.0.0",  # noqa: S104 -- named so its absence can be asserted
    "[::]",
)
"""Spellings of "every interface" that must appear nowhere under `src/globin`.

Not a validation mechanism — `LoopbackAddress` is, and it refuses spellings no list
would enumerate. This is the *absence* check that sits beside it: the validator can
only refuse an address that reaches it, and a wildcard written directly into a
`bind()` call would never reach one.

The suppression is the honest form: the thing being forbidden is a literal, so a
test proving it absent has to be able to write it. Spelling it obscurely to dodge
the linter would make the test unreadable for no gain — the same trade the clock
contract's operation matrix records.
"""


def _identifiers(tree: ast.AST) -> set[str]:
    """Every name a module actually uses, ignoring prose.

    Args:
        tree: The parsed source.

    Returns:
        Bare names, attribute names, and imported or aliased names.

    **AST rather than a substring scan, and that is a correction rather than a
    preference.** Phase 026 checked the raw text, which meant a docstring *explaining*
    why a function is forbidden violated the rule that forbade it — the same file had
    to write a wildcard address inside backticks and strip them again to say what it
    refused. Prose that names a rule is the opposite of breaking it, so what is
    checked is what the module does.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name.split(".")[-1])
            if node.asname:
                found.add(node.asname)
    return found


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


def test_no_module_reaches_a_listener_by_a_librarys_route(repo_root: Path) -> None:
    """Every `prometheus_client` route to a socket is forbidden, without exception.

    All three default their bind address to every interface. GLOBIN opens its one
    socket through the standard library instead, binding an address a value type has
    already refused unless it is loopback — so there is no longer a route that needs
    an argument passed correctly, which is what the Phase 026 exception depended on.
    """
    offenders: dict[str, list[str]] = {}
    for path in _modules(repo_root):
        used = _identifiers(ast.parse(path.read_text(encoding="utf-8")))
        found = sorted(used.intersection(FORBIDDEN_LISTENERS))
        if found:
            offenders[module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)] = found
    assert not offenders, f"a library route to a listener appeared: {offenders}"


@pytest.mark.parametrize(
    ("source", "caught"),
    [
        pytest.param("from prometheus_client import start_http_server\n", True, id="from-import"),
        pytest.param(
            "import prometheus_client as p\np.start_http_server(1)\n", True, id="attribute"
        ),
        pytest.param("start_http_server(1)\n", True, id="bare-call"),
        pytest.param("from prometheus_client import start_http_server as s\n", True, id="aliased"),
        pytest.param('"""start_http_server is forbidden."""\n', False, id="docstring"),
        pytest.param("# start_http_server is forbidden\n", False, id="comment"),
        pytest.param('x = "start_http_server"\n', False, id="a-string-naming-it"),
    ],
)
def test_the_listener_detector_reads_code_and_not_prose(source: str, caught: bool) -> None:
    """Guard the guard, in both directions.

    The three false cases are the point. A rule whose *explanation* violates it
    teaches people to write around the checker rather than to obey the rule, and this
    file's own docstring has to be able to name what it forbids.
    """
    used = _identifiers(ast.parse(source))
    assert bool(used.intersection(FORBIDDEN_LISTENERS)) is caught


def test_only_one_module_can_reach_a_socket_at_all(repo_root: Path) -> None:
    """The count of modules able to open a socket is one, and it is named.

    A proxy rather than a proof, like its neighbours: a module handed an open socket
    would defeat it. What it catches is the realistic erosion — somebody importing
    `socket` in a second place because it was convenient there too.
    """
    offenders: dict[str, list[str]] = {}
    for path in _modules(repo_root):
        name = module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)
        if name == LISTENER_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = sorted(
            {spelling for guard in LISTENER_IMPORTS for spelling in _imports(tree, guard)}
        )
        if found:
            offenders[name] = found
    assert not offenders, f"a socket became reachable outside {LISTENER_MODULE}: {offenders}"


def test_the_module_that_binds_does_import_what_it_needs(repo_root: Path) -> None:
    """The other direction, so the check above is not vacuously true."""
    relative = LISTENER_MODULE.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/")
    path = repo_root / PACKAGE_RELATIVE_PATH / f"{relative}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {spelling for guard in LISTENER_IMPORTS for spelling in _imports(tree, guard)}
    assert found, f"{LISTENER_MODULE} reaches no socket, so the rule guards nothing"


def test_the_binding_module_contains_no_address_literal_at_all(repo_root: Path) -> None:
    """The security posture of the whole feature, asserted rather than reviewed.

    Phase 026 asserted that `127.0.0.1` appeared as a literal in the binding module,
    because a literal *was* the mechanism. The mechanism is now a type, so the
    assertion inverts: what has to be true is that this module contains **no address
    literal of any kind**, loopback included.

    That is strictly stronger than checking for a wildcard. An address the module
    cannot spell is an address it cannot bind, so the only one reachable is the one it
    was handed — and the only way to hand it one is
    :class:`~globin.domain.diagnostics_http.LoopbackAddress`, which has already
    refused everything that is not loopback. A future edit hardcoding *any* address
    fails here, whether or not somebody would have recognised it as dangerous.
    """
    relative = LISTENER_MODULE.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/")
    path = repo_root / PACKAGE_RELATIVE_PATH / f"{relative}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    literals = sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _is_address(node.value)
        }
    )
    assert not literals, (
        f"{LISTENER_MODULE} spells an address rather than being handed one: {literals}"
    )


def _is_address(text: str) -> bool:
    """Whether a string is an IP address.

    Args:
        text: The candidate.

    Returns:
        Whether :mod:`ipaddress` parses it.
    """
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize(
    ("text", "recognised"),
    [
        pytest.param("127.0.0.1", True, id="loopback-v4"),
        pytest.param("::1", True, id="loopback-v6"),
        pytest.param("10.1.2.3", True, id="private-v4"),
        pytest.param("HTTP/1.0", False, id="a-protocol-version"),
        pytest.param("Content-Type", False, id="a-header-name"),
        pytest.param("", False, id="empty"),
    ],
)
def test_the_address_detector_knows_an_address_from_a_header(text: str, recognised: bool) -> None:
    """Guard the guard.

    The false cases matter: this module is full of protocol strings, and a detector
    that called `HTTP/1.0` an address would fail the check above for the wrong reason.
    """
    assert _is_address(text) is recognised


def test_the_wildcard_address_appears_nowhere_in_the_package(repo_root: Path) -> None:
    """The absence that sits beside the validator, because the validator cannot see this.

    `LoopbackAddress` can only refuse an address that reaches it. A wildcard written
    straight into a bind call reaches nothing, so its absence is checked separately —
    and checked over the whole package rather than one file, which is both simpler
    and stronger than the per-file rule Phase 026 had.
    """
    offenders: dict[str, list[str]] = {}
    for path in _modules(repo_root):
        text = path.read_text(encoding="utf-8")
        found = [token for token in WILDCARD_ADDRESS_TOKENS if token in text]
        if found:
            offenders[module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)] = found
    assert not offenders, f"a wildcard bind address was spelled in the package: {offenders}"


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
