"""Whether a lock could be built from local bytes, and the safety around trying.

Every artefact below is a literal or a file written into `tmp_path`. Nothing is
fetched, nothing is installed, and no environment is created -- the failure
vocabulary is driven entirely through injected seams, which is what lets a
timeout be tested by a double that raises immediately rather than by a test that
sleeps.

The assertions that carry the most weight are three refusals. A corrupt cached
artefact proves **left in place** rather than deleted or re-fetched. A missing
artefact proves to fail rather than reach an index. And `cleanroom_problems`
proves to refuse every path that is not a freshly-created scratch room --
including, specifically, a `.venv`.
"""

import hashlib
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from packaging.pylock import Pylock

from tests.contract.test_roadmap_contract import LAST_COMPLETED_PHASE
from tools.quality.materialize.cache import CacheError, Wheelhouse, corrupt_paths
from tools.quality.materialize.cleanroom import (
    SCRATCH_PREFIX,
    CleanRoom,
    CleanRoomFault,
    cleanroom_problems,
    installed_from,
)
from tools.quality.materialize.cli import main as cli_main
from tools.quality.materialize.gate import (
    DELIVERED_PHASE,
    commit_of,
    declared_target,
    run_materialize,
    selections_from,
)
from tools.quality.materialize.manifest import (
    MANIFEST_NAME,
    REASONS,
    SCHEMA,
    SCHEMA_VERSION,
    MaterializeManifestError,
    build,
    digest,
    load,
    render,
)
from tools.quality.materialize.plan import (
    PlanState,
    cache_key,
    offline_problems,
    plan_for,
    usable_digest,
)

SHA = "a" * 64
OTHER = "b" * 64

needs_select = pytest.mark.skipif(
    not hasattr(Pylock, "select"),
    reason=(
        "packaging.Pylock.select arrived in 26.1, and this interpreter carries an "
        "older packaging than pyproject.toml declares"
    ),
)
"""Guards the tests that ask the reference implementation to choose an artefact.

Guarding on the **capability** rather than on a version string or a CI variable,
which is what `docs/TESTING_STRATEGY.md` requires: the skip reason is a true
statement about this machine. An environment carrying packaging 26.0 does not
satisfy the `>=26.3` floor `pyproject.toml` declares, so these tests are not
being weakened -- they are being run only where the declared contract holds. CI
pins 26.3 explicitly in every job that runs the suite, so they run there.
"""


def selection(
    name: str = "thing",
    version: str = "1.0",
    filename: str = "thing-1.0-py3-none-any.whl",
    hashes: Sequence[tuple[str, str]] = (("sha256", SHA),),
    *,
    is_source: bool = False,
) -> tuple[str, str, str, Sequence[tuple[str, str]], bool]:
    return (name, version, filename, hashes, is_source)


# ---------------------------------------------------------------------------
# Addressing
# ---------------------------------------------------------------------------


def test_an_artefact_is_addressed_by_the_digest_the_lock_names() -> None:
    key = cache_key(name="thing", version="1.0", filename="w.whl", hashes=(("sha256", SHA),))
    assert key is not None
    assert key.relative() == "thing/1.0/aa/w.whl"


@pytest.mark.parametrize(
    "algorithm",
    [
        pytest.param("md5", id="md5"),
        pytest.param("sha1", id="sha1"),
        pytest.param("sha224", id="sha224"),
    ],
)
def test_a_weak_digest_cannot_address_an_artefact(algorithm: str) -> None:
    """Refused by name, and refused regardless of what a policy file permits."""
    assert usable_digest(((algorithm, SHA),)) is None


def test_sha256_is_preferred_when_several_are_recorded() -> None:
    chosen = usable_digest((("sha512", OTHER), ("sha256", SHA)))
    assert chosen == ("sha256", SHA)


def test_an_unfamiliar_but_strong_digest_is_accepted() -> None:
    """Refusing one this repository has not heard of would refuse a stronger one."""
    assert usable_digest((("sha3_256", SHA),)) == ("sha3_256", SHA)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def test_an_artefact_present_and_correct_is_satisfiable() -> None:
    key = cache_key(
        name="thing",
        version="1.0",
        filename="thing-1.0-py3-none-any.whl",
        hashes=(("sha256", SHA),),
    )
    assert key is not None
    plan = plan_for((selection(),), {key.relative(): SHA}, allow_source=False)
    assert plan.state() is PlanState.SATISFIABLE
    assert offline_problems(plan) == ()


def test_an_artefact_nobody_fetched_fails_rather_than_reaching_an_index() -> None:
    """The offline guarantee, at the level of the verdict."""
    plan = plan_for((selection(),), {}, allow_source=False)
    assert plan.state() is PlanState.INCOMPLETE
    assert "not in the wheelhouse" in offline_problems(plan)[0]


def test_bytes_that_are_not_the_bytes_the_lock_names_are_corrupt() -> None:
    key = cache_key(
        name="thing",
        version="1.0",
        filename="thing-1.0-py3-none-any.whl",
        hashes=(("sha256", SHA),),
    )
    assert key is not None
    plan = plan_for((selection(),), {key.relative(): OTHER}, allow_source=False)
    assert plan.state() is PlanState.CORRUPT


def test_a_lock_offering_nothing_for_this_target_is_incompatible() -> None:
    plan = plan_for((selection(filename=""),), {}, allow_source=False)
    assert plan.state() is PlanState.INCOMPATIBLE


def test_a_source_distribution_is_refused_unless_policy_allows_it() -> None:
    forbidden = plan_for((selection(is_source=True),), {}, allow_source=False)
    assert forbidden.state() is PlanState.SOURCE_ONLY
    allowed = plan_for((selection(is_source=True),), {}, allow_source=True)
    assert allowed.state() is PlanState.INCOMPLETE


def test_an_artefact_with_no_usable_digest_could_not_be_trusted() -> None:
    plan = plan_for((selection(hashes=(("md5", SHA),)),), {}, allow_source=False)
    assert plan.state() is PlanState.UNHASHED


def test_the_worst_state_decides_the_plan() -> None:
    """Corruption outranks absence: it means something here is wrong."""
    key = cache_key(
        name="bad",
        version="1.0",
        filename="bad-1.0-py3-none-any.whl",
        hashes=(("sha256", SHA),),
    )
    assert key is not None
    plan = plan_for(
        (
            selection(name="bad", filename="bad-1.0-py3-none-any.whl"),
            selection(name="absent", filename="absent-1.0-py3-none-any.whl"),
        ),
        {key.relative(): OTHER},
        allow_source=False,
    )
    assert plan.state() is PlanState.CORRUPT


def test_a_plan_record_carries_no_url() -> None:
    """A lock holds hundreds; a manifest is a summary."""
    plan = plan_for((selection(),), {}, allow_source=False)
    assert "http" not in repr(plan.as_record())


# ---------------------------------------------------------------------------
# The wheelhouse
# ---------------------------------------------------------------------------


def test_the_bytes_are_hashed_rather_than_the_filename_trusted(tmp_path: Path) -> None:
    """A wheelhouse is a directory somebody can write to."""
    payload = b"the real artefact"
    real = hashlib.sha256(payload).hexdigest()
    key = cache_key(name="thing", version="1.0", filename="w.whl", hashes=(("sha256", real),))
    assert key is not None
    target = tmp_path / Path(key.relative())
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)

    assert Wheelhouse(root=tmp_path).digests((key,)) == {key.relative(): real}


def test_an_artefact_nobody_fetched_is_absent_from_the_mapping(tmp_path: Path) -> None:
    """So that "not fetched" and "fetched and wrong" cannot be confused."""
    key = cache_key(name="thing", version="1.0", filename="w.whl", hashes=(("sha256", SHA),))
    assert key is not None
    assert Wheelhouse(root=tmp_path).digests((key,)) == {}


def test_a_weak_algorithm_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    from tools.quality.materialize.plan import CacheKey

    key = CacheKey(name="t", version="1", algorithm="md5", digest=SHA, filename="w.whl")
    with pytest.raises(CacheError):
        Wheelhouse(root=tmp_path).digests((key,))


def test_a_corrupt_artefact_is_reported_and_left_in_place(tmp_path: Path) -> None:
    """Deleting the evidence of a corruption is how the diagnosis is lost."""
    key = cache_key(name="thing", version="1.0", filename="w.whl", hashes=(("sha256", SHA),))
    assert key is not None
    target = tmp_path / Path(key.relative())
    target.parent.mkdir(parents=True)
    target.write_bytes(b"wrong")

    assert corrupt_paths((key,), {key.relative(): OTHER}) == (key.relative(),)
    assert target.is_file()


def test_an_empty_wheelhouse_lists_nothing(tmp_path: Path) -> None:
    assert list(Wheelhouse(root=tmp_path / "absent").entries()) == []


def test_the_wheelhouse_lists_what_it_holds(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "w.whl").write_bytes(b"x")
    assert [path.name for path in Wheelhouse(root=tmp_path).entries()] == ["w.whl"]


# ---------------------------------------------------------------------------
# The clean-room safety refusals
# ---------------------------------------------------------------------------


def test_a_freshly_created_scratch_room_may_be_removed(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    target = scratch / f"{SCRATCH_PREFIX}abc"
    target.mkdir(parents=True)
    assert (
        cleanroom_problems(
            target=target,
            repo_root=tmp_path / "repo",
            scratch_root=scratch,
            is_reparse_point=False,
        )
        == ()
    )


def test_a_virtual_environment_is_refused_however_it_is_reached(tmp_path: Path) -> None:
    """The refusal this function exists for."""
    repo = tmp_path / "repo"
    venv = repo / ".venv"
    venv.mkdir(parents=True)
    problems = cleanroom_problems(
        target=venv,
        repo_root=repo,
        scratch_root=tmp_path / "scratch",
        is_reparse_point=False,
    )
    assert problems
    assert any("inside the repository" in problem for problem in problems)


@pytest.mark.parametrize(
    ("name", "reparse", "expected"),
    [
        pytest.param(f"{SCRATCH_PREFIX}ok", True, "link", id="a-link"),
        pytest.param("not-prefixed", False, SCRATCH_PREFIX, id="wrong-name"),
    ],
)
def test_a_target_that_fails_any_single_check_is_refused(
    tmp_path: Path, name: str, reparse: bool, expected: str
) -> None:
    """Four redundant checks, and any one of them alone refuses."""
    scratch = tmp_path / "scratch"
    target = scratch / name
    target.mkdir(parents=True)
    problems = cleanroom_problems(
        target=target,
        repo_root=tmp_path / "repo",
        scratch_root=scratch,
        is_reparse_point=reparse,
    )
    assert any(expected in problem for problem in problems)


def test_the_scratch_root_itself_is_never_the_room(tmp_path: Path) -> None:
    scratch = tmp_path / f"{SCRATCH_PREFIX}root"
    scratch.mkdir()
    problems = cleanroom_problems(
        target=scratch,
        repo_root=tmp_path / "repo",
        scratch_root=scratch,
        is_reparse_point=False,
    )
    assert any("scratch root itself" in problem for problem in problems)


def test_a_sibling_with_a_shared_prefix_is_not_inside(tmp_path: Path) -> None:
    """Compared with relative_to rather than by string prefix."""
    (tmp_path / "globin").mkdir()
    target = tmp_path / f"globin{SCRATCH_PREFIX}x"
    target.mkdir()
    problems = cleanroom_problems(
        target=target,
        repo_root=tmp_path / "repo",
        scratch_root=tmp_path / "globin",
        is_reparse_point=False,
    )
    assert any("not beneath the scratch root" in problem for problem in problems)


# ---------------------------------------------------------------------------
# The clean-room process seam
# ---------------------------------------------------------------------------


class _Runner:
    """A process runner that records what it was asked to start.

    A class rather than a closure so that `calls` is a typed attribute, which
    lets a test assert what was *never* started without reaching for an ignore.
    """

    def __init__(
        self, status: int = 0, output: str = "", raises: BaseException | None = None
    ) -> None:
        self.calls: list[Sequence[str]] = []
        self.status = status
        self.output = output
        self.raises = raises

    def __call__(self, argv: Sequence[str], *, cwd: Path, timeout: float) -> tuple[int, str]:
        del cwd, timeout
        self.calls.append(argv)
        if self.raises is not None:
            raise self.raises
        return (self.status, self.output)


def runner(status: int = 0, output: str = "", raises: BaseException | None = None) -> _Runner:
    """A recording runner, so a test can assert what was never started."""
    return _Runner(status=status, output=output, raises=raises)


def test_an_environment_the_interpreter_refuses_is_reported(tmp_path: Path) -> None:
    room = CleanRoom(root=tmp_path, runner=runner(status=1))
    outcome = room.create(Path("python.exe"))
    assert outcome.fault is CleanRoomFault.ENVIRONMENT_REFUSED


def test_an_install_that_outlives_its_bound_is_reported(tmp_path: Path) -> None:
    """Driven by a double that raises immediately, never by sleeping."""
    expired = subprocess.TimeoutExpired(cmd="pip", timeout=1.0)
    room = CleanRoom(root=tmp_path, runner=runner(raises=expired))
    outcome = room.install(tmp_path / "pylock.toml", None)
    assert outcome.fault is CleanRoomFault.INSTALL_TIMED_OUT


def test_an_interrupted_install_says_the_environment_is_half_built(tmp_path: Path) -> None:
    room = CleanRoom(root=tmp_path, runner=runner(raises=KeyboardInterrupt()))
    outcome = room.install(tmp_path / "pylock.toml", None)
    assert outcome.fault is CleanRoomFault.INSTALL_INTERRUPTED
    assert "half-built" in outcome.detail


def test_a_failed_install_is_reported(tmp_path: Path) -> None:
    room = CleanRoom(root=tmp_path, runner=runner(status=2))
    assert room.install(tmp_path / "pylock.toml", None).fault is CleanRoomFault.INSTALL_FAILED


def test_a_wheelhouse_makes_the_install_refuse_the_index(tmp_path: Path) -> None:
    """`--no-index` and `--find-links` together, so a gap fails rather than fetches."""
    run = runner()
    room = CleanRoom(root=tmp_path, runner=run)
    room.install(tmp_path / "pylock.toml", tmp_path / "house")
    argv = list(run.calls[0])
    assert "--no-index" in argv
    assert "--find-links" in argv


def test_no_child_is_ever_started_through_a_shell(tmp_path: Path) -> None:
    """A list argv has no quoting surface and no injection surface."""
    run = runner()
    room = CleanRoom(root=tmp_path, runner=run)
    room.create(Path("python.exe"))
    argv = run.calls[0]
    assert isinstance(argv, list)
    assert all(isinstance(word, str) for word in argv)


def test_a_probe_that_fails_is_reported(tmp_path: Path) -> None:
    room = CleanRoom(root=tmp_path, runner=runner(status=1))
    outcome, output = room.probe()
    assert outcome.fault is CleanRoomFault.PROBE_DISAGREED
    assert output == ""


def test_a_probe_that_outlives_its_bound_is_reported(tmp_path: Path) -> None:
    expired = subprocess.TimeoutExpired(cmd="pip", timeout=1.0)
    room = CleanRoom(root=tmp_path, runner=runner(raises=expired))
    outcome, _ = room.probe()
    assert outcome.fault is CleanRoomFault.INSTALL_TIMED_OUT


def test_a_successful_probe_returns_what_was_installed(tmp_path: Path) -> None:
    room = CleanRoom(root=tmp_path, runner=runner(output="numpy==2.5.2\n"))
    outcome, output = room.probe()
    assert outcome.ok is True
    assert installed_from(output) == {"numpy": "2.5.2"}


def test_a_transcript_line_that_is_not_a_pin_is_skipped() -> None:
    """Pip emits editable and direct-reference lines in other shapes."""
    assert installed_from("-e git+https://x#egg=y\nnumpy==2.5.2\nrubbish\n") == {"numpy": "2.5.2"}


def test_an_underscored_name_is_normalised_on_the_way_in() -> None:
    assert installed_from("typing_extensions==4.0\n") == {"typing-extensions": "4.0"}


# ---------------------------------------------------------------------------
# The declared target
# ---------------------------------------------------------------------------


def test_the_target_is_read_from_the_declaration_and_not_this_interpreter(
    repo_root: Path,
) -> None:
    """The whole reason this gate returns the same verdict on every runner."""
    tags, allow_source, problem = declared_target(repo_root)
    assert problem == ""
    assert allow_source is False
    assert any(tag.platform == "win_amd64" for tag in tags)
    assert tags[0].interpreter.startswith("cp3")


def test_the_tags_are_ordered_because_order_is_preference(repo_root: Path) -> None:
    """PEP 425 tag order is priority, and `Tag` is deliberately unorderable."""
    tags, _, _ = declared_target(repo_root)
    assert isinstance(tags, tuple)
    assert tags[0].abi.startswith("cp")


def test_a_missing_declaration_is_reported_rather_than_guessed(tmp_path: Path) -> None:
    tags, _, problem = declared_target(tmp_path)
    assert tags == ()
    assert "could not be read" in problem


@needs_select
def test_the_committed_lock_resolves_against_the_declared_target(repo_root: Path) -> None:
    tags, _, _ = declared_target(repo_root)
    selections, problem = selections_from(
        (repo_root / "pylock.toml").read_text(encoding="utf-8"), tags
    )
    assert problem == ""
    assert len(selections) > 5
    assert all(filename for _, _, filename, _, _ in selections)


def test_a_lock_that_is_not_toml_is_reported(repo_root: Path) -> None:
    tags, _, _ = declared_target(repo_root)
    _, problem = selections_from("not toml {{{", tags)
    assert "could not be read" in problem


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def document() -> dict[str, object]:
    return build(run={"commit": "x"}, findings={}, verdict={"verdict": "passed"})


def test_a_manifest_seals_itself_with_its_own_digest() -> None:
    assert load(render(document()))["schema"] == SCHEMA


def test_a_manifest_that_was_edited_is_refused() -> None:
    tampered = document()
    tampered["run"] = {"commit": "y"}
    with pytest.raises(MaterializeManifestError):
        load(render(tampered))


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("not json", id="not-json"),
        pytest.param("[]", id="not-an-object"),
        pytest.param('{"schema": "other"}', id="another-schema"),
    ],
)
def test_a_document_this_reader_cannot_use_is_refused(text: str) -> None:
    with pytest.raises(MaterializeManifestError):
        load(text)


def test_a_version_this_reader_does_not_implement_is_refused() -> None:
    stale = document()
    stale["schema_version"] = SCHEMA_VERSION + 1
    stale["digest"] = digest(stale)
    with pytest.raises(MaterializeManifestError):
        load(render(stale))


def test_the_reason_set_is_closed() -> None:
    assert all(reason.startswith("MATERIALIZE_") for reason in REASONS)


# ---------------------------------------------------------------------------
# The gate, end to end
# ---------------------------------------------------------------------------


def tree(root: Path, *, lock: str, allow_source: bool = False) -> None:
    """A repository just complete enough for the gate to judge it."""
    policy = root / "docs" / "engineering"
    policy.mkdir(parents=True)
    (policy / "lock-policy.toml").write_text(
        "[target]\n"
        'minor_line = "3.14"\n'
        'platform_tag = "win_amd64"\n'
        "free_threaded = false\n"
        "[policy]\n"
        f"allow_source = {str(allow_source).lower()}\n",
        encoding="utf-8",
    )
    (root / "pylock.toml").write_text(lock, encoding="utf-8")


def one_wheel(digest_value: str) -> str:
    """A minimal valid lock naming exactly one wheel."""
    return (
        'lock-version = "1.0"\n'
        'created-by = "globin-tests"\n'
        "[[packages]]\n"
        'name = "thing"\n'
        'version = "1.0"\n'
        "[[packages.wheels]]\n"
        'name = "thing-1.0-py3-none-any.whl"\n'
        'url = "https://files.pythonhosted.org/thing-1.0-py3-none-any.whl"\n'
        f'hashes = {{sha256 = "{digest_value}"}}\n'
    )


def test_an_empty_wheelhouse_is_unmeasured_rather_than_failed(tmp_path: Path) -> None:
    """The distinction that keeps a fresh clone from being red.

    Artefacts are hundreds of megabytes and are not committed, so nothing has
    been established rather than an absence having been established. `drift`
    draws exactly this line with an unrecorded baseline, and exits 3 too.
    """
    tree(tmp_path, lock=one_wheel(SHA))
    assert run_materialize(tmp_path, wheelhouse=tmp_path / "house") == 3


@needs_select
def test_a_populated_and_correct_wheelhouse_passes(tmp_path: Path) -> None:
    payload = b"the artefact"
    real = hashlib.sha256(payload).hexdigest()
    tree(tmp_path, lock=one_wheel(real))
    house = tmp_path / "house"
    target = house / "thing" / "1.0" / real[:2] / "thing-1.0-py3-none-any.whl"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)

    assert run_materialize(tmp_path, wheelhouse=house) == 0


@needs_select
def test_a_populated_but_wrong_wheelhouse_fails(tmp_path: Path) -> None:
    """The case worth failing: somebody fetched, and one artefact is not right."""
    tree(tmp_path, lock=one_wheel(SHA))
    house = tmp_path / "house"
    target = house / "thing" / "1.0" / SHA[:2] / "thing-1.0-py3-none-any.whl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not the artefact")

    assert run_materialize(tmp_path, wheelhouse=house) == 1


def test_an_unreadable_declaration_is_unmeasured(tmp_path: Path) -> None:
    (tmp_path / "pylock.toml").write_text(one_wheel(SHA), encoding="utf-8")
    assert run_materialize(tmp_path, wheelhouse=tmp_path / "house") == 3


def test_an_unreadable_lock_is_unmeasured(tmp_path: Path) -> None:
    tree(tmp_path, lock="not toml {{{")
    assert run_materialize(tmp_path, wheelhouse=tmp_path / "house") == 3


def test_the_gate_writes_a_manifest_that_verifies(tmp_path: Path) -> None:
    tree(tmp_path, lock=one_wheel(SHA))
    run_materialize(tmp_path, wheelhouse=tmp_path / "house")
    written = tmp_path / ".globin" / "materialize" / MANIFEST_NAME
    document = load(written.read_text(encoding="utf-8"))
    assert document["phase"] == 29


def test_the_manifest_records_no_absolute_path_and_no_url(tmp_path: Path) -> None:
    tree(tmp_path, lock=one_wheel(SHA))
    run_materialize(tmp_path, wheelhouse=tmp_path / "house")
    written = tmp_path / ".globin" / "materialize" / MANIFEST_NAME
    text = written.read_text(encoding="utf-8")
    assert "http" not in text
    assert str(tmp_path) not in text


def test_the_gate_produces_the_same_manifest_twice(tmp_path: Path) -> None:
    """Determinism, proved by running it rather than by asserting a literal."""
    tree(tmp_path, lock=one_wheel(SHA))
    written = tmp_path / ".globin" / "materialize" / MANIFEST_NAME
    run_materialize(tmp_path, wheelhouse=tmp_path / "house")
    first = written.read_text(encoding="utf-8")
    run_materialize(tmp_path, wheelhouse=tmp_path / "house")
    assert written.read_text(encoding="utf-8") == first


def test_the_delivered_phase_never_claims_more_than_has_shipped() -> None:
    """An inequality, never an equality, so it goes stale harmlessly."""
    assert DELIVERED_PHASE <= LAST_COMPLETED_PHASE + 1


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_the_help_is_printed_and_nothing_runs(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["--help"]) == 0
    assert "REACHES THE INDEX" in capsys.readouterr().out


def test_an_unrecognised_subcommand_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["frobnicate"]) == 2
    assert "unrecognised" in capsys.readouterr().out


def test_a_subcommand_that_takes_nothing_refuses_an_argument() -> None:
    assert cli_main(["plan", "extra"]) == 2


def test_cleanroom_says_it_reaches_the_index_and_starts_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """It is exercised by an opt-in integration test, never from here."""
    assert cli_main(["cleanroom"]) == 0
    assert "reaches the index" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Reading the commit without starting Git
# ---------------------------------------------------------------------------


def test_a_tree_with_no_git_directory_records_an_unknown_commit(tmp_path: Path) -> None:
    """So a manifest can be produced in a checkout with no Git on the path."""
    assert commit_of(tmp_path) == "unknown"


def test_a_detached_head_is_read_directly(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("f" * 40, encoding="utf-8")
    assert commit_of(tmp_path) == "f" * 40


def test_a_head_that_is_not_a_sha_and_not_a_ref_is_unknown(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("something else", encoding="utf-8")
    assert commit_of(tmp_path) == "unknown"


def test_a_symbolic_head_is_followed_to_its_reference(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (git / "refs" / "heads" / "master").write_text("e" * 40, encoding="utf-8")
    assert commit_of(tmp_path) == "e" * 40


def test_a_reference_that_does_not_exist_is_unknown(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/gone\n", encoding="utf-8")
    assert commit_of(tmp_path) == "unknown"


# ---------------------------------------------------------------------------
# Declaration shapes the gate refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("[target]\n", "no target or no policy", id="no-policy"),
        pytest.param("[policy]\n", "no target or no policy", id="no-target"),
        pytest.param(
            '[target]\nminor_line = ""\nplatform_tag = "win_amd64"\n[policy]\n',
            "incomplete target",
            id="no-minor-line",
        ),
        pytest.param(
            '[target]\nminor_line = "3.14"\nplatform_tag = ""\n[policy]\n',
            "incomplete target",
            id="no-platform",
        ),
        pytest.param(
            '[target]\nminor_line = "three"\nplatform_tag = "win_amd64"\n[policy]\n',
            "incomplete target",
            id="minor-line-not-a-number",
        ),
        pytest.param("not toml {{{", "could not be read", id="not-toml"),
    ],
)
def test_a_declaration_the_gate_cannot_use_is_reported(
    tmp_path: Path, body: str, expected: str
) -> None:
    """Refused with a sentence rather than guessed at."""
    policy = tmp_path / "docs" / "engineering"
    policy.mkdir(parents=True)
    (policy / "lock-policy.toml").write_text(body, encoding="utf-8")
    tags, _, problem = declared_target(tmp_path)
    assert tags == ()
    assert expected in problem


def test_a_free_threaded_target_offers_no_stable_abi_tag(tmp_path: Path) -> None:
    """The limited API is not offered on a free-threaded build.

    ADR-0052 recorded the trap; this is the same rule stated as tag construction
    rather than as a filename comparison.
    """
    policy = tmp_path / "docs" / "engineering"
    policy.mkdir(parents=True)
    (policy / "lock-policy.toml").write_text(
        '[target]\nminor_line = "3.14"\nplatform_tag = "win_amd64"\n'
        "free_threaded = true\n[policy]\nallow_source = false\n",
        encoding="utf-8",
    )
    tags, _, problem = declared_target(tmp_path)
    assert problem == ""
    assert tags[0].abi == "cp314t"
    assert not any(tag.abi == "abi3" for tag in tags)


def test_a_lock_the_reference_implementation_refuses_is_reported(repo_root: Path) -> None:
    tags, _, _ = declared_target(repo_root)
    _, problem = selections_from('lock-version = "1.0"\npackages = []\n', tags)
    assert "could not be read" in problem


@needs_select
def test_one_unservable_distribution_makes_the_whole_lock_unresolvable(
    repo_root: Path,
) -> None:
    """Measured rather than assumed, and it corrected a design assumption.

    `Pylock.select` is **all-or-nothing**: it raises as soon as any package has
    no artefact serving the tags, rather than yielding the rest and omitting
    that one. So a lock carrying a single Linux-only wheel is reported as a
    lock-level problem, not as one incompatible entry among many.

    That is a reasonable answer for a gate -- an environment that cannot be
    fully built is not partly buildable -- and it is why `PlanState.INCOMPATIBLE`
    is reachable through the pure `plan_for` API and not through this path. The
    message names the package, so an operator is not left guessing which.
    """
    tags, _, _ = declared_target(repo_root)
    lock = (
        'lock-version = "1.0"\n'
        'created-by = "globin-tests"\n'
        "[[packages]]\n"
        'name = "linux-only"\n'
        'version = "1.0"\n'
        "[[packages.wheels]]\n"
        'name = "linux_only-1.0-cp314-cp314-manylinux_2_17_x86_64.whl"\n'
        'url = "https://files.pythonhosted.org/x.whl"\n'
        'hashes = {sha256 = "ab"}\n'
    )
    selections, problem = selections_from(lock, tags)
    assert selections == ()
    assert "could not be resolved" in problem
    assert "linux-only" in problem


@needs_select
def test_a_wheelhouse_asked_for_a_weak_digest_reports_it(tmp_path: Path) -> None:
    """The cache finding, driven through the gate rather than the helper."""
    policy = tmp_path / "docs" / "engineering"
    policy.mkdir(parents=True)
    (policy / "lock-policy.toml").write_text(
        '[target]\nminor_line = "3.14"\nplatform_tag = "win_amd64"\n'
        "free_threaded = false\n[policy]\nallow_source = false\n",
        encoding="utf-8",
    )
    (tmp_path / "pylock.toml").write_text(
        'lock-version = "1.0"\n'
        'created-by = "globin-tests"\n'
        "[[packages]]\n"
        'name = "thing"\n'
        'version = "1.0"\n'
        "[[packages.wheels]]\n"
        'name = "thing-1.0-py3-none-any.whl"\n'
        'url = "https://files.pythonhosted.org/thing-1.0-py3-none-any.whl"\n'
        'hashes = {md5 = "ab"}\n',
        encoding="utf-8",
    )
    # An md5-only artefact yields no usable key, so the plan says UNHASHED and
    # the wheelhouse is never asked about it -- which is the ordering the plan
    # documents: a digest is required before presence.
    assert run_materialize(tmp_path, wheelhouse=tmp_path / "house") == 1


def test_a_file_that_cannot_be_read_is_reported_rather_than_crashing(
    tmp_path: Path,
) -> None:
    """A wheelhouse entry that exists and is unreadable is a cache fault."""
    key = cache_key(name="thing", version="1.0", filename="w.whl", hashes=(("sha256", SHA),))
    assert key is not None
    target = tmp_path / Path(key.relative())
    target.parent.mkdir(parents=True)
    target.mkdir()  # a directory where a file is expected: present, unreadable
    assert Wheelhouse(root=tmp_path).digests((key,)) == {}


# ---------------------------------------------------------------------------
# The command line's remaining paths
# ---------------------------------------------------------------------------


class _Counter:
    """A stand-in for the gate that records how often it was asked to run."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        return 0


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="no-subcommand"),
        pytest.param(["plan"], id="plan"),
        pytest.param(["verify"], id="verify"),
    ],
)
def test_the_offline_plan_is_what_runs_by_default(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`plan` is the default, and it is what the one-word command runs."""
    counter = _Counter()
    monkeypatch.setattr("tools.quality.materialize.cli.run_materialize", counter)
    assert cli_main(argv) == 0
    assert counter.calls == 1
