"""What the domain layer may know about, enforced against the real source tree.

Phase 011 registers *kinds* of identifier and refuses to register *instances*.
The distinction is the whole phase, and it is easy to lose: the natural next
commit after "products have canonical names" is a tuple of the product names,
placed in the domain layer because that is where the type lives. This module is
what makes that fail.

**Why nothing else already covers this.** Three checks look as though they might,
and none does:

* The dependency contract forbids an inner layer importing an outer one or an
  I/O-capable module. A tuple of strings imports nothing.
* ``tests/unit/test_values.py`` holds Phase 008's version of the rule —
  ``test_a_well_formed_code_no_venue_lists_is_still_a_currency`` fails if a set
  of known codes appears. That is one type's behaviour, checked through one
  constructor. A register of *products* next year would be caught by nothing.
* ``docs/architecture/dependency-rules.toml`` states the rule in prose — "domain
  must remain describable without mentioning Binance, HTTP, Windows or any
  storage engine" — and states it nowhere a machine reads.

The second rule closes a gap ADR-0026 left open. That record puts identifier
generation in the adapters layer because it reads a source of randomness, and
the dependency contract does not list :mod:`uuid`, :mod:`random` or
:mod:`secrets` among the I/O-capable modules — so nothing today would notice
:func:`uuid.uuid4` appearing in the domain. ``test_clock_discipline.py`` is the
same shape for the same reason.

Both checks are proxies rather than proofs, in the sense
``docs/architecture/dependency-rules.toml`` already uses about I/O imports: they
match spellings, so an alias defeats them. They catch the way a boundary is
realistically eroded — somebody reaches for the convenient thing — and each has
its own failing case below.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

#: Vocabulary that names a *thing a venue offers* rather than a shape GLOBIN
#: enforces. Compared case-insensitively against whole string constants, so a
#: sentence mentioning one in prose is unaffected and a tuple listing them is
#: not. Products and environments come from ``docs/GLOSSARY.md``; the assets are
#: the ones a register would reach for first.
VENUE_VOCABULARY: Final[frozenset[str]] = frozenset(
    {
        "algo trading",
        "bnb",
        "btc",
        "busd",
        "coin-m futures",
        "cross margin",
        "demo",
        "demo mode",
        "eth",
        "futures",
        "internal simulation",
        "isolated margin",
        "live",
        "mainnet",
        "margin",
        "options",
        "portfolio margin",
        "portfolio margin pro",
        "production",
        "simulation",
        "spot",
        "testnet",
        "usdc",
        "usdt",
        "wallet",
    }
)

#: Call spellings that read a source of randomness, as :func:`ast.unparse`
#: renders them. ADR-0026 places every one of these in the adapters layer.
RANDOMNESS_CALLS: Final[frozenset[str]] = frozenset(
    {
        "getrandbits",
        "os.urandom",
        "random.getrandbits",
        "random.random",
        "secrets.token_bytes",
        "secrets.token_hex",
        "token_hex",
        "urandom",
        "uuid.uuid1",
        "uuid.uuid4",
        "uuid1",
        "uuid4",
    }
)


def _live_constants(tree: ast.AST) -> list[str]:
    """Every string constant in a parsed module that is not a docstring.

    Args:
        tree: The parsed source.

    Returns:
        The values, in the order :func:`ast.walk` reaches them.

    A docstring is a bare string expression statement, so excluding every
    :class:`ast.Expr` wrapping a constant removes module, class, function and
    attribute docstrings in one rule. What remains is string data the module
    actually carries: defaults, literals, and the elements of any collection.
    """
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _randomness_calls(tree: ast.AST) -> list[str]:
    """Every randomness-reading call in a parsed module.

    Args:
        tree: The parsed source.

    Returns:
        The spellings found, in the order :func:`ast.walk` reaches them.
    """
    return [
        spelling
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (spelling := ast.unparse(node.func)) in RANDOMNESS_CALLS
    ]


def _domain_modules(repo_root: Path) -> list[Path]:
    """Every module in the domain layer, sorted so two runs report identically.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH / "domain").rglob("*.py"))


def test_the_domain_layer_names_no_product_environment_or_asset(repo_root: Path) -> None:
    """Phase 011's own predicted failure, made to fail here rather than in Phase 036.

    A register of instances in the domain layer turns a capability question into
    a shape one. Which products a venue offers is answered against the venue
    (ADR-0006) and changes without GLOBIN being redeployed; a tuple compiled
    into the innermost layer cannot express that and would be wrong quietly.
    """
    offenders = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE): named
        for path in _domain_modules(repo_root)
        if (
            named := sorted(
                {
                    value
                    for value in _live_constants(ast.parse(path.read_text(encoding="utf-8")))
                    if value.strip().lower() in VENUE_VOCABULARY
                }
            )
        )
    }
    assert not offenders, (
        "the domain layer names something a venue offers; a register of instances "
        "belongs to the phase that reads it from the venue, not to the layer that "
        f"bounds its shape: {offenders}"
    )


def test_the_domain_layer_reads_no_source_of_randomness(repo_root: Path) -> None:
    """ADR-0026's rule, which the dependency contract cannot express.

    `uuid`, `random` and `secrets` are absent from the I/O-capable list, so an
    identifier minted in the domain would import cleanly and make every value
    built from it nondeterministic — the failure ADR-0026 rejected by name.
    """
    offenders = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE): calls
        for path in _domain_modules(repo_root)
        if (calls := _randomness_calls(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert not offenders, (
        "the domain layer reads a source of randomness; minting belongs in the "
        f"adapters layer beside the clock, as ADR-0026 requires: {offenders}"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param('KNOWN = ("spot", "margin")\n', ["spot", "margin"], id="a register"),
        pytest.param('x = {"testnet": 1}\n', ["testnet"], id="a mapping key"),
        pytest.param('def f():\n    return "BTC"\n', ["BTC"], id="inside a function"),
        pytest.param('"""Prose mentioning spot and testnet."""\n', [], id="a module docstring"),
        pytest.param(
            'class A:\n    """Doc."""\n\n    B = "x"\n    """Attribute doc."""\n',
            ["x"],
            id="attribute docstrings are spared",
        ),
    ],
)
def test_the_constant_check_notices_a_register_and_spares_prose(
    source: str, expected: list[str]
) -> None:
    """The guard's own failing cases, in both directions.

    ``TESTING_STRATEGY.md`` requires every checker to be exercised by something
    it must catch and something it must not. The last two rows are the ones that
    matter: this module's own docstrings mention every word in the denylist, so
    a check that read them would refuse the code it exists to protect.
    """
    assert _live_constants(ast.parse(source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("x = uuid4().hex\n", ["uuid4"], id="bare"),
        pytest.param("x = uuid.uuid4()\n", ["uuid.uuid4"], id="dotted"),
        pytest.param("def f():\n    return os.urandom(16)\n", ["os.urandom"], id="in a function"),
        pytest.param("x = value.uuid4\n", [], id="an attribute read is spared"),
        pytest.param("def f(c):\n    return c.now()\n", [], id="another call is spared"),
    ],
)
def test_the_randomness_check_notices_a_mint_and_spares_everything_else(
    source: str, expected: list[str]
) -> None:
    """The second guard's own failing cases."""
    assert _randomness_calls(ast.parse(source)) == expected
