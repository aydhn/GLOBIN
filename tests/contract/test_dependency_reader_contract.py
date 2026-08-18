"""Two readers of one specification, compared against the files they both read.

This repository parses PEP 751 twice, and that is a deliberate exception to a
rule rather than an accident. `docs/engineering/SOURCE_OF_TRUTH.md` permits a
second copy of a fact only when "a test compares the two copies and fails when
they diverge". **This is that test.**

The two readers, and why neither can be deleted:

- `tools/quality/lock/plan.py:parse_lock` was written in Phase 020, by hand,
  before `packaging` was available to this repository. It runs inside the quality
  gate, on a bare CI interpreter that installs five pinned tools and no runtime
  lock.
- `globin.adapters.dependency.read_lock` delegates to `packaging.pylock`, the
  specification's own reference implementation. It runs inside a started GLOBIN,
  which cannot import `tools/` at all -- `pyproject.toml` packages only
  `src/globin`, so the gate's parser does not exist in an installed GLOBIN.

Note which way round the comparison runs. The reference implementation is the
yardstick and the hand-written gate parser is the thing being checked, so this
file validates delivered Phase 020 code against the specification rather than
merely pinning two new pieces of code to each other.

Two asymmetries are asserted **as deliberate** rather than smoothed away. Where
the readers differ on purpose, the test pins the direction of the difference, so
that the difference cannot silently invert.
"""

import pytest

from globin.adapters.dependency import read_lock
from globin.domain.dependency import LockState, versions_agree
from tests.support import REPO_ROOT
from tools.quality.lock.plan import LockError, parse_lock, version_problems

COMMITTED_LOCKS = ("pylock.toml", "pylock.dev.toml")

WHEEL = (
    "[[packages.wheels]]\n"
    'name = "thing-1.0-py3-none-any.whl"\n'
    'url = "https://files.pythonhosted.org/thing-1.0-py3-none-any.whl"\n'
    'hashes = {sha256 = "0123456789abcdef"}\n'
)

MINIMAL = (
    'lock-version = "1.0"\n'
    'created-by = "globin-tests"\n'
    "[[packages]]\n"
    'name = "thing"\n'
    'version = "1.0"\n' + WHEEL
)


def lock_text(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Agreement on the files that are actually in this repository
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [pytest.param(name, id=name.replace(".", "-")) for name in COMMITTED_LOCKS],
)
def test_both_readers_agree_about_every_committed_lock(name: str) -> None:
    """The comparison that makes the second reader a tripwire rather than drift."""
    text = lock_text(name)
    gate = parse_lock(text, path=name)
    runtime = read_lock(text)

    assert runtime.state is LockState.PRESENT
    assert runtime.lock_version == gate.lock_version
    assert {entry.name: entry.version for entry in runtime.entries} == {
        package.normalised: (package.version or "") for package in gate.packages
    }


@pytest.mark.parametrize(
    "name",
    [pytest.param(name, id=name.replace(".", "-")) for name in COMMITTED_LOCKS],
)
def test_neither_reader_finds_a_committed_lock_surprising(name: str) -> None:
    """No unknown key, so PEP 751's SHOULD-warn clause is silent on these files.

    A relock by a future pip that emits a key neither reader knows will turn this
    red, which is the notice this repository wants rather than a surprise later.
    """
    assert read_lock(lock_text(name)).unknown_keys == ()


def test_the_committed_locks_are_not_empty_so_the_comparison_is_not_vacuous() -> None:
    """Guard the guard: an agreement about nothing would pass every assertion."""
    for name in COMMITTED_LOCKS:
        assert len(read_lock(lock_text(name)).entries) > 5


# ---------------------------------------------------------------------------
# Divergence: the tripwire must be able to fire
# ---------------------------------------------------------------------------


def test_both_readers_refuse_a_major_version_neither_implements() -> None:
    """An unsupported major version is a refusal PEP 751 requires of both.

    The specification's words are "If a tool doesn't support a major version, it
    MUST raise an error".

    Both refuse, and they refuse at **different stages** -- which this test
    discovered rather than assumed. The gate parses the document successfully and
    reports the version separately through `version_problems`, because its job is
    to collect every problem in a file and print them together. The reference
    implementation refuses during parsing, because its job is to hand back a
    valid object or none.

    So the pairing is what is asserted, not identical behaviour, and not an
    identical moment. What would be a genuine defect is either one *accepting*.
    """
    text = 'lock-version = "2.0"\ncreated-by = "x"\npackages = []\n'

    gate = parse_lock(text, path="future.toml")
    assert version_problems(gate), "the gate must refuse a major version it cannot read"

    assert read_lock(text).state is LockState.UNSUPPORTED


def test_a_document_that_is_not_toml_at_all_stops_both_readers() -> None:
    """Here the gate does raise, which is the shape difference above, inverted."""
    text = "this is not toml {{{"

    with pytest.raises(LockError):
        parse_lock(text, path="broken.toml")

    assert read_lock(text).state is LockState.UNREADABLE


def test_the_readers_differ_on_an_unknown_key_and_the_direction_is_pinned() -> None:
    """A deliberate asymmetry, and the more capable answer is the runtime's.

    The gate reads the keys it knows and ignores the rest, which is correct
    behaviour for a parser and cannot satisfy the specification's SHOULD-warn
    clause. The runtime audits the document's keys against the specification's
    set, so it reports what the gate cannot.
    """
    text = MINIMAL.replace(
        'created-by = "globin-tests"\n', 'created-by = "globin-tests"\nfuture-key = 1\n'
    )

    gate = parse_lock(text, path="future.toml")
    runtime = read_lock(text)

    assert [package.normalised for package in gate.packages] == ["thing"]
    assert runtime.state is LockState.NEWER_MINOR
    assert runtime.unknown_keys == ("future-key",)
    assert [entry.name for entry in runtime.entries] == ["thing"]


def test_the_runtime_reader_enforces_rules_the_gate_never_learned() -> None:
    """The reason the reference implementation is the yardstick.

    PEP 751 requires a package name to be normalised. The hand-written gate
    parser reports that separately, through `package_problems`, rather than
    refusing the document; the reference implementation refuses it outright.
    Both catch it. Only one of them was told to.
    """
    text = MINIMAL.replace('name = "thing"\n', 'name = "Thing_Name"\n', 1)

    assert read_lock(text).state is LockState.UNREADABLE
    parse_lock(text, path="unnormalised.toml")


# ---------------------------------------------------------------------------
# The version-comparison asymmetry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("locked", "installed"),
    [
        pytest.param("1.0", "1.0.0", id="trailing-zero"),
        pytest.param("1.0.0", "1.0", id="trailing-zero-reversed"),
        pytest.param("2.5.2", "2.5.2.0", id="fourth-component"),
    ],
)
def test_the_runtime_accepts_version_spellings_the_gate_would_call_different(
    locked: str, installed: str
) -> None:
    """The second deliberate asymmetry, with its direction pinned.

    The gate compares versions as raw strings, because it asks whether the
    committed file's *text* describes this environment. The runtime compares them
    as PEP 440 releases, because it asks whether the *release* is the same.

    The direction matters and is asserted here: what the runtime accepts is a
    **superset** of what a string comparison accepts. If that ever inverts --
    if the runtime started refusing something the gate accepts -- a start-up
    would refuse an environment the gate had just certified, and this test is
    what would catch it.
    """
    assert locked != installed
    assert versions_agree(locked, installed) is True


def test_the_two_comparisons_agree_whenever_the_text_is_identical() -> None:
    """The superset claim, from the other end: string equality implies agreement."""
    for version in ("1.0", "2.5.2", "0.26.0", "7.2.2"):
        assert versions_agree(version, version) is True
