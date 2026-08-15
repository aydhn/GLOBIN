"""The pure half of the mutation harness: what it finds, what it decides, what it reads.

Three modules are checked here, and none of them touches a disk or a process.
That is the point of the package's split: the judgements worth testing
exhaustively are the ones a subprocess would otherwise make untestable.

The judgements that matter most are the ones about *not* trusting a number.
:func:`~tools.quality.mutation.plan.classify` is parametrised over every exit
code pytest defines, because the failure this whole harness is shaped around is
reading "not zero" as "the mutant was killed" — which would score a run that
collected no tests at all as a flawless one.
"""

import ast
import difflib
import tomllib
from typing import Final

import pytest

from tools.quality.mutation import baseline, operators, plan
from tools.quality.mutation.plan import (
    Configuration,
    MutationConfigurationError,
    Target,
    Verdict,
)

#: A module small enough to reason about, holding one site of every kind.
SAMPLE: Final[str] = '''\
"""A docstring, which is never a site because strings are never mutated."""

LIMIT = 8
ENABLED = True


class Colour(StrEnum):
    """An enumeration, whose integer members are excluded."""

    RED = 1
    BLUE = 2


class Holder:
    def check(self, depth, other):
        if not other:
            return None
        if depth >= LIMIT and depth + 1 < 20:
            return "deep" in other or depth is None
        return depth - 1
'''


def _identities(source: str) -> tuple[str, ...]:
    return tuple(site.identity for site in operators.sites(source))


def _changed_lines(source: str, identity: str) -> list[str]:
    """The unified diff of one mutant against the unparsed original."""
    before = ast.unparse(ast.parse(source)).splitlines()
    after = operators.apply(source, identity).splitlines()
    return [
        line
        for line in difflib.unified_diff(before, after, n=0)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


# --------------------------------------------------------------------------
# Finding sites
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("a = 1 < 2", "<module>::comparison::Lt->LtE::0"),
        ("a = 1 <= 2", "<module>::comparison::LtE->Lt::0"),
        ("a = 1 == 2", "<module>::comparison::Eq->NotEq::0"),
        ("a = 1 in b", "<module>::comparison::In->NotIn::0"),
        ("a = 1 is b", "<module>::comparison::Is->IsNot::0"),
        ("a = b and c", "<module>::boolean::And->Or::0"),
        ("a = b + c", "<module>::arithmetic::Add->Sub::0"),
        ("a = not b", "<module>::not-removal::remove::0"),
        ("a = 7", "<module>::integer::7->8::0"),
        ("a = True", "<module>::boolean-constant::True->False::0"),
        ("a = False", "<module>::boolean-constant::False->True::0"),
    ],
)
def test_each_operator_finds_its_own_site(source: str, expected: str) -> None:
    assert expected in _identities(source)


@pytest.mark.parametrize("source", ['a = "text"', "a = 1.5", "a = None", "a = b @ c"])
def test_the_excluded_kinds_produce_no_site(source: str) -> None:
    """Strings, floats, `None` and unlisted operators are deliberately not mutated."""
    assert _identities(source) == ()


def test_the_comparison_table_covers_every_comparison_python_has() -> None:
    """A tripwire, because the code indexes the table rather than defaulting.

    Looking up with a default and skipping the miss would mean a new comparison
    operator silently stopped producing sites, and the score would improve for
    the worst possible reason.
    """
    assert set(operators.COMPARISONS) == set(ast.cmpop.__subclasses__())


def test_a_class_whose_base_is_not_an_enumeration_keeps_its_integers() -> None:
    assert "Holder::integer::3->4::0" in _identities("class Holder(Base):\n    LIMIT = 3\n")


def test_a_statement_holding_plain_strings_is_walked_without_complaint() -> None:
    """`global` carries a list of names, not of nodes, and the walk must not assume."""
    assert _identities("def f():\n    global x\n    return 1 < 2\n") == (
        "f::comparison::Lt->LtE::0",
        "f::integer::1->2::0",
        "f::integer::2->3::0",
    )


def test_an_integer_member_of_an_enumeration_is_not_a_site() -> None:
    """A guaranteed survivor is noise in a report meant to be read."""
    assert _identities("class Severity(IntEnum):\n    DEBUG = 10\n") == ()
    assert _identities("class Severity(enum.IntEnum):\n    DEBUG = 10\n") == ()


def test_an_integer_in_a_method_of_an_enumeration_is_still_a_site() -> None:
    """The exclusion covers the class body, not everything lexically inside it."""
    source = "class Severity(IntEnum):\n    def scaled(self):\n        return 3\n"
    assert "Severity.scaled::integer::3->4::0" in _identities(source)


def test_an_integer_in_an_ordinary_class_body_is_a_site() -> None:
    assert "Holder::integer::3->4::0" in _identities("class Holder:\n    LIMIT = 3\n")


def test_every_comparison_in_a_chain_is_its_own_site() -> None:
    found = _identities("a = 1 < 2 < 3")
    assert found.count("<module>::comparison::Lt->LtE::0") == 1
    assert "<module>::comparison::Lt->LtE::1" in found


def test_repeated_identical_changes_are_told_apart_by_ordinal() -> None:
    """Two `<` in one module are the same change in two places, and must be separable."""
    found = _identities("a = 1 < 2\nb = 3 < 4\n")
    assert "<module>::comparison::Lt->LtE::0" in found
    assert "<module>::comparison::Lt->LtE::1" in found


def test_no_two_sites_share_an_identity() -> None:
    """A repeated identity would make a baseline entry ambiguous about which it names."""
    found = _identities(SAMPLE)
    assert len(set(found)) == len(found)


def test_sites_are_ordered_by_position_and_then_by_what_the_change_is() -> None:
    """Explicit, so the inventory cannot move when `ast` reorders its children."""
    found = operators.sites("a = 1 < 2\nb = 3 + 4\n")
    keys = [(site.lineno, site.col_offset, site.operator) for site in found]
    assert keys == sorted(keys)


def test_a_site_is_named_after_the_scope_that_holds_it() -> None:
    source = "class Outer:\n    class Inner:\n        def method(self):\n            return 1 < 2\n"
    assert "Outer.Inner.method::comparison::Lt->LtE::0" in _identities(source)


def test_an_async_function_names_its_scope_too() -> None:
    assert "wait::comparison::Lt->LtE::0" in _identities("async def wait():\n    return 1 < 2\n")


def test_finding_sites_is_deterministic() -> None:
    """A run whose inventory moved between invocations could not have a baseline."""
    assert operators.sites(SAMPLE) == operators.sites(SAMPLE)


def test_the_sample_offers_something_to_find() -> None:
    """Guard the guard: an empty inventory would make the assertions above vacuous."""
    assert len(operators.sites(SAMPLE)) > 5


def test_a_site_records_where_it_came_from() -> None:
    """Positions are for the report, and must be the original ones."""
    site = next(item for item in operators.sites(SAMPLE) if item.qualname == "Holder.check")
    assert site.lineno > 1
    assert site.col_offset >= 0


# --------------------------------------------------------------------------
# Writing one of them wrong
# --------------------------------------------------------------------------


def test_every_mutant_of_the_sample_still_parses() -> None:
    """A mutant that will not compile is not a test of anything."""
    for site in operators.sites(SAMPLE):
        ast.parse(operators.apply(SAMPLE, site.identity))


def test_every_mutant_changes_exactly_one_line() -> None:
    """Two changes at once would make a survivor impossible to interpret."""
    for site in operators.sites(SAMPLE):
        assert len(_changed_lines(SAMPLE, site.identity)) == 2, site.identity


def test_applying_a_change_does_not_disturb_the_next_one() -> None:
    """Each call re-parses, so the inventory cannot drift as mutants are produced."""
    before = operators.sites(SAMPLE)
    for site in before:
        operators.apply(SAMPLE, site.identity)
    assert operators.sites(SAMPLE) == before


def test_removing_a_not_inside_a_list_of_operands_works() -> None:
    """The change replaces a node inside its parent, and the parent may hold a list."""
    mutated = operators.apply("a = (not b) and c", "<module>::not-removal::remove::0")
    assert mutated == "a = b and c"


def test_an_unknown_identity_is_refused_rather_than_ignored() -> None:
    with pytest.raises(KeyError, match="no mutation site"):
        operators.apply(SAMPLE, "Nowhere::comparison::Lt->LtE::0")


# --------------------------------------------------------------------------
# Deciding what an exit code means
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [
        (0, Verdict.SURVIVED),
        (1, Verdict.KILLED),
        (2, Verdict.ERROR),
        (3, Verdict.ERROR),
        (4, Verdict.ERROR),
        (5, Verdict.NO_TESTS),
        (6, Verdict.ERROR),
        (99, Verdict.ERROR),
        (None, Verdict.ERROR),
    ],
)
def test_each_exit_code_means_what_pytest_says_it_means(
    exit_code: int | None, expected: Verdict
) -> None:
    """Only 0 and 1 are verdicts about the mutant. Everything else says so.

    Exit 5 is the one that matters: a mis-typed selector collects nothing and
    returns it, and a harness reading "not zero" as "killed" would call that a
    perfect score.
    """
    assert plan.classify(exit_code, timed_out=False) is expected


@pytest.mark.parametrize("exit_code", [None, 0, 1])
def test_a_stopped_child_is_a_timeout_whatever_it_returned(exit_code: int | None) -> None:
    assert plan.classify(exit_code, timed_out=True) is Verdict.TIMEOUT


# --------------------------------------------------------------------------
# Launching a child
# --------------------------------------------------------------------------


def test_the_child_is_told_which_hypothesis_profile_to_use() -> None:
    """Without it the `dev` profile's example database survives between mutants.

    One mutant's verdict would then depend on the failures of the mutant before
    it, which is the definition of a result nobody can reproduce.
    """
    assert "--hypothesis-profile=ci" in plan.child_argv(["tests/unit/test_values.py"])


def test_the_child_writes_no_cache_into_the_sandbox() -> None:
    assert "no:cacheprovider" in plan.child_argv([])


def test_the_child_stops_at_the_first_failure() -> None:
    """A killed mutant needs one failing test, not a full report of them."""
    assert "-x" in plan.child_argv([])


def test_the_child_is_asked_to_run_exactly_the_declared_paths() -> None:
    argv = plan.child_argv(["a.py", "b.py"])
    assert argv[-2:] == ("a.py", "b.py")


@pytest.mark.parametrize(
    "name", ["COVERAGE_PROCESS_START", "PYTHONPATH", "PYTEST_ADDOPTS", "HYPOTHESIS_PROFILE"]
)
def test_the_child_inherits_nothing_that_could_change_the_answer(name: str) -> None:
    """An allowlist, so a name nobody thought of cannot arrive by accident.

    `PYTHONPATH` is the dangerous one: pointing it at the real source tree would
    make every mutant survive.
    """
    assert name not in plan.child_environment({name: "something", "PATH": "p"})


def test_the_child_keeps_what_it_needs_to_start() -> None:
    child = plan.child_environment({"PATH": "p", "SYSTEMROOT": "r"})
    assert child["PATH"] == "p"
    assert child["SYSTEMROOT"] == "r"


def test_the_child_never_writes_bytecode() -> None:
    """Not speed: CPython validates a `.pyc` against a whole-second timestamp and a.

    byte count, and most mutations here preserve length exactly. Two mutants written
    in the same second could otherwise run the first one's cached bytecode.
    """
    assert plan.child_environment({})["PYTHONDONTWRITEBYTECODE"] == "1"


def test_the_child_hashes_deterministically() -> None:
    assert plan.child_environment({})["PYTHONHASHSEED"] == "0"


def test_the_interpreter_launched_is_the_one_running() -> None:
    assert plan.interpreter().endswith(("python", "python.exe", "python3", "python3.exe"))


# --------------------------------------------------------------------------
# Reading the configuration
# --------------------------------------------------------------------------


def _configuration(**overrides: object) -> dict[str, object]:
    mutation: dict[str, object] = {
        "target": [
            {"module": "src/globin/domain/values.py", "tests": ["tests/unit/test_values.py"]}
        ]
    }
    mutation.update(overrides)
    return {"tool": {"globin": {"mutation": mutation}}}


def test_a_configuration_declares_its_targets() -> None:
    configuration = plan.read_configuration(_configuration())
    assert configuration.targets == (
        Target(module="src/globin/domain/values.py", tests=("tests/unit/test_values.py",)),
    )


def test_a_configuration_falls_back_to_the_published_defaults() -> None:
    configuration = plan.read_configuration(_configuration())
    assert configuration.sandbox == plan.DEFAULT_SANDBOX
    assert configuration.baseline == plan.DEFAULT_BASELINE
    assert configuration.timeout_factor == plan.DEFAULT_TIMEOUT_FACTOR
    assert configuration.timeout_floor_seconds == plan.DEFAULT_TIMEOUT_FLOOR_SECONDS


def test_a_configuration_may_override_every_default() -> None:
    configuration = plan.read_configuration(
        _configuration(
            sandbox=["src"], baseline="b.toml", timeout_factor=2, timeout_floor_seconds=5
        )
    )
    assert configuration.sandbox == ("src",)
    assert configuration.baseline == "b.toml"
    assert configuration.timeout_factor == 2
    assert configuration.timeout_floor_seconds == 5


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param({}, "called 'tool'", id="no tool table"),
        pytest.param({"tool": {}}, "called 'globin'", id="no globin table"),
        pytest.param({"tool": {"globin": {}}}, "called 'mutation'", id="no mutation table"),
        pytest.param({"tool": {"globin": {"mutation": {}}}}, "declares no", id="no target"),
        pytest.param(
            {"tool": {"globin": {"mutation": {"target": ["not a table"]}}}},
            "not a table",
            id="target is not a table",
        ),
        pytest.param(
            {"tool": {"globin": {"mutation": {"target": [{"tests": ["a"]}]}}}},
            "declares no module",
            id="target without a module",
        ),
        pytest.param(
            {"tool": {"globin": {"mutation": {"target": [{"module": "m"}]}}}},
            "declares no tests",
            id="target without tests",
        ),
    ],
)
def test_a_malformed_configuration_is_refused_by_name(
    document: dict[str, object], expected: str
) -> None:
    """Every refusal names the thing that is wrong, because the reader has to fix it."""
    with pytest.raises(MutationConfigurationError, match=expected):
        plan.read_configuration(document)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("sandbox", "src", "list of strings"),
        ("baseline", 4, "must be a string"),
        ("timeout_factor", "eight", "whole number"),
        ("timeout_floor_seconds", True, "whole number"),
    ],
)
def test_a_setting_of_the_wrong_shape_is_refused(key: str, value: object, expected: str) -> None:
    """`True` is refused as a number because `isinstance(True, int)` is true."""
    with pytest.raises(MutationConfigurationError, match=expected):
        plan.read_configuration(_configuration(**{key: value}))


def test_a_declared_path_that_does_not_exist_is_reported_before_anything_launches(
    repo_root: object,
) -> None:
    """The one mistake that would otherwise reach pytest and come back as exit 5."""
    from pathlib import Path

    assert isinstance(repo_root, Path)
    configuration = Configuration(
        targets=(Target(module="src/nope.py", tests=("tests/nope.py",)),),
        sandbox=(),
        baseline="",
        timeout_factor=1,
        timeout_floor_seconds=1,
    )
    problems = plan.validate(configuration, repo_root)
    assert any("target module does not exist" in line for line in problems)
    assert any("test path does not exist" in line for line in problems)


def test_the_real_configuration_resolves(repo_root: object) -> None:
    """A positive control: without it the check above could pass on anything."""
    from pathlib import Path

    assert isinstance(repo_root, Path)
    document = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert plan.validate(plan.read_configuration(document), repo_root) == ()


# --------------------------------------------------------------------------
# The budget
# --------------------------------------------------------------------------


def test_a_fast_subset_still_gets_the_floor() -> None:
    configuration = plan.read_configuration(_configuration(timeout_floor_seconds=30))
    assert plan.timeout_seconds(0.1, configuration) == 30


def test_a_slow_subset_gets_a_proportionally_longer_budget() -> None:
    """Relative to a measurement, so the verdict is not a report about the hardware."""
    configuration = plan.read_configuration(
        _configuration(timeout_factor=8, timeout_floor_seconds=30)
    )
    assert plan.timeout_seconds(20.0, configuration) == 160


# --------------------------------------------------------------------------
# The baseline
# --------------------------------------------------------------------------

REASON: Final[str] = "A reason long enough to count as an argument rather than a shrug."


def _baseline(**survivor: object) -> dict[str, object]:
    entry: dict[str, object] = {"module": "m.py"}
    if survivor:
        entry["survivor"] = [survivor]
    return {"target": [entry]}


def test_a_baseline_records_a_survivor_and_its_argument() -> None:
    loaded = baseline.load(_baseline(id="a::b::c::0", reason=REASON))
    assert loaded["m.py"].survivors == {"a::b::c::0": REASON}


def test_a_baseline_may_expect_no_survivors() -> None:
    assert baseline.load(_baseline())["m.py"].survivors == {}


def test_an_empty_baseline_loads_to_nothing() -> None:
    assert baseline.load({}) == {}


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param({"target": "no"}, "must be a list", id="targets not a list"),
        pytest.param({"target": ["no"]}, "must be a table", id="target not a table"),
        pytest.param({"target": [{}]}, "declares no module", id="no module"),
        pytest.param(
            {"target": [{"module": "m", "survivor": "no"}]},
            "must be a list",
            id="survivors not a list",
        ),
        pytest.param(
            {"target": [{"module": "m", "survivor": ["no"]}]},
            "must be a table",
            id="survivor not a table",
        ),
        pytest.param(
            {"target": [{"module": "m", "survivor": [{"reason": "r"}]}]},
            "declares no id",
            id="no id",
        ),
        pytest.param(
            {"target": [{"module": "m", "survivor": [{"id": "i"}]}]},
            "declares no reason",
            id="no reason",
        ),
        pytest.param(
            {"target": [{"module": "m", "survivor": [{"id": "i", "reason": "  "}]}]},
            "declares no reason",
            id="blank reason",
        ),
    ],
)
def test_a_malformed_baseline_is_refused_by_name(
    document: dict[str, object], expected: str
) -> None:
    with pytest.raises(MutationConfigurationError, match=expected):
        baseline.load(document)


def test_a_run_matching_the_baseline_reports_nothing() -> None:
    expectations = baseline.load(_baseline(id="a::b::c::0", reason=REASON))
    assert baseline.compare("m.py", frozenset({"a::b::c::0"}), expectations) == ()


def test_a_survivor_the_baseline_does_not_expect_fails_the_gate() -> None:
    expectations = baseline.load(_baseline())
    lines = baseline.compare("m.py", frozenset({"new::b::c::0"}), expectations)
    assert any("survived, unrecorded: new::b::c::0" in line for line in lines)


def test_a_recorded_survivor_the_run_killed_also_fails_the_gate() -> None:
    """The `xfail_strict` reading: a claim that has stopped being true is worse than none.

    Somebody will read the baseline and believe a gap still exists.
    """
    expectations = baseline.load(_baseline(id="a::b::c::0", reason=REASON))
    lines = baseline.compare("m.py", frozenset(), expectations)
    assert any("recorded, now killed: a::b::c::0" in line for line in lines)


def test_a_module_missing_from_the_baseline_fails_even_with_no_survivors() -> None:
    """Otherwise an unrecorded module would be allowed any number of survivors."""
    assert baseline.compare("absent.py", frozenset(), {}) != ()


def test_a_module_missing_from_the_baseline_lists_what_survived() -> None:
    lines = baseline.compare("absent.py", frozenset({"a::b::c::0"}), {})
    assert any("a::b::c::0" in line for line in lines)


def test_the_suggested_block_is_valid_toml_that_will_not_pass_review() -> None:
    """It parses, so it can be pasted; every reason is a placeholder, so pasting it.

    unread fails `tests/contract/test_mutation_contract.py` rather than the gate.
    """
    rendered = baseline.render("m.py", frozenset({"a::b::c::0"}))
    parsed = tomllib.loads(rendered)
    assert parsed["target"][0]["module"] == "m.py"
    assert baseline.REASON_PLACEHOLDER in parsed["target"][0]["survivor"][0]["reason"]


def test_the_suggested_block_for_a_clean_module_lists_no_survivors() -> None:
    assert tomllib.loads(baseline.render("m.py", frozenset()))["target"][0] == {"module": "m.py"}
