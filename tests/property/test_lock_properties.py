"""Invariants of the lock reader, over generated input rather than fixed examples.

Four properties, chosen because their failure modes are the ones a fixed example
would not find: trusting an unhashed artefact, accepting a wheel built for another
interpreter, and a bound that quietly decides when it should refuse.

**The asymmetry is deliberate.** A gate that wrongly rejects a good lock is noisy
and found within minutes; one that wrongly accepts a bad lock is silent. So the
properties below assert the direction that matters — *never passes* — rather than
merely that a good lock does.
"""

from hypothesis import given
from hypothesis import strategies as st

from tools.quality.lock.plan import (
    LockTarget,
    Policy,
    compatibility_problems,
    hash_problems,
    normalise,
    parse_lock,
    satisfies_bound,
)

LOCK_PATH = "pylock.dev.toml"

TARGET = LockTarget(
    implementation="CPython",
    minor_line="3.14",
    architecture="AMD64",
    platform_tag="win_amd64",
    free_threaded=False,
    index="https://pypi.org/simple",
    artefact_host="files.pythonhosted.org",
    locked="2026-08-16",
)

POLICY = Policy(require_hashes=True, hash_algorithms=("sha256",), allow_source=False)

#: Distribution names PEP 503 admits, restricted to what a lock actually carries.
names = st.from_regex(r"\A[a-z][a-z0-9]{0,10}(-[a-z0-9]{1,10}){0,2}\Z", fullmatch=True)

#: A release version, kept numeric so a filename can be built from it.
versions = st.from_regex(r"\A[0-9]{1,3}(\.[0-9]{1,3}){0,2}\Z", fullmatch=True)

#: A well-formed sha256.
digests = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


def wheel_filename(name: str, version: str, tags: str) -> str:
    """A wheel filename for a package, in PEP 427's grammar."""
    return f"{name.replace('-', '_')}-{version}-{tags}.whl"


def render(packages: list[tuple[str, str, str, str]]) -> str:
    """A lock file holding the given packages."""
    body = "".join(
        f'\n[[packages]]\nname = "{name}"\nversion = "{version}"\n'
        f'\n[[packages.wheels]]\nname = "{wheel_filename(name, version, tags)}"\n'
        f'url = "https://files.pythonhosted.org/packages/ab/'
        f'{wheel_filename(name, version, tags)}"\n'
        f'\n[packages.wheels.hashes]\nsha256 = "{digest}"\n'
        for name, version, tags, digest in packages
    )
    return 'lock-version = "1.0"\ncreated-by = "pip"\n' + body


tables = st.lists(
    st.tuples(names, versions, st.just("py3-none-any"), digests),
    min_size=1,
    max_size=6,
    unique_by=lambda entry: normalise(entry[0]),
)


@given(packages=tables)
def test_a_well_formed_lock_parses_and_recovers_what_was_written(
    packages: list[tuple[str, str, str, str]],
) -> None:
    """Deciding a well-formed lock never raises, and nothing is lost in the reading.

    The reader is the gate's only view of the file, so anything it drops is
    something no check downstream can see.
    """
    parsed = parse_lock(render(packages), path=LOCK_PATH)
    assert len(parsed.packages) == len(packages)
    for entry, (name, version, _tags, digest) in zip(parsed.packages, packages, strict=True):
        assert entry.name == name
        assert entry.version == version
        assert entry.wheels[0].hashes == (("sha256", digest),)


@given(packages=tables, index=st.integers(min_value=0, max_value=5))
def test_a_lock_with_any_hash_removed_never_passes(
    packages: list[tuple[str, str, str, str]], index: int
) -> None:
    """For every position, not merely the first.

    An unhashed artefact installs whatever the URL serves. A check that only
    looked at the first entry would pass a lock whose last package was open, and
    nothing about the file would look wrong.
    """
    position = index % len(packages)
    parsed = parse_lock(render(packages), path=LOCK_PATH)
    target = parsed.packages[position]
    stripped = type(target)(
        name=target.name,
        version=target.version,
        wheels=tuple(
            type(artefact)(name=artefact.name, url=artefact.url, path=artefact.path, hashes=())
            for artefact in target.wheels
        ),
        sdist=None,
        direct_kind=None,
    )
    assert hash_problems(stripped, POLICY, LOCK_PATH)


@given(name=names, version=versions)
def test_a_pure_python_wheel_always_serves_the_target(name: str, version: str) -> None:
    """`py3-none-any` binds to no ABI and no platform, so it installs anywhere."""
    parsed = parse_lock(render([(name, version, "py3-none-any", "0" * 64)]), path=LOCK_PATH)
    assert compatibility_problems(parsed.packages[0], TARGET, LOCK_PATH) == ()


@given(
    name=names,
    version=versions,
    tags=st.sampled_from(
        [
            "cp313-cp313-win_amd64",
            "cp312-cp312-win_amd64",
            "cp314-cp314-win32",
            "cp314-cp314-manylinux1_x86_64",
            "cp314-cp314t-win_amd64",
        ]
    ),
)
def test_a_wheel_for_another_interpreter_or_platform_never_serves_the_target(
    name: str, version: str, tags: str
) -> None:
    """Including the free-threaded ABI, which is where a substring search gets it backwards.

    `cp314-cp314t` looks like it would serve a 3.14 interpreter and does not: the
    free-threaded build has its own ABI, and a wheel for one does not install on
    the other.
    """
    parsed = parse_lock(render([(name, version, tags, "0" * 64)]), path=LOCK_PATH)
    assert compatibility_problems(parsed.packages[0], TARGET, LOCK_PATH)


@given(
    version=versions,
    operator=st.sampled_from([">=", "==", "~=", "!=", "<", "<=", ">", ""]),
    bound=versions,
)
def test_a_bound_either_decides_or_refuses_with_no_third_outcome(
    version: str, operator: str, bound: str
) -> None:
    """Three-valued on purpose, and never anything else.

    A lock exists to say exactly what will be installed. A specifier this module
    cannot evaluate must report that rather than resolve to True, which is where
    it deliberately differs from `inventory._satisfies`.
    """
    verdict = satisfies_bound(version, f"{operator}{bound}")
    assert verdict is None or isinstance(verdict, bool)
    if operator != ">=":
        assert verdict is None


@given(name=names)
def test_normalisation_is_idempotent(name: str) -> None:
    """Every comparison in the gate runs over normalised names.

    A normaliser that changed its answer on a second application would make
    `normalise(a) == normalise(b)` depend on how many times each side had been
    through it.
    """
    once = normalise(name)
    assert normalise(once) == once
