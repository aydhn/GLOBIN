"""Every judgement the lock gate makes, from literals.

The cases are taken from what `pip lock` actually emits rather than invented: a
lock carries `lock-version`, `created-by` and `packages`, and each package carries
a name, a version and wheel entries with a URL and a digest table. Ledger entry
S-03 records where that shape was read from, and it is why several checks a reader
would expect are absent — there is no `requires-python` in the file to compare.

**The refusals are most of this module, and that is the point.** A lock gate that
only ever sees good locks is a gate nobody has tested. Each case below is one way a
lock can be wrong while still parsing as TOML.
"""

import pytest

from tools.quality.lock.plan import (
    Declaration,
    Gap,
    Lock,
    LockedFile,
    LockedPackage,
    LockError,
    LockTarget,
    Policy,
    Producer,
    artefact_problems,
    compatibility_problems,
    coverage_problems,
    declaration_problems,
    duplicate_packages,
    environment_problems,
    hash_problems,
    normalise,
    package_problems,
    parse_declaration,
    parse_lock,
    producer_problems,
    register_problems,
    runtime_problems,
    satisfies_bound,
    source_problems,
    target_problems,
    version_problems,
)
from tools.quality.supply.inventory import (
    CONTINUOUS_INTEGRATION,
    DEVELOPMENT,
    PINNED,
    PRE_COMMIT,
    PYPI,
    PYPROJECT,
    RANGED,
    RUNTIME,
    Dependency,
)

DIGEST = "a" * 64
"""A well-formed sha256, in the only spelling this module accepts.

Not a real digest of anything, and deliberately not credential-shaped: it is
sixty-four of one character, which no scanner mistakes for a secret and no reader
mistakes for evidence.
"""

LOCK_PATH = "pylock.dev.toml"

MINIMAL_LOCK = f"""\
lock-version = "1.0"
created-by = "pip"

[[packages]]
name = "ruff"
version = "0.15.14"

[[packages.wheels]]
name = "ruff-0.15.14-py3-none-win_amd64.whl"
url = "https://files.pythonhosted.org/packages/ab/ruff-0.15.14-py3-none-win_amd64.whl"

[packages.wheels.hashes]
sha256 = "{DIGEST}"
"""

DECLARATION = """\
schema = 1

[producer]
tool = "pip"
version = "26.1.1"
experimental = true

[target]
implementation = "CPython"
minor_line = "3.14"
architecture = "AMD64"
platform_tag = "win_amd64"
free_threaded = false
index = "https://pypi.org/simple"
artefact_host = "files.pythonhosted.org"
locked = 2026-08-16

[policy]
require_hashes = true
hash_algorithms = ["sha256"]
allow_source = false

[dev]
path = "pylock.dev.toml"
extra = "dev"
roots = ["ruff>=0.6"]

[runtime]
path = "pylock.toml"
locked = false
reason = "there are no runtime dependencies yet"

[project]
distribution = "globin"
installed = false

[environment]
seeded = ["pip"]
"""


def target(**overrides: object) -> LockTarget:
    """A target matching the declaration above, with any field replaced."""
    values: dict[str, object] = {
        "implementation": "CPython",
        "minor_line": "3.14",
        "architecture": "AMD64",
        "platform_tag": "win_amd64",
        "free_threaded": False,
        "index": "https://pypi.org/simple",
        "artefact_host": "files.pythonhosted.org",
        "locked": "2026-08-16",
    }
    values.update(overrides)
    return LockTarget(**values)  # type: ignore[arg-type]


def policy(**overrides: object) -> Policy:
    """The declared policy, with any field replaced."""
    values: dict[str, object] = {
        "require_hashes": True,
        "hash_algorithms": ("sha256",),
        "allow_source": False,
    }
    values.update(overrides)
    return Policy(**values)  # type: ignore[arg-type]


def wheel(name: str, *, url: str | None = None, hashes: object = None) -> LockedFile:
    """One wheel entry, with a well-formed URL and digest unless overridden."""
    return LockedFile(
        name=name,
        url=url if url is not None else f"https://files.pythonhosted.org/packages/ab/{name}",
        path=None,
        hashes=(("sha256", DIGEST),) if hashes is None else hashes,  # type: ignore[arg-type]
    )


def package(
    name: str = "ruff",
    version: str | None = "0.15.14",
    *,
    wheels: tuple[LockedFile, ...] | None = None,
    sdist: LockedFile | None = None,
    direct_kind: str | None = None,
) -> LockedPackage:
    """One package entry, serving the target unless overridden."""
    if wheels is None:
        wheels = (wheel(f"{name}-{version}-py3-none-win_amd64.whl"),)
    return LockedPackage(
        name=name, version=version, wheels=wheels, sdist=sdist, direct_kind=direct_kind
    )


def lock(*packages: LockedPackage, version: str = "1.0", created_by: str = "pip") -> Lock:
    """A lock holding the given packages."""
    return Lock(
        path=LOCK_PATH,
        lock_version=version,
        created_by=created_by,
        packages=packages or (package(),),
    )


def declaration(**overrides: object) -> Declaration:
    """The declaration above as a value, with any field replaced."""
    values: dict[str, object] = {
        "producer": Producer(tool="pip", version="26.1.1", experimental=True),
        "target": target(),
        "policy": policy(),
        "dev_path": LOCK_PATH,
        "dev_extra": "dev",
        "roots": ("ruff>=0.6",),
        "runtime_locked": False,
        "runtime_path": "pylock.toml",
        "runtime_roots": (),
        "project_distribution": "globin",
        "project_installed": False,
        "seeded": ("pip",),
        "gaps": (),
    }
    values.update(overrides)
    return Declaration(**values)  # type: ignore[arg-type]


def declared(
    name: str = "ruff",
    version: str = ">=0.6",
    *,
    scope: str = DEVELOPMENT,
    source: str = PYPROJECT,
    ecosystem: str = PYPI,
    resolution: str = RANGED,
) -> Dependency:
    """One inventory entry, as a register would report it."""
    return Dependency(
        ecosystem=ecosystem,
        name=name,
        version=version,
        scope=scope,
        resolution=resolution,
        source=source,
    )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("ruff", "ruff"),
        ("Pip_Audit", "pip-audit"),
        ("boolean.py", "boolean-py"),
        ("A__B", "a-b"),
        ("py-serializable", "py-serializable"),
    ],
)
def test_names_normalise_under_pep_503(written: str, expected: str) -> None:
    """Two spellings of one distribution must reduce to one key.

    Without this the lock could hold `pip_audit` and the inventory `pip-audit`,
    and every comparison between them would report a package missing from both.
    """
    assert normalise(written) == expected


# ---------------------------------------------------------------------------
# Reading a lock
# ---------------------------------------------------------------------------


def test_a_minimal_lock_parses_into_what_pip_wrote() -> None:
    """The shape ledger S-03 records, read back field for field."""
    parsed = parse_lock(MINIMAL_LOCK, path=LOCK_PATH)
    assert parsed.lock_version == "1.0"
    assert parsed.created_by == "pip"
    assert len(parsed.packages) == 1
    only = parsed.packages[0]
    assert only.name == "ruff"
    assert only.version == "0.15.14"
    assert only.wheels[0].hashes == (("sha256", DIGEST),)
    assert only.wheels[0].url is not None
    assert only.sdist is None
    assert only.direct_kind is None


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("this is not toml", id="not-toml"),
        pytest.param('created-by = "pip"\npackages = []\n', id="no-lock-version"),
        pytest.param('lock-version = ""\ncreated-by = "pip"\npackages = []\n', id="empty-version"),
        pytest.param('lock-version = "1.0"\npackages = []\n', id="no-created-by"),
        pytest.param('lock-version = "1.0"\ncreated-by = "pip"\n', id="no-packages"),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\npackages = "several"\n',
            id="packages-not-an-array",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\npackages = [1]\n',
            id="package-not-a-table",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n[[packages]]\nversion = "1"\n',
            id="package-without-a-name",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n[[packages]]\nname = "a"\nversion = 1\n',
            id="version-not-a-string",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n[[packages]]\nname = "a"\nwheels = 1\n',
            id="wheels-not-an-array",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n[[packages]]\nname = "a"\nsdist = 1\n',
            id="sdist-not-a-table",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n'
            '[[packages]]\nname = "a"\n[[packages.wheels]]\nurl = "https://x/y"\n',
            id="artefact-without-a-name",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n'
            '[[packages]]\nname = "a"\n[[packages.wheels]]\nname = "w"\nurl = 1\n',
            id="url-not-a-string",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n'
            '[[packages]]\nname = "a"\n[[packages.wheels]]\nname = "w"\nhashes = 1\n',
            id="hashes-not-a-table",
        ),
        pytest.param(
            'lock-version = "1.0"\ncreated-by = "pip"\n'
            '[[packages]]\nname = "a"\n[[packages.wheels]]\nname = "w"\n'
            "[packages.wheels.hashes]\nsha256 = 1\n",
            id="hash-not-a-string",
        ),
    ],
)
def test_a_lock_this_reader_cannot_use_is_refused_rather_than_partly_read(text: str) -> None:
    """Refused, not salvaged.

    A half-read lock is worse than none: the checks below would run over whatever
    survived parsing and report a verdict about a subset nobody chose.
    """
    with pytest.raises(LockError):
        parse_lock(text, path=LOCK_PATH)


# ---------------------------------------------------------------------------
# The format version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        ("1.0", True),
        ("1.1", False),
        ("2.0", False),
        ("0.9", False),
        ("1", False),
        ("one.zero", False),
    ],
)
def test_only_a_format_this_reader_implements_is_accepted(version: str, accepted: bool) -> None:
    """A later minor may add fields, and a reader ignoring them reports a partial check.

    PEP 751 permits a minor bump to carry new information. Reading one
    optimistically would mean recomputing a verdict from an incomplete picture
    while presenting it as a complete one, so a minor ahead of this reader is
    refused in the same breath as an unknown major.
    """
    assert (version_problems(lock(version=version)) == ()) is accepted


def test_a_lock_written_by_another_tool_is_reported() -> None:
    """`created-by` is the only thing the file says about what produced it."""
    problems = producer_problems(lock(created_by="uv"), declaration())
    assert any("created-by" in problem for problem in problems)


def test_a_locked_producer_must_be_the_declared_producer() -> None:
    """The lock installs the same producer that wrote it, or it installs another one.

    pip is a real transitive dependency of this toolchain, so it appears in the
    lock with a version. That version is checkable where "the pip that ran" is
    not, and it is the only side of the producer pairing that can be recomputed.
    """
    problems = producer_problems(lock(package("pip", "26.2.1")), declaration())
    assert any("26.2.1" in problem and "26.1.1" in problem for problem in problems)
    assert producer_problems(lock(package("pip", "26.1.1")), declaration()) == ()


def test_a_producer_absent_from_the_lock_is_not_a_problem() -> None:
    """The pairing is a coherence requirement where the evidence exists."""
    assert producer_problems(lock(package("ruff", "0.15.14")), declaration()) == ()


# ---------------------------------------------------------------------------
# The target
# ---------------------------------------------------------------------------


def test_a_target_matching_the_runtime_contract_passes() -> None:
    """The declared target is a tripwire against the contract, not a second source."""
    assert (
        target_problems(
            target(),
            implementation="CPython",
            minor_line="3.14",
            architecture="AMD64",
            free_threaded=False,
        )
        == ()
    )


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"implementation": "PyPy"}, id="implementation"),
        pytest.param({"minor_line": "3.13"}, id="minor-line"),
        pytest.param({"architecture": "ARM64"}, id="architecture"),
        pytest.param({"free_threaded": True}, id="free-threaded"),
        pytest.param({"platform_tag": "win32"}, id="platform-tag"),
    ],
)
def test_a_target_the_contract_does_not_declare_is_reported(override: dict[str, object]) -> None:
    """A lock resolved for an interpreter nothing here runs is misleading, not merely stale."""
    assert target_problems(
        target(**override),
        implementation="CPython",
        minor_line="3.14",
        architecture="AMD64",
        free_threaded=False,
    )


def test_a_target_that_cannot_be_compared_becomes_a_finding_rather_than_an_exception() -> None:
    """A malformed minor line surfaces here, not as an error naming the wheel survey."""
    problems = target_problems(
        target(minor_line="three"),
        implementation="CPython",
        minor_line="three",
        architecture="AMD64",
        free_threaded=False,
    )
    assert problems


# ---------------------------------------------------------------------------
# Package entries
# ---------------------------------------------------------------------------


def test_a_well_formed_package_has_no_problems() -> None:
    """The control for the refusals below."""
    assert package_problems(package(), LOCK_PATH) == ()


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        pytest.param(package("Pip_Audit", "2.9.0"), "normalised", id="unnormalised-name"),
        pytest.param(package(version=None), "no version", id="no-version"),
        pytest.param(package(wheels=()), "no artefact", id="no-artefact"),
        pytest.param(package(direct_kind="vcs"), "vcs", id="vcs"),
        pytest.param(package(direct_kind="directory"), "directory", id="directory"),
        pytest.param(package(direct_kind="archive"), "archive", id="archive"),
    ],
)
def test_a_package_that_is_not_reproducible_is_reported(
    entry: LockedPackage, expected: str
) -> None:
    """Each of these installs something other than an artefact from the declared index.

    The versionless case is doubly bad: `pip-audit` reports such a package as
    skipped, and a skipped package under `--strict` fails the audit anyway — so
    catching it here names the reason rather than leaving somebody to read a
    scanner's exit code.
    """
    problems = package_problems(entry, LOCK_PATH)
    assert any(expected in problem for problem in problems)


def test_one_distribution_locked_twice_is_reported() -> None:
    """Two entries would let the lock hold two versions, with nothing saying which."""
    assert duplicate_packages((package("ruff", "0.1"), package("Ruff", "0.2"))) == ("ruff",)
    assert duplicate_packages((package("ruff"), package("mypy", "2.1.0"))) == ()


# ---------------------------------------------------------------------------
# Hashes
# ---------------------------------------------------------------------------


def test_a_hashed_artefact_passes() -> None:
    """The control."""
    assert hash_problems(package(), policy(), LOCK_PATH) == ()


@pytest.mark.parametrize(
    ("hashes", "expected"),
    [
        pytest.param((), "no hash", id="none"),
        pytest.param((("sha256", "a" * 63),), "hexadecimal", id="too-short"),
        pytest.param((("sha256", "a" * 65),), "hexadecimal", id="too-long"),
        pytest.param((("sha256", "A" * 64),), "hexadecimal", id="uppercase"),
        pytest.param((("sha256", "z" * 64),), "hexadecimal", id="not-hex"),
        pytest.param((("md5", "a" * 32),), "md5", id="md5"),
        pytest.param((("sha1", "a" * 40),), "sha1", id="sha1"),
        pytest.param((("sha512", "a" * 128),), "permitted algorithm", id="unpermitted"),
    ],
)
def test_an_artefact_without_a_usable_digest_is_reported(
    hashes: tuple[tuple[str, str], ...], expected: str
) -> None:
    """An unhashed artefact installs whatever the URL serves, and the lock still looks like one.

    `md5` and `sha1` are refused by name whatever the policy permits, so widening
    `hash_algorithms` cannot reach them.
    """
    entry = package(wheels=(wheel("ruff-0.15.14-py3-none-win_amd64.whl", hashes=hashes),))
    problems = hash_problems(entry, policy(), LOCK_PATH)
    assert any(expected in problem for problem in problems)


def test_an_unhashed_artefact_passes_when_the_policy_does_not_require_one() -> None:
    """The requirement is the declaration's, and the shape checks are this module's."""
    entry = package(wheels=(wheel("ruff-0.15.14-py3-none-win_amd64.whl", hashes=()),))
    assert hash_problems(entry, policy(require_hashes=False), LOCK_PATH) == ()


# ---------------------------------------------------------------------------
# Artefact locations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param("http://files.pythonhosted.org/a/b.whl", "http", id="plain-http"),
        pytest.param("file:///c/a/b.whl", "file", id="file"),
        pytest.param("https://evil.example/a/b.whl", "evil.example", id="another-host"),
        pytest.param(
            "https://user:pw@files.pythonhosted.org/a/b.whl", "credentials", id="userinfo"
        ),
    ],
)
def test_an_artefact_served_from_somewhere_unexpected_is_reported(url: str, expected: str) -> None:
    """A lock is several hundred URLs; one pointing elsewhere is the edit nobody reads.

    The userinfo case is the sharpest: a credential in a lock would be committed,
    published and cached, and it would look exactly like every other URL there.
    """
    entry = package(wheels=(wheel("ruff-0.15.14-py3-none-win_amd64.whl", url=url),))
    problems = artefact_problems(entry, target(), LOCK_PATH)
    assert any(expected in problem for problem in problems)


def test_an_artefact_given_as_a_filesystem_path_is_refused() -> None:
    """A lock resolvable only relative to one checkout is not a lock."""
    entry = package(
        wheels=(
            LockedFile(
                name="ruff-0.15.14-py3-none-win_amd64.whl",
                url=None,
                path="dist/ruff.whl",
                hashes=(("sha256", DIGEST),),
            ),
        )
    )
    problems = artefact_problems(entry, target(), LOCK_PATH)
    assert any("filesystem path" in problem for problem in problems)


def test_an_artefact_with_neither_a_url_nor_a_path_is_reported() -> None:
    """Nothing says where it would come from."""
    entry = package(
        wheels=(
            LockedFile(
                name="ruff-0.15.14-py3-none-win_amd64.whl",
                url=None,
                path=None,
                hashes=(("sha256", DIGEST),),
            ),
        )
    )
    assert any("no url" in problem for problem in artefact_problems(entry, target(), LOCK_PATH))


# ---------------------------------------------------------------------------
# Wheel compatibility, through Phase 018's matcher
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "serves"),
    [
        pytest.param("ruff-0.15.14-cp314-cp314-win_amd64.whl", True, id="exact-abi"),
        pytest.param("ruff-0.15.14-py3-none-any.whl", True, id="pure-python"),
        pytest.param("ruff-0.15.14-py3-none-win_amd64.whl", True, id="platform-but-abi-free"),
        pytest.param("ruff-0.15.14-cp313-cp313-win_amd64.whl", False, id="earlier-abi"),
        pytest.param("ruff-0.15.14-cp314-cp314-win32.whl", False, id="another-platform"),
        pytest.param("ruff-0.15.14-cp314-cp314t-win_amd64.whl", False, id="free-threaded-abi"),
    ],
)
def test_compatibility_is_decided_by_the_wheel_surveys_matcher(filename: str, serves: bool) -> None:
    """Called rather than reimplemented, and this is what pins the reuse.

    A second tag parser here would be a second thing to be wrong in a different
    way — and the free-threaded case is exactly where a substring search gets it
    backwards, because `cp314-cp314` looks like it would serve a `3.14t`
    interpreter and does not.
    """
    entry = package(wheels=(wheel(filename),))
    problems = compatibility_problems(entry, target(), LOCK_PATH)
    assert (problems == ()) is serves


def test_a_filename_disagreeing_with_its_entry_is_reported() -> None:
    """The check that catches a hand-edited lock.

    Editing a version in a package table is easy; editing it in every wheel
    filename beneath is not, and the two disagreeing is what shows.
    """
    entry = package("ruff", "0.15.14", wheels=(wheel("ruff-0.16.3-py3-none-win_amd64.whl"),))
    problems = compatibility_problems(entry, target(), LOCK_PATH)
    assert any("0.16.3" in problem for problem in problems)

    renamed = package("ruff", "0.15.14", wheels=(wheel("mypy-0.15.14-py3-none-any.whl"),))
    assert any(
        "mypy" in problem for problem in compatibility_problems(renamed, target(), LOCK_PATH)
    )


def test_a_package_with_no_wheel_at_all_is_not_a_compatibility_problem() -> None:
    """That question is `source_problems`', and it is answered with the gap bargain."""
    assert compatibility_problems(package(wheels=()), target(), LOCK_PATH) == ()


def test_an_unparsable_filename_becomes_a_finding() -> None:
    """Reported rather than raised, so one bad entry does not lose the whole run."""
    entry = package(wheels=(wheel("not-a-wheel.txt"),))
    assert compatibility_problems(entry, target(), LOCK_PATH)


# ---------------------------------------------------------------------------
# Source-only packages and the gap bargain
# ---------------------------------------------------------------------------


def test_a_package_with_no_serving_wheel_and_no_owner_is_reported() -> None:
    """A gap is not a failure. An unowned gap is."""
    entry = package(wheels=(wheel("ruff-0.15.14-cp313-cp313-win_amd64.whl"),))
    problems = source_problems((entry,), target(), policy(), (), delivered=20, total=320)
    assert any("no [[gap]]" in problem for problem in problems)


def test_a_gap_owned_by_an_undelivered_phase_passes() -> None:
    """Recorded and answered for, which is what the register is for."""
    entry = package(wheels=(wheel("ruff-0.15.14-cp313-cp313-win_amd64.whl"),))
    gap = Gap(name="ruff", phase=99, reason="upstream publishes no wheel for this line")
    assert source_problems((entry,), target(), policy(), (gap,), delivered=20, total=320) == ()


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        pytest.param(20, "already shipped", id="delivered"),
        pytest.param(321, "beyond the", id="beyond-the-programme"),
    ],
)
def test_a_gap_recorded_against_an_impossible_phase_is_reported(phase: int, expected: str) -> None:
    """A gap owned by a phase that has shipped is a gap nobody will now close."""
    entry = package(wheels=(wheel("ruff-0.15.14-cp313-cp313-win_amd64.whl"),))
    gap = Gap(name="ruff", phase=phase, reason="whatever")
    problems = source_problems((entry,), target(), policy(), (gap,), delivered=20, total=320)
    assert any(expected in problem for problem in problems)


def test_a_gap_recorded_for_a_package_that_has_a_wheel_is_reported() -> None:
    """The other direction, so the register cannot accumulate entries nobody needs."""
    gap = Gap(name="ruff", phase=99, reason="stale")
    problems = source_problems((package(),), target(), policy(), (gap,), delivered=20, total=320)
    assert any("nothing to do" in problem for problem in problems)


def test_a_source_distribution_is_permitted_when_the_policy_allows_one() -> None:
    """`allow_source` is the declaration's to set, and it is false in this repository."""
    entry = package(
        wheels=(wheel("ruff-0.15.14-cp313-cp313-win_amd64.whl"),),
        sdist=wheel("ruff-0.15.14.tar.gz"),
    )
    assert (
        source_problems((entry,), target(), policy(allow_source=True), (), delivered=20, total=320)
        == ()
    )


# ---------------------------------------------------------------------------
# Version bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "specifier", "verdict"),
    [
        pytest.param("8.1", ">=8.0", True, id="clears"),
        pytest.param("8.0", ">=8.0", True, id="equals"),
        pytest.param("7.9", ">=8.0", False, id="below"),
        pytest.param("0.15.14", ">= 0.6", True, id="spaced"),
        pytest.param("1.0", "~=1.0", None, id="compatible-release"),
        pytest.param("1.0", "==1.0", None, id="exact"),
        pytest.param("1.0", "!=2.0", None, id="exclusion"),
        pytest.param("1.0", "<2.0", None, id="upper-bound"),
        pytest.param("1.0", "", None, id="empty"),
    ],
)
def test_a_bound_either_decides_or_refuses_with_no_third_outcome(
    version: str, specifier: str, verdict: bool | None
) -> None:
    """This is where the module deliberately differs from the inventory.

    `inventory._satisfies` returns True for anything it cannot read, which is
    right there: a false disagreement would make a gate cry wolf about a version
    nobody chose. It is wrong here. A lock exists to say exactly what will be
    installed, so a bound nobody can evaluate is reported rather than assumed
    satisfied.
    """
    assert satisfies_bound(version, specifier) is verdict


# ---------------------------------------------------------------------------
# The declared roots, in both directions
# ---------------------------------------------------------------------------


def test_roots_agreeing_with_the_project_file_pass() -> None:
    """The control."""
    assert declaration_problems(declaration(), (declared(),)) == ()


def test_a_tool_declared_in_the_project_and_missing_from_the_roots_is_reported() -> None:
    """It would be unlocked while appearing declared."""
    problems = declaration_problems(declaration(), (declared(), declared("mypy", ">=1.11")))
    assert any("mypy" in problem and "does not list it" in problem for problem in problems)


def test_a_root_the_project_no_longer_declares_is_reported() -> None:
    """The direction that earns its keep.

    pip records no dependency edges, so a root removed from the project and left
    in the declaration is otherwise undetectable offline. This is the only check
    that sees it.
    """
    problems = declaration_problems(declaration(roots=("ruff>=0.6", "black>=24.0")), (declared(),))
    assert any("black" in problem for problem in problems)


def test_a_root_whose_bound_has_moved_is_reported() -> None:
    """The declaration records what a resolution was performed from."""
    problems = declaration_problems(declaration(), (declared("ruff", ">=0.9"),))
    assert any(">=0.9" in problem for problem in problems)


def test_a_root_this_reader_cannot_name_becomes_a_finding() -> None:
    """Reported rather than raised, like every other malformed value here."""
    assert declaration_problems(declaration(roots=("==1.0",)), (declared(),))


# ---------------------------------------------------------------------------
# Coverage of the declared toolchain
# ---------------------------------------------------------------------------


def test_every_declared_tool_must_be_locked() -> None:
    """A tool in the extra and not in the lock is one nobody pinned."""
    problems = coverage_problems(lock(), (declared(), declared("mypy", ">=1.11")))
    assert any("mypy" in problem and "omits it" in problem for problem in problems)


def test_a_locked_version_below_its_declared_bound_is_reported() -> None:
    """The lock would install something the project says is too old."""
    problems = coverage_problems(lock(package("ruff", "0.5")), (declared(),))
    assert any("0.5" in problem for problem in problems)


def test_a_bound_that_cannot_be_decided_is_reported_rather_than_assumed() -> None:
    """On ambiguity, refuse."""
    problems = coverage_problems(lock(), (declared("ruff", "~=0.6"),))
    assert any("does not decide" in problem for problem in problems)


def test_entries_from_other_registers_are_not_treated_as_declared_tools() -> None:
    """Only the project file's development extra is the toolchain."""
    assert (
        coverage_problems(lock(), (declared(scope=CONTINUOUS_INTEGRATION, source="ci.yml"),)) == ()
    )


def test_a_runtime_dependency_is_not_a_development_one() -> None:
    """The default scope answers for the development lock and nothing else.

    Without this the two locks would be checked against one register, and a
    runtime dependency would be reported as missing from the toolchain lock that
    was never supposed to contain it.
    """
    assert coverage_problems(lock(), (declared("psutil", ">=7.2.2", scope=RUNTIME),)) == ()


def test_a_declared_runtime_dependency_the_runtime_lock_omits_is_reported() -> None:
    """The check Phase 024 found missing, stated as the case that was passing.

    ``psutil`` was added to ``project.dependencies`` and to the declaration's
    ``[runtime] roots`` while ``pylock.toml`` was left alone, and the gate returned
    a clean ``passed``: every runtime finding was about whether the lock was sound
    in itself, and none asked whether it held what had been declared.
    """
    problems = coverage_problems(
        lock(), (declared("psutil", ">=7.2.2", scope=RUNTIME),), scope=RUNTIME
    )
    assert any("psutil" in problem and "omits it" in problem for problem in problems)


def test_a_runtime_lock_covering_its_declaration_passes() -> None:
    """The other direction, so the check above is not merely always-failing."""
    assert (
        coverage_problems(
            lock(package("psutil", "7.2.2")),
            (declared("psutil", ">=7.2.2", scope=RUNTIME),),
            scope=RUNTIME,
        )
        == ()
    )


# ---------------------------------------------------------------------------
# The other registers
# ---------------------------------------------------------------------------


def test_a_pin_agreeing_with_the_lock_passes() -> None:
    """The control."""
    pin = declared(
        "ruff", "0.15.14", scope=CONTINUOUS_INTEGRATION, source="quality.yml", resolution=PINNED
    )
    assert register_problems(lock(), (pin,)) == ()


def test_a_pin_disagreeing_with_the_lock_names_the_replacement() -> None:
    """The message is the upgrade procedure's second step, so it has to be exact."""
    pin = declared(
        "ruff", "0.16.3", scope=CONTINUOUS_INTEGRATION, source="quality.yml", resolution=PINNED
    )
    problems = register_problems(lock(), (pin,))
    assert any("write ruff==0.15.14" in problem for problem in problems)


def test_a_pin_for_something_the_lock_does_not_carry_is_reported() -> None:
    """CI would install a tool the lock says nothing about."""
    pin = declared(
        "black", "24.0", scope=CONTINUOUS_INTEGRATION, source="quality.yml", resolution=PINNED
    )
    assert any("does not lock" in problem for problem in register_problems(lock(), (pin,)))


def test_a_mirrored_hook_revision_is_compared_against_the_locked_tool() -> None:
    """The disagreement that bites hardest, because both halves pass on their own.

    A developer commits through a hook calling a file clean and watches CI call it
    dirty, with no diff between them to explain why.
    """
    hook = declared(
        "astral-sh/ruff-pre-commit",
        "v0.16.3",
        scope="hook",
        source=".pre-commit-config.yaml",
        ecosystem=PRE_COMMIT,
        resolution=PINNED,
    )
    problems = register_problems(lock(), (hook,))
    assert any("would disagree" in problem for problem in problems)


def test_a_hook_that_mirrors_nothing_is_left_alone() -> None:
    """A repository without the mirror suffix wraps no distribution here."""
    hook = declared(
        "pre-commit/pre-commit-hooks",
        "v6.0.0",
        scope="hook",
        source=".pre-commit-config.yaml",
        ecosystem=PRE_COMMIT,
        resolution=PINNED,
    )
    assert register_problems(lock(), (hook,)) == ()


# ---------------------------------------------------------------------------
# The runtime pairing
# ---------------------------------------------------------------------------


def test_no_runtime_dependency_and_no_runtime_lock_is_the_state_today() -> None:
    """Passes silently, which is correct while `project.dependencies` is empty."""
    assert runtime_problems(declaration(), (declared(),)) == ()


def test_a_runtime_dependency_without_a_runtime_lock_fails() -> None:
    """The forward hook. Phase 021 cannot introduce one without the lock beside it."""
    runtime = declared("httpx", ">=0.27", scope="runtime")
    problems = runtime_problems(declaration(), (declared(), runtime))
    assert any("httpx" in problem for problem in problems)


def test_a_runtime_dependency_with_a_runtime_lock_passes() -> None:
    """The obligation is discharged by producing the lock, which is the point.

    The roots must agree too, which is Phase 021's addition: once a runtime lock
    exists, `[runtime] roots` and `project.dependencies` are compared in both
    directions exactly as the development pair already was.
    """
    runtime = declared("httpx", ">=0.27", scope="runtime")
    agreed = declaration(runtime_locked=True, runtime_roots=("httpx>=0.27",))
    assert runtime_problems(agreed, (declared(), runtime)) == ()


def test_a_runtime_root_the_project_no_longer_declares_is_reported() -> None:
    """The direction that earns its keep, for the runtime pair as for the dev one.

    pip records no dependency edges, so a root removed from `project.dependencies`
    and left in the declaration is undetectable offline by any other means.
    """
    runtime = declared("httpx", ">=0.27", scope="runtime")
    stale = declaration(runtime_locked=True, runtime_roots=("httpx>=0.27", "orjson>=3.10"))
    problems = runtime_problems(stale, (declared(), runtime))
    assert any("orjson" in problem and "no longer declares" in problem for problem in problems)


def test_a_runtime_dependency_missing_from_the_declared_roots_is_reported() -> None:
    """And the forward direction, which catches a dependency added without a relock."""
    runtime = declared("httpx", ">=0.27", scope="runtime")
    incomplete = declaration(runtime_locked=True, runtime_roots=())
    problems = runtime_problems(incomplete, (declared(), runtime))
    assert any("httpx" in problem and "does not record it" in problem for problem in problems)


def test_the_project_itself_is_exempt_from_the_unexpected_check_when_installed() -> None:
    """Since Phase 021 `bootstrap.ps1` installs GLOBIN, and no lock resolved it.

    Declared rather than inferred: passing `project=""` means the project is not
    expected to be installed, and finding it then IS a difference worth reporting.
    """
    present = {"ruff": "0.15.14", "globin": "0.1.0"}
    assert environment_problems([lock()], present, ("pip",), project="globin") == ()
    assert environment_problems([lock()], present, ("pip",), project="") != ()


def test_two_locks_are_compared_as_one_expectation() -> None:
    """Comparing against one lock alone would report the other's packages as unexpected.

    This is what Phase 021 changed: the environment now holds the union of the
    development and the runtime lock, and either one on its own describes a
    machine that does not exist.
    """
    runtime = Lock(
        path="pylock.toml",
        lock_version="1.0",
        created_by="pip",
        packages=(package("numpy", "2.5.2"),),
    )
    installed = {"ruff": "0.15.14", "numpy": "2.5.2"}
    assert environment_problems([lock(), runtime], installed, ("pip",)) == ()


def test_two_locks_disagreeing_about_one_version_is_reported_as_a_declaration_defect() -> None:
    """The first lock to name a distribution owns the expectation, and the clash is named.

    A package locked twice at two versions cannot be satisfied by any environment,
    so reporting it as an environment difference would send a reader to fix the
    wrong file.
    """
    runtime = Lock(
        path="pylock.toml",
        lock_version="1.0",
        created_by="pip",
        packages=(package("ruff", "0.16.0"),),
    )
    problems = environment_problems([lock(), runtime], {"ruff": "0.15.14"}, ("pip",))
    assert any(
        "pylock.dev.toml locks 0.15.14 and pylock.toml locks 0.16.0" in problem
        for problem in problems
    )


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


def test_an_environment_matching_the_lock_passes() -> None:
    """The control."""
    assert environment_problems([lock()], {"ruff": "0.15.14"}, ("pip",)) == ()


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        pytest.param({}, "is not installed", id="missing"),
        pytest.param({"ruff": "0.16.3"}, "0.16.3 is installed", id="wrong-version"),
        pytest.param({"ruff": "0.15.14", "black": "24.0"}, "does not lock it", id="unexpected"),
    ],
)
def test_an_environment_differing_from_the_lock_is_reported(
    installed: dict[str, str], expected: str
) -> None:
    """Three differences, each with its own sentence, because each needs a different fix."""
    problems = environment_problems([lock()], installed, ("pip",))
    assert any(expected in problem for problem in problems)


def test_a_seeded_distribution_is_exempt_from_the_unexpected_check() -> None:
    """`venv` seeds pip before anything is installed.

    Without the exemption a bootstrap that failed partway would report "one
    unexpected package" alongside the forty-eight that are genuinely missing,
    which buries the real finding.
    """
    assert environment_problems([lock()], {"ruff": "0.15.14", "pip": "26.1.1"}, ("pip",)) == ()
    assert environment_problems([lock()], {"ruff": "0.15.14", "pip": "26.1.1"}, ())


def test_the_environment_comparison_normalises_both_sides() -> None:
    """`importlib.metadata` reports a name as the distribution spells it."""
    parsed = lock(package("pip-audit", "2.9.0"))
    assert environment_problems([parsed], {"pip_audit": "2.9.0"}, ()) == ()


# ---------------------------------------------------------------------------
# Reading the declaration
# ---------------------------------------------------------------------------


def test_the_declaration_parses_into_what_it_says() -> None:
    """Field for field, so a silently dropped table is visible."""
    parsed = parse_declaration(DECLARATION)
    assert parsed.producer.tool == "pip"
    assert parsed.producer.experimental is True
    assert parsed.target.artefact_host == "files.pythonhosted.org"
    assert parsed.target.locked == "2026-08-16"
    assert parsed.policy.hash_algorithms == ("sha256",)
    assert parsed.policy.allow_source is False
    assert parsed.roots == ("ruff>=0.6",)
    assert parsed.runtime_locked is False
    assert parsed.seeded == ("pip",)
    assert parsed.gaps == ()


def test_a_recorded_gap_is_read() -> None:
    """The register is an array of tables, and an absent array is not an error."""
    parsed = parse_declaration(
        DECLARATION + '\n[[gap]]\nname = "example"\nphase = 99\nreason = "no wheel upstream"\n'
    )
    assert parsed.gaps == (Gap(name="example", phase=99, reason="no wheel upstream"),)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(("schema = 1", "schema = 2"), "schema", id="unknown-schema"),
        pytest.param(
            ("locked = 2026-08-16", 'locked = "2026-08-16"'), "bare TOML", id="quoted-date"
        ),
        pytest.param(('tool = "pip"', "tool = 1"), "non-empty string", id="tool-not-a-string"),
        pytest.param(
            ("experimental = true", "experimental = 1"), "true or false", id="flag-not-a-boolean"
        ),
        pytest.param(('roots = ["ruff>=0.6"]', "roots = []"), "non-empty list", id="empty-roots"),
        pytest.param(
            ('hash_algorithms = ["sha256"]', 'hash_algorithms = ["crc32"]'),
            "digest width",
            id="unknown-algorithm",
        ),
        pytest.param(("[policy]", "[unused]"), "[policy]", id="missing-table"),
    ],
)
def test_a_declaration_this_reader_cannot_use_is_refused(
    mutation: tuple[str, str], expected: str
) -> None:
    """Refused with a sentence naming what to fix, rather than read partly.

    The unknown-algorithm case is the one worth reading twice: this module knows
    the digest width of what it permits, so an algorithm it cannot check the shape
    of is refused rather than having its values trusted.
    """
    old, new = mutation
    with pytest.raises(LockError, match=expected):
        parse_declaration(DECLARATION.replace(old, new))


def test_a_declaration_that_is_not_toml_is_refused() -> None:
    """The first thing that can go wrong."""
    with pytest.raises(LockError, match="valid TOML"):
        parse_declaration("this is not toml either")


@pytest.mark.parametrize(
    "phase",
    [
        pytest.param("0", id="zero"),
        pytest.param("true", id="boolean"),
        pytest.param('"9"', id="string"),
    ],
)
def test_a_gap_phase_that_is_not_a_positive_integer_is_refused(phase: str) -> None:
    """A boolean is an integer in Python, and would otherwise pass as phase one."""
    text = DECLARATION + f'\n[[gap]]\nname = "x"\nphase = {phase}\nreason = "y"\n'
    with pytest.raises(LockError, match="positive integer"):
        parse_declaration(text)
