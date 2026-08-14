"""The pure half of the execution harness: manifests, shards, argv and verdicts.

Everything here is driven from literals. The module that starts a process is
covered by ``tests/integration/test_execution_end_to_end.py`` with a scripted
runner, and the command table's view of it by
``tests/contract/test_execution_contract.py``.

Two tests in this file spawn a real interpreter and carry ``slow``. They are the
only way to observe what they assert: that the shard mapping does not depend on
``PYTHONHASHSEED``, which is fixed before the interpreter starts and therefore
cannot be varied from inside one.
"""

import re
import subprocess
import sys
from typing import Final

import pytest

from tools.quality.execution import manifest, plan, shard

COLLECTED: Final[str] = """\
tests/unit/test_a.py::test_one
tests/unit/test_a.py::test_two
tests/unit/test_b.py::test_three

3 tests collected in 0.12s
"""

DESELECTED: Final[str] = """\
tests/unit/test_a.py::test_one
tests/unit/test_a.py::test_two

2/9 tests collected (7 deselected) in 0.20s
"""

IDS: Final[tuple[str, ...]] = tuple(f"tests/unit/test_{n // 10}.py::test_{n}" for n in range(60))


# --------------------------------------------------------------------------
# Parsing collection output
# --------------------------------------------------------------------------


def test_every_node_id_is_read_and_the_summary_line_is_not() -> None:
    assert manifest.parse_collection(COLLECTED) == (
        "tests/unit/test_a.py::test_one",
        "tests/unit/test_a.py::test_two",
        "tests/unit/test_b.py::test_three",
    )


def test_a_deselected_summary_is_understood() -> None:
    """`240/963 tests collected (723 deselected)` is the form a marker gives."""
    assert len(manifest.parse_collection(DESELECTED)) == 2


def test_a_parametrised_id_carrying_an_escape_is_kept() -> None:
    """pytest escapes special characters inside a parametrised ID.

    A fixture string containing a newline becomes a literal ``\\n`` and ``ç``
    becomes ``\\xe7``. Four real IDs in this repository are spelled that way, and
    a rule that refused every backslash silently dropped all four.
    """
    text = 'tests/unit/test_x.py::test_y[[meta]\\nroot = "globin"]\n\n1 test collected in 0.1s\n'
    assert len(manifest.parse_collection(text)) == 1


def test_output_with_no_summary_line_is_refused() -> None:
    with pytest.raises(manifest.ManifestError, match="no collection summary"):
        manifest.parse_collection("tests/unit/test_a.py::test_one\n")


def test_a_count_that_disagrees_with_pytests_own_is_refused() -> None:
    """The self-check that found the escaped IDs, kept as a test."""
    text = "tests/unit/test_a.py::test_one\n\n7 tests collected in 0.1s\n"
    with pytest.raises(manifest.ManifestError, match="reported 7 tests but 1 node ID"):
        manifest.parse_collection(text)


def test_an_empty_collection_is_refused() -> None:
    with pytest.raises(manifest.ManifestError, match="nothing to shard"):
        manifest.parse_collection("\n0 tests collected in 0.1s\n")


@pytest.mark.parametrize(
    "bad",
    [
        "tests\\unit\\test_a.py::test_one",
        "@tests/unit/test_a.py::test_one",
        " tests/unit/test_a.py::test_one",
    ],
)
def test_a_malformed_node_id_is_not_read_as_one(bad: str) -> None:
    """A backslash in the *path*, a leading `@`, or leading whitespace.

    Each would break something concrete: a backslash means the platform started
    writing paths its own way, and `@` is what argparse expands as another file.
    """
    assert not manifest.NODE_ID_RE.match(bad)


# --------------------------------------------------------------------------
# The digest
# --------------------------------------------------------------------------


def test_the_digest_does_not_depend_on_the_order_the_ids_arrived_in() -> None:
    forward = manifest.digest(IDS, selection="not external")
    backward = manifest.digest(tuple(reversed(IDS)), selection="not external")
    assert forward == backward


def test_the_digest_changes_when_a_test_is_added() -> None:
    assert manifest.digest(IDS, selection="x") != manifest.digest(
        (*IDS, "tests/unit/test_z.py::test_new"), selection="x"
    )


def test_the_digest_changes_when_the_selection_changes() -> None:
    """A manifest of `unit` is not a manifest of `not external`."""
    assert manifest.digest(IDS, selection="unit") != manifest.digest(IDS, selection="not external")


def test_the_digest_names_its_algorithm() -> None:
    value = manifest.digest(IDS, selection="x")
    assert value.startswith("sha256:")
    assert len(value) == len("sha256:") + 64


def test_no_volatile_field_reaches_the_digest() -> None:
    """`meta` is where everything machine-specific lives, and it is not hashed."""
    lean = manifest.build(IDS, selection="x", meta={})
    rich = manifest.build(IDS, selection="x", meta={"platform": "linux", "python": "3.99"})
    assert lean["digest"] == rich["digest"]


# --------------------------------------------------------------------------
# Round trip and refusals
# --------------------------------------------------------------------------


def test_a_document_round_trips() -> None:
    document = manifest.build(IDS, selection="x", meta={"platform": "win32"})
    assert manifest.load(manifest.render(document)) == document


def test_rendering_is_byte_stable() -> None:
    document = manifest.build(IDS, selection="x", meta={"b": 1, "a": 2})
    assert manifest.render(document) == manifest.render(document)
    assert manifest.render(document).isascii()


def test_malformed_json_is_refused() -> None:
    with pytest.raises(manifest.ManifestError, match="not valid JSON"):
        manifest.load("{not json")


def test_a_document_of_another_kind_is_refused_by_name() -> None:
    with pytest.raises(manifest.ManifestError, match=re.escape("not a globin.execution.manifest")):
        manifest.load('{"schema":"something.else","schema_version":1}')


def test_a_document_from_another_schema_version_is_refused() -> None:
    document = manifest.build(IDS, selection="x", meta={})
    document["schema_version"] = 99
    with pytest.raises(manifest.ManifestError, match="version 1"):
        manifest.load(manifest.render(document))


def test_a_document_whose_digest_disagrees_with_its_tests_is_refused() -> None:
    """An edited manifest is refused rather than partitioned."""
    document = manifest.build(IDS, selection="x", meta={})
    document["tests"] = [*IDS, "tests/unit/test_z.py::test_smuggled"]
    with pytest.raises(manifest.ManifestError, match="has been edited or truncated"):
        manifest.load(manifest.render(document))


# --------------------------------------------------------------------------
# The partition
# --------------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 2, 3, 4, 7, 60])
def test_every_test_lands_in_exactly_one_shard(count: int) -> None:
    shards = shard.partition(IDS, shard_count=count, seed=0)
    dealt = [name for group in shards for name in group]
    assert sorted(dealt) == sorted(IDS)
    assert len(dealt) == len(set(dealt))


@pytest.mark.parametrize("count", [2, 3, 4, 7])
def test_shard_sizes_differ_by_at_most_one(count: int) -> None:
    sizes = [len(group) for group in shard.partition(IDS, shard_count=count, seed=0)]
    assert max(sizes) - min(sizes) <= 1


def test_the_same_inputs_give_the_same_mapping() -> None:
    assert shard.partition(IDS, shard_count=4, seed=7) == shard.partition(
        IDS, shard_count=4, seed=7
    )


def test_the_order_the_ids_arrive_in_does_not_change_the_mapping() -> None:
    assert shard.partition(IDS, shard_count=4, seed=0) == shard.partition(
        tuple(reversed(IDS)), shard_count=4, seed=0
    )


def test_a_different_seed_deals_differently() -> None:
    """Which is what lets `soak` vary execution order without a plugin."""
    assert shard.partition(IDS, shard_count=4, seed=0) != shard.partition(
        IDS, shard_count=4, seed=1
    )


@pytest.mark.parametrize("count", [0, -1])
def test_a_shard_count_below_one_is_refused(count: int) -> None:
    with pytest.raises(shard.ShardError, match="at least 1"):
        shard.partition(IDS, shard_count=count, seed=0)


def test_more_shards_than_tests_is_refused() -> None:
    """An empty shard is pytest exit 5, not a pass."""
    with pytest.raises(shard.ShardError, match="at least one would be empty"):
        shard.partition(IDS, shard_count=len(IDS) + 1, seed=0)


@pytest.mark.parametrize("index", [-1, 4])
def test_a_shard_index_outside_the_range_is_refused(index: int) -> None:
    with pytest.raises(shard.ShardError, match=re.escape("must be in 0..3")):
        shard.validate(total=len(IDS), shard_count=4, shard_index=index)


@pytest.mark.slow
def test_the_mapping_does_not_depend_on_the_interpreters_hash_seed() -> None:
    """The one test that would actually catch `hash()` creeping in.

    Hash randomisation differs *between processes*, so this cannot be observed
    from inside one. Two children are started with different
    ``PYTHONHASHSEED`` values and must produce identical mappings.
    """
    script = (
        "from tools.quality.execution.shard import partition;"
        "ids = tuple(f'tests/unit/test_{n // 10}.py::test_{n}' for n in range(60));"
        "print(partition(ids, shard_count=4, seed=0))"
    )
    outputs = []
    for hash_seed in ("0", "1"):
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            env={"PATH": "", "PYTHONHASHSEED": hash_seed, "PYTHONPATH": "."},
            cwd=str(shard.__file__).rsplit("tools", 1)[0],
        )
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]


# --------------------------------------------------------------------------
# Verdicts, argv and environment
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, plan.Verdict.PASSED),
        (1, plan.Verdict.FAILED),
        (2, plan.Verdict.UNMEASURED),
        (3, plan.Verdict.UNMEASURED),
        (4, plan.Verdict.UNMEASURED),
        (5, plan.Verdict.UNMEASURED),
        (None, plan.Verdict.UNMEASURED),
    ],
)
def test_only_zero_and_one_are_verdicts_about_the_tests(
    code: int | None, expected: plan.Verdict
) -> None:
    assert plan.classify(code) is expected


def test_no_tests_collected_is_never_a_pass() -> None:
    """Exit 5 read as success is a shard that measured nothing reported as green."""
    assert plan.classify(5) is not plan.Verdict.PASSED


def test_a_timeout_is_unmeasured_rather_than_failed() -> None:
    assert plan.classify(0, timed_out=True) is plan.Verdict.UNMEASURED


def test_an_unmeasured_shard_outranks_a_failed_one() -> None:
    """The partition being wrong casts doubt on the shards that passed."""
    assert plan.combine([plan.Verdict.PASSED, plan.Verdict.FAILED, plan.Verdict.UNMEASURED]) is (
        plan.Verdict.UNMEASURED
    )
    assert plan.combine([plan.Verdict.PASSED, plan.Verdict.FAILED]) is plan.Verdict.FAILED
    assert plan.combine([plan.Verdict.PASSED]) is plan.Verdict.PASSED


def test_no_shards_at_all_is_unmeasured() -> None:
    assert plan.combine([]) is plan.Verdict.UNMEASURED


def test_the_child_disables_the_repositorys_coverage_floor() -> None:
    """Measured: one quarter of this suite reaches 87.43%, and the floor is 95.

    Without the override pytest-cov applies the whole-suite floor to a shard, so
    every shard exits 1 and the gate reports a broken suite while nothing is
    broken.
    """
    assert "--cov-fail-under=0" in plan.child_argv("a.txt", coverage=True)


def test_the_child_does_not_stop_at_the_first_failure() -> None:
    """`-x` would hide later failures and truncate the shard's coverage."""
    assert "-x" not in plan.child_argv("a.txt", coverage=True)


def test_the_child_uses_the_reproducible_hypothesis_profile() -> None:
    assert "--hypothesis-profile=ci" in plan.child_argv("a.txt", coverage=False)


def test_the_child_reads_its_tests_from_a_file() -> None:
    """Not from argv: 963 node IDs exceed the Windows command-line limit."""
    assert plan.child_argv("a.txt", coverage=False)[-1] == "@a.txt"


def test_coverage_flags_appear_only_when_measuring() -> None:
    assert "--cov=globin" not in plan.child_argv("a.txt", coverage=False)


def test_the_child_carries_the_seed() -> None:
    environment = plan.child_environment({}, seed=4242)
    assert environment["PYTHONHASHSEED"] == "4242"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"


@pytest.mark.parametrize("name", ["PYTHONPATH", "PYTEST_ADDOPTS", "COVERAGE_PROCESS_START"])
def test_the_child_inherits_nothing_that_could_change_the_answer(name: str) -> None:
    assert name not in plan.child_environment({name: "smuggled"}, seed=0)


def test_the_child_does_not_set_pythonnousersite() -> None:
    """A regression guard: setting it makes the child unable to find pytest here."""
    assert "PYTHONNOUSERSITE" not in plan.child_environment({}, seed=0)


def test_a_coverage_file_is_given_only_when_asked_for() -> None:
    assert "COVERAGE_FILE" not in plan.child_environment({}, seed=0)
    assert plan.child_environment({}, seed=0, coverage_file="x.cov")["COVERAGE_FILE"] == "x.cov"


# --------------------------------------------------------------------------
# The seed contract
# --------------------------------------------------------------------------


def test_a_seed_round_trips() -> None:
    assert plan.parse_seed("4242") == 4242


@pytest.mark.parametrize("bad", ["random", "1.5", "", "0x10"])
def test_a_seed_that_is_not_a_whole_number_is_refused(bad: str) -> None:
    """There is deliberately no `--seed random`: an unrecorded seed is not one."""
    with pytest.raises(ValueError, match="whole number"):
        plan.parse_seed(bad)


@pytest.mark.parametrize("bad", ["-1", "4294967296"])
def test_a_seed_outside_the_documented_range_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match=re.escape("must be in 0..4294967295")):
        plan.parse_seed(bad)


def test_the_replay_command_names_the_three_things_that_reproduce_a_run() -> None:
    line = plan.replay_command(shard_index=2, shard_count=5, seed=99)
    assert "--shards 5" in line
    assert "--only 2" in line
    assert "--seed 99" in line


def test_a_duplicate_node_id_from_pytest_is_refused() -> None:
    """The count would still agree, so this needs its own check.

    A duplicate makes the partition's disjointness claim false while every other
    signal looks healthy.
    """
    text = (
        "tests/unit/test_a.py::test_one\n"
        "tests/unit/test_a.py::test_one\n"
        "\n2 tests collected in 0.1s\n"
    )
    with pytest.raises(manifest.ManifestError, match="more than once"):
        manifest.parse_collection(text)


def test_a_json_document_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(manifest.ManifestError, match="must be a JSON object"):
        manifest.load("[1, 2, 3]")


def test_a_manifest_missing_its_tests_or_selection_is_refused() -> None:
    """A document of the right schema and version can still be unusable."""
    document = manifest.build(IDS, selection="x", meta={})
    document["tests"] = "not a list"
    with pytest.raises(manifest.ManifestError, match="a list of tests"):
        manifest.load(manifest.render(document))


def test_the_partition_guard_notices_a_test_dealt_twice() -> None:
    """Guard the guard: a checker whose failing case never runs rots.

    The real partition cannot produce this, which is exactly why the check needs
    its own failing case rather than being trusted because it has never fired.
    """
    from tools.quality.execution.gate import _verify_partition

    duplicated = (("a::t1",), ("a::t1", "a::t2"))
    assert "not disjoint" in (_verify_partition(("a::t1", "a::t2"), duplicated) or "")


def test_the_partition_guard_notices_a_test_that_reached_no_shard() -> None:
    from tools.quality.execution.gate import _verify_partition

    lossy = (("a::t1",),)
    assert "reached no shard" in (_verify_partition(("a::t1", "a::t2"), lossy) or "")


def test_the_partition_guard_is_quiet_when_the_contract_holds() -> None:
    from tools.quality.execution.gate import _verify_partition

    assert _verify_partition(("a::t1", "a::t2"), (("a::t1",), ("a::t2",))) is None
