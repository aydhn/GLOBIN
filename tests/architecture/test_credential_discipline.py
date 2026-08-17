"""Whether the two Win32 libraries have spread beyond the adapters that may reach them.

`test_probe_discipline.py` applies this rule to `psutil` and explains the shape.
This is the same rule for two more names, and the reason is the same one twice
over: the absence must be handled in exactly one place so that every layer above
can be written as if the library were present.

**Why these two, and why a rule at all.** `ctypes` is in the I/O-capable list, so
the dependency contract already stops the domain, ports and application layers
reaching it. What that contract cannot say is that *within the adapters layer*
only one module may load `advapi32` and only one may load `kernel32`. Without
this, a second adapter could reasonably load `kernel32` for some unrelated
purpose, and the absent-safe factory would stop being the only door.

**The absence is real, not hypothetical.** `sys.platform != "win32"` on any
non-Windows interpreter, and `docs/research/phase_028_sources.md` S-01 records
that `IsWow64Process2` did not exist before Windows 10 version 1709 while
`runtime-contract.toml` declares a floor of "10" with no build component. Both
factories answer with a recorded state rather than raising, and that is only
worth anything if nothing else reaches past them.

Like its neighbours this is a proxy rather than a proof: it matches spellings, so
an alias or an `importlib.import_module` call defeats it. It catches the way a
boundary is realistically eroded — somebody reaches for the convenient thing.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

GUARDED: Final[dict[str, str]] = {
    "advapi32": "globin.adapters.secrets",
    "kernel32": "globin.adapters.environment",
}
"""Which Win32 library each module is the sole permitted loader of.

`advapi32` carries the credential functions and `kernel32` the architecture
ones. They are separate entries rather than one rule about "Win32" because the
two adapters are absent-safe for *different* reasons — one for a logon session
with no credential set, one for a Windows release predating an API — and folding
them together would let one module quietly acquire the other's capability.
"""


def _loaded_libraries(tree: ast.AST) -> list[str]:
    """Every Win32 library name passed to a `ctypes` loader in a parsed module.

    Args:
        tree: The parsed source.

    Returns:
        The library names found, lowercased.

    Matches the *argument* rather than the import, because `import ctypes` is
    legitimate anywhere in the adapters layer — `globin.adapters.health` uses it
    for nothing of the kind. What distinguishes this rule is which library is
    handed to `WinDLL`, `windll.LoadLibrary`, `CDLL` or `OleDLL`.

    A non-literal argument is skipped rather than guessed at, which is one of the
    ways this check is a proxy: `ctypes.WinDLL(name)` for a computed `name`
    passes. That is the same limitation `test_probe_discipline.py` records about
    aliased imports, and it is accepted for the same reason.
    """
    loaders = {"WinDLL", "CDLL", "OleDLL", "LoadLibrary", "PyDLL"}
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.attr
            if isinstance(function, ast.Attribute)
            else function.id
            if isinstance(function, ast.Name)
            else ""
        )
        if name not in loaders or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append(first.value.lower().removesuffix(".dll"))
    return found


def _package_modules(repo_root: Path) -> list[Path]:
    """Every module under the package.

    Args:
        repo_root: The repository root.

    Returns:
        The paths, sorted.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


@pytest.mark.parametrize(("library", "permitted"), sorted(GUARDED.items()))
def test_only_one_adapter_loads_each_win32_library(
    repo_root: Path, library: str, permitted: str
) -> None:
    """One module owns each absence, so nothing above it has to."""
    package = repo_root / PACKAGE_RELATIVE_PATH
    offenders = {
        name: loaded
        for path in _package_modules(repo_root)
        if (loaded := [lib for lib in _loaded_libraries(_parse(path)) if lib == library])
        and (name := module_name(path, package, ROOT_PACKAGE)) != permitted
    }
    assert not offenders, (
        f"{library} is loaded outside {permitted}; the absence is handled in one place "
        f"so that every layer above can be written as if it were present: {offenders}"
    )


@pytest.mark.parametrize(("library", "permitted"), sorted(GUARDED.items()))
def test_the_permitted_adapter_does_load_it(repo_root: Path, library: str, permitted: str) -> None:
    """The other direction, so the check above is not vacuously true.

    A rule that only forbade would keep passing if the factory were deleted, at
    which point the capability would be gone and nothing would say so.
    """
    relative = Path(permitted.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/") + ".py")
    source = repo_root / PACKAGE_RELATIVE_PATH / relative
    assert library in _loaded_libraries(_parse(source))


def test_neither_factory_loads_its_library_at_import(repo_root: Path) -> None:
    """The load must be inside a function, which is what makes the absence safe.

    `test_architecture_contract.py` already forbids a *layer package* performing
    work at import, and it catches calls in module and class bodies. This states
    the specific consequence for these two modules, because it is the property
    the CI story depends on: `globin.adapters` is imported by the smoke test on
    hosts where neither library exists.
    """
    package = repo_root / PACKAGE_RELATIVE_PATH
    offenders: list[str] = []
    for permitted in sorted(GUARDED.values()):
        relative = Path(permitted.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/") + ".py")
        tree = _parse(package / relative)
        offenders.extend(
            f"{permitted}: {loaded}"
            for node in tree.body
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            for loaded in _loaded_libraries(node)
        )
    assert not offenders, f"a Win32 library is loaded at import time: {offenders}"


def _parse(path: Path) -> ast.Module:
    """Parse one module.

    Args:
        path: Where it is.

    Returns:
        The parsed tree.
    """
    return ast.parse(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param('ctypes.WinDLL("advapi32")\n', ["advapi32"], id="the ordinary spelling"),
        pytest.param('ctypes.WinDLL("Advapi32.dll")\n', ["advapi32"], id="case and suffix"),
        pytest.param(
            'def f():\n    return ctypes.WinDLL("kernel32", use_last_error=True)\n',
            ["kernel32"],
            id="inside a function, which is how this repository does it",
        ),
        pytest.param('ctypes.CDLL("kernel32")\n', ["kernel32"], id="a different loader"),
        pytest.param(
            'ctypes.windll.LoadLibrary("kernel32")\n', ["kernel32"], id="through LoadLibrary"
        ),
        pytest.param("import ctypes\n", [], id="importing ctypes alone is spared"),
        pytest.param("ctypes.string_at(pointer, 4)\n", [], id="an unrelated ctypes call is spared"),
        pytest.param("name = 'advapi32'\n", [], id="the name in a string is spared"),
        pytest.param("ctypes.WinDLL(chosen)\n", [], id="a computed name is skipped, not guessed"),
    ],
)
def test_the_loader_check_notices_a_load_and_spares_everything_else(
    source: str, expected: list[str]
) -> None:
    """The guard's own failing cases, in both directions.

    `TESTING_STRATEGY.md` requires every checker to be exercised by something it
    must catch and something it must not. The in-function row is the one that
    matters most: both factories load inside a function, so a check that missed
    that would pass while enforcing nothing at all. The last row is the honest
    limitation — a computed library name defeats this, and it is recorded here
    rather than in prose alone.
    """
    assert _loaded_libraries(ast.parse(source)) == expected
