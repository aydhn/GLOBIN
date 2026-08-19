"""Whether either provider library has spread beyond its one adapter, and who may use a socket.

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

**Phase 034 made the socket half a two-role rule, and it did not relax.** Until
then GLOBIN opened no outbound connection and one module could bind. It now has a
REST transport, so exactly two modules may touch a socket and each keeps the one
direction it was named for: the listener may not become a client, and the client
may not become a server. The rule is *stronger* than what it replaced — the routes
outward (`http.client`, `urllib.request`, `ssl`) were unguarded entirely, so any
module could have reached the internet, and the matcher that was supposed to guard
`http.server` had never matched a dotted name at all. ADR-0089 records the exchange.

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
"""The one module in GLOBIN that may open a *listening* socket."""

OUTBOUND_MODULE: Final[str] = "globin.adapters.rest_transport"
"""The one module in GLOBIN that may *reach outward*.

Added in Phase 034, which gave GLOBIN a REST transport. Until then the package
opened no outbound connection at all and this constant had no reason to exist.
"""

SOCKET_CAPABLE: Final[dict[str, str]] = {
    LISTENER_MODULE: "listen",
    OUTBOUND_MODULE: "reach outward",
}
"""Every module that may touch a socket, and what each one is for.

Two, and the count is exact in both directions: a third module naming any route
below fails, and either of these two losing its route fails as well.
"""

LISTENER_IMPORTS: Final[tuple[str, ...]] = ("socketserver", "http.server")
"""Standard-library routes to a *listening* socket.

Permitted only in :data:`LISTENER_MODULE`. Importing one of these in the outbound
module would mean the REST client had grown a server, which is a different
component wearing the same name.
"""

OUTBOUND_IMPORTS: Final[tuple[str, ...]] = ("http.client", "urllib.request", "ssl")
"""Standard-library routes *out*, permitted only in :data:`OUTBOUND_MODULE`.

**None of these were guarded before Phase 034, and that was a hole rather than an
omission.** The rule as Phase 027 left it named ``socket``, ``socketserver`` and
``http.server`` — every route to a *listener*. Any module in the package could
have imported ``http.client`` or ``urllib.request`` and reached the internet, and
nothing would have noticed. The phase that finally needed one outbound module is
the phase that closes the door behind it.

``ssl`` is here rather than beside ``socket`` because its only use in this package
is building the client's verifying context. A second module reaching for it would
be a second module deciding how TLS is configured, which is exactly what
:func:`globin.adapters.rest_transport.secure_context` exists to prevent.
"""

SHARED_SOCKET_IMPORTS: Final[tuple[str, ...]] = ("socket",)
"""The substrate both roles are built on, permitted in either named module.

``socket`` cannot be assigned to one role: the listener binds one and the client
connects one. What it can be is confined to the two modules that already have a
declared role, which is what stops a third module being one ``connect()`` away
from the thing this rule exists to prevent.
"""

SOCKET_ROUTES: Final[tuple[str, ...]] = (
    *LISTENER_IMPORTS,
    *OUTBOUND_IMPORTS,
    *SHARED_SOCKET_IMPORTS,
)
"""Every route to a socket, of either direction."""

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


def _covers(imported: str, guarded: str) -> bool:
    """Whether one imported dotted name is, or lives inside, a guarded module.

    Args:
        imported: The dotted name an import statement names.
        guarded: The module being guarded.

    Returns:
        Whether the import reaches the guarded module.

    **A dotted guard never matched before Phase 034, and that was a hole rather
    than a simplification.** This function replaces ``name.split(".")[0] ==
    guarded``, which compares only the first segment — so ``http.server`` had been
    in :data:`LISTENER_IMPORTS` since Phase 026 matching nothing at all, because the
    first segment of ``import http.server`` is ``http``. The rule passed its own
    guard-the-guard test the whole time, because ``socketserver`` is a single
    segment and one satisfied route was enough to prove the module reached *a*
    socket.

    Nothing had exploited it: ``diagnostics_http`` is the only module that imports
    ``http.server`` and it is the permitted one. But the rule Phase 034 needs is
    specifically about ``http.client`` against ``http.server`` — two dotted names
    sharing a first segment — so the comparison had to become exact before it could
    tell the two roles apart.
    """
    return imported == guarded or imported.startswith(f"{guarded}.")


def _imports(tree: ast.AST, guarded: str) -> list[str]:
    """Every spelling of one guarded module in a parsed file.

    Args:
        tree: The parsed source.
        guarded: The module name, dotted or not.

    Returns:
        The spellings found.

    ``from http import client`` is caught by joining the module to each imported
    name, which is the one spelling neither the statement's module nor its names
    carry on their own.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(a.name for a in node.names if _covers(a.name, guarded))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _covers(node.module, guarded):
                found.append(node.module)
            else:
                found.extend(
                    f"{node.module}.{a.name}"
                    for a in node.names
                    if _covers(f"{node.module}.{a.name}", guarded)
                )
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


def test_only_the_two_named_modules_can_reach_a_socket_at_all(repo_root: Path) -> None:
    """The count of modules able to touch a socket is two, and both are named.

    A proxy rather than a proof, like its neighbours: a module handed an open socket
    would defeat it. What it catches is the realistic erosion — somebody importing
    ``http.client`` in a second place because it was convenient there too, which
    before Phase 034 this rule would not have caught anywhere.
    """
    offenders: dict[str, list[str]] = {}
    for path in _modules(repo_root):
        name = module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)
        if name in SOCKET_CAPABLE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = sorted({spelling for guard in SOCKET_ROUTES for spelling in _imports(tree, guard)})
        if found:
            offenders[name] = found
    permitted = ", ".join(sorted(SOCKET_CAPABLE))
    assert not offenders, f"a socket became reachable outside {permitted}: {offenders}"


@pytest.mark.parametrize(
    ("module", "routes"),
    [
        pytest.param(LISTENER_MODULE, LISTENER_IMPORTS, id="listener"),
        pytest.param(OUTBOUND_MODULE, OUTBOUND_IMPORTS, id="outbound"),
    ],
)
def test_each_named_module_does_reach_what_its_role_needs(
    repo_root: Path, module: str, routes: tuple[str, ...]
) -> None:
    """The other direction, so the rule cannot pass by a role vanishing.

    ``test_process_discipline.py`` is the same shape for the same reason: a rule
    that only forbids is satisfied by nobody doing the thing at all.
    """
    relative = module.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/")
    tree = ast.parse((repo_root / PACKAGE_RELATIVE_PATH / f"{relative}.py").read_text("utf-8"))
    found = {spelling for guard in routes for spelling in _imports(tree, guard)}
    assert found, f"{module} reaches none of {routes}, so its half of the rule guards nothing"


@pytest.mark.parametrize(
    ("module", "forbidden", "role"),
    [
        pytest.param(LISTENER_MODULE, OUTBOUND_IMPORTS, "a client", id="listener-stays-a-server"),
        pytest.param(OUTBOUND_MODULE, LISTENER_IMPORTS, "a server", id="client-stays-a-client"),
    ],
)
def test_neither_named_module_grows_the_other_role(
    repo_root: Path, module: str, forbidden: tuple[str, ...], role: str
) -> None:
    """Two permitted modules is not the same as two modules permitted everything.

    Without this, naming a second socket-capable module would have widened the rule
    twice over: the listener could have started making outbound requests and the
    client could have started accepting them, with the count of socket-capable
    modules still reading two. Each module keeps exactly the direction it was named
    for.
    """
    relative = module.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/")
    tree = ast.parse((repo_root / PACKAGE_RELATIVE_PATH / f"{relative}.py").read_text("utf-8"))
    found = sorted({spelling for guard in forbidden for spelling in _imports(tree, guard)})
    assert not found, f"{module} has become {role}: {found}"


@pytest.mark.parametrize("module", sorted(SOCKET_CAPABLE))
def test_neither_socket_module_contains_an_address_literal_at_all(
    repo_root: Path, module: str
) -> None:
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
    relative = module.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/")
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
    assert not literals, f"{module} spells an address rather than being handed one: {literals}"


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


@pytest.mark.parametrize(
    ("source", "routes", "caught"),
    [
        pytest.param("import http.client\n", "SOCKET", True, id="dotted-import"),
        pytest.param("from http import client\n", "SOCKET", True, id="from-package-import-module"),
        pytest.param("from http.client import HTTPConnection\n", "SOCKET", True, id="from-dotted"),
        pytest.param("import urllib.request\n", "SOCKET", True, id="urllib-request"),
        pytest.param("import socket\n", "SOCKET", True, id="bare-socket"),
        pytest.param("import ssl\n", "SOCKET", True, id="ssl"),
        pytest.param("import json\n", "SOCKET", False, id="innocent"),
        pytest.param("import http\n", "SOCKET", False, id="the-package-alone-reaches-nothing"),
        pytest.param("import http.client\n", "OUTBOUND", True, id="listener-would-grow-a-client"),
        pytest.param("import socketserver\n", "LISTENER", True, id="client-would-grow-a-server"),
        pytest.param("import http.server\n", "LISTENER", True, id="client-would-grow-a-server-2"),
        pytest.param("import http.server\n", "OUTBOUND", False, id="server-is-not-client"),
    ],
)
def test_the_socket_detector_tells_the_two_directions_apart(
    source: str, routes: str, caught: bool
) -> None:
    """Guard the guard, in both directions and for both roles.

    **Every dotted case here failed before Phase 034**, because the matcher compared
    only an import's first segment. ``import http.client`` and ``import
    http.server`` were indistinguishable from each other and from ``import http``,
    which is precisely the distinction the two-role rule turns on. The cases are
    parametrised rather than argued in prose so that a future simplification of
    :func:`_covers` cannot quietly reintroduce the hole.
    """
    guards = {
        "SOCKET": SOCKET_ROUTES,
        "LISTENER": LISTENER_IMPORTS,
        "OUTBOUND": OUTBOUND_IMPORTS,
    }[routes]
    tree = ast.parse(source)
    found = bool({spelling for guard in guards for spelling in _imports(tree, guard)})
    assert found is caught
