"""Judging drift, driven directly rather than through a host.

Everything in :mod:`tools.quality.drift.plan` is pure, which is what lets this
module exercise every branch without a machine, a filesystem or a clock. The
declaration used here is written in the test rather than read from
``docs/engineering/drift-policy.toml``: this asserts what the *reader* does with a
declaration, and ``tests/contract/test_drift_contract.py`` asserts what the real
one says. A test that read the shipped file would fail whenever somebody edited a
`reason`, which trains people to update expectations without reading them.
"""

import pytest

from tools.quality.drift import plan

POLICY = """\
schema = 1

[[class]]
key = "interpreter.version"
severity = "conditional"
rule = "interpreter-version"
repair = "recreate"
writes = "nothing"
reason = "Which answer this deserves depends on which way the version moved."

[[class]]
key = "environment.system_site_packages"
severity = "violation"
repair = "in-place"
action = "set include-system-site-packages to false"
writes = "environment"
reason = "The environment can see the machine's global packages."

[[class]]
key = "host.kernel"
severity = "material"
repair = "operator"
writes = "nothing"
reason = "Windows was patched."

[[class]]
key = "pip.config.*"
severity = "material"
repair = "operator"
writes = "nothing"
reason = "A pip configuration file appeared or disappeared."
"""
"""A declaration exercising every severity, every repair reachable here, and a prefix."""


@pytest.fixture
def policy() -> plan.Policy:
    """The declaration above, parsed."""
    return plan.parse_declaration(POLICY)


# ---------------------------------------------------------------------------
# Reading the declaration
# ---------------------------------------------------------------------------


def test_a_declaration_parses_into_its_classes(policy: plan.Policy) -> None:
    """The four entries above, in the order they were written."""
    assert [entry.key for entry in policy.classes] == [
        "interpreter.version",
        "environment.system_site_packages",
        "host.kernel",
        "pip.config.*",
    ]


def test_an_optional_value_that_is_absent_reads_as_empty(policy: plan.Policy) -> None:
    """`action` and `rule` are absent from most entries and are not errors."""
    kernel = policy.for_key("host.kernel")
    assert kernel is not None
    assert kernel.action == ""
    assert kernel.rule == ""


def test_text_that_is_not_toml_is_refused() -> None:
    """A malformed declaration is reported as malformed, with tomllib's position."""
    with pytest.raises(plan.DriftPolicyError, match="not valid TOML"):
        plan.parse_declaration("[[class]\nkey =")


def test_another_schema_is_refused_rather_than_read_anyway() -> None:
    """A reader that guessed at a format it does not implement would be inventing one."""
    with pytest.raises(plan.DriftPolicyError, match="schema 1"):
        plan.parse_declaration("schema = 2\n")


def test_a_missing_required_value_names_the_entry_and_the_value() -> None:
    """The message has to be enough to find the line, and an entry may have no key yet."""
    with pytest.raises(plan.DriftPolicyError, match=r"class\[0\] must declare key"):
        plan.parse_declaration('schema = 1\n\n[[class]]\nseverity = "material"\n')


def test_a_value_of_the_wrong_type_is_refused() -> None:
    """A severity written as a number is a mistake with no defensible reading."""
    with pytest.raises(plan.DriftPolicyError, match="must be a string"):
        plan.parse_declaration("schema = 1\n\n[[class]]\nkey = 1\n")


def test_a_value_outside_the_closed_set_enumerates_what_is_accepted() -> None:
    """A rejected declaration should say what to write instead."""
    text = POLICY.replace('severity = "material"', 'severity = "spicy"', 1)
    with pytest.raises(plan.DriftPolicyError, match="expected one of"):
        plan.parse_declaration(text)


def test_a_class_array_that_is_not_tables_is_refused() -> None:
    """`class = 1` is not an array of tables, and reading it as one would invent entries."""
    with pytest.raises(plan.DriftPolicyError, match="array of tables"):
        plan.parse_declaration("schema = 1\nclass = 1\n")


def test_a_declaration_with_no_classes_is_permitted_and_empty() -> None:
    """Absent is not malformed. An empty policy classifies nothing, which the gate reports."""
    assert plan.parse_declaration("schema = 1\n").classes == ()


# ---------------------------------------------------------------------------
# Finding the class that governs a key
# ---------------------------------------------------------------------------


def test_an_exact_key_beats_a_prefix(policy: plan.Policy) -> None:
    """The specific class wins, whatever order the file happens to be in."""
    entry = policy.for_key("host.kernel")
    assert entry is not None
    assert entry.key == "host.kernel"


def test_a_prefix_class_governs_every_key_beneath_it(policy: plan.Policy) -> None:
    """One entry covers four pip scopes, so the scopes are named by the host and not here."""
    for scope in ("global", "user", "user-legacy", "site"):
        entry = policy.for_key(f"pip.config.{scope}")
        assert entry is not None
        assert entry.key == "pip.config.*"


def test_the_longest_prefix_wins_regardless_of_file_order() -> None:
    """Ordering that changes meaning is a thing that breaks when somebody tidies a file."""
    text = (
        "schema = 1\n"
        '\n[[class]]\nkey = "a.*"\nseverity = "benign"\nrepair = "none"\nwrites = "nothing"\n'
        'reason = "general"\n'
        '\n[[class]]\nkey = "a.b.*"\nseverity = "material"\nrepair = "operator"\n'
        'writes = "nothing"\nreason = "specific"\n'
    )
    entry = plan.parse_declaration(text).for_key("a.b.c")
    assert entry is not None
    assert entry.key == "a.b.*"


def test_a_key_nothing_declares_has_no_class(policy: plan.Policy) -> None:
    """Returning None rather than a default is what makes an unclassified key visible."""
    assert policy.for_key("something.nobody.wrote") is None


# ---------------------------------------------------------------------------
# Normalising and flattening an observation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        (None, ""),
        (3, "3"),
        ("3.14.5", "3.14.5"),
    ],
)
def test_a_value_normalises_to_one_spelling(value: object, expected: str) -> None:
    """A flag written two ways would compare unequal to itself across a JSON round trip."""
    assert plan.normalise(value) == expected


def test_a_nested_observation_flattens_to_dotted_keys() -> None:
    """One difference is one key, which is what a policy entry can be written against."""
    flat = plan.flatten({"pip": {"config": {"user": False}, "version": "25.2"}})
    assert flat == {"pip.config.user": "false", "pip.version": "25.2"}


def test_a_sequence_flattens_to_one_sorted_key() -> None:
    """Which variables are set is the fact; the order the host listed them in is not."""
    flat = plan.flatten({"pip": {"overrides": ["PIP_NO_INPUT", "PIP_INDEX_URL"]}})
    assert flat == {"pip.overrides": "PIP_INDEX_URL, PIP_NO_INPUT"}


def test_flattening_does_not_depend_on_the_order_keys_were_built_in() -> None:
    """Determinism starts here: the manifest is only reproducible if this is."""
    forwards = plan.flatten({"a": 1, "b": {"c": 2, "d": 3}})
    backwards = plan.flatten({"b": {"d": 3, "c": 2}, "a": 1})
    assert forwards == backwards


# ---------------------------------------------------------------------------
# Comparing two observations
# ---------------------------------------------------------------------------


def test_an_observation_compared_against_itself_reports_nothing() -> None:
    """The identity property. A comparison that failed this would report drift forever."""
    observation = {"a": "1", "b": "2"}
    assert plan.compare(observation, observation) == ()


def test_a_changed_value_is_reported_with_both_sides() -> None:
    """Which side set the value is the question an operator actually asks."""
    (difference,) = plan.compare({"a": "1"}, {"a": "2"})
    assert (difference.key, difference.before, difference.after) == ("a", "1", "2")
    assert difference.kind == plan.KIND_CHANGED


def test_a_key_the_baseline_did_not_have_is_added() -> None:
    """A `PIP_INDEX_URL` arriving is an added key, and it is the case this exists for."""
    (difference,) = plan.compare({}, {"pip.overrides": "PIP_INDEX_URL"})
    assert difference.kind == plan.KIND_ADDED
    assert difference.before == plan.ABSENT


def test_a_key_the_host_no_longer_reports_is_removed() -> None:
    """A tool disappearing is drift too, and reads as removed rather than as changed."""
    (difference,) = plan.compare({"toolchain.ruff": "0.15.14"}, {})
    assert difference.kind == plan.KIND_REMOVED
    assert difference.after == plan.ABSENT


def test_differences_are_sorted_by_key_whatever_order_the_inputs_were_in() -> None:
    """Sorting is what makes two runs of the same host render the same bytes."""
    forwards = plan.compare({"b": "1", "a": "1"}, {"b": "2", "a": "2"})
    backwards = plan.compare({"a": "1", "b": "1"}, {"a": "2", "b": "2"})
    assert forwards == backwards
    assert [difference.key for difference in forwards] == ["a", "b"]


def test_comparing_against_an_empty_baseline_is_total() -> None:
    """Two observations always have an answer, including when one of them is empty."""
    assert len(plan.compare({}, {"a": "1", "b": "2"})) == 2


# ---------------------------------------------------------------------------
# The conditional rule, which is where the phase earns its separate gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "expected", "why"),
    [
        ("3.14.5", "3.14.7", plan.SEVERITY_BENIGN, "a security patch was installed"),
        ("3.14.5", "3.14.5", plan.SEVERITY_BENIGN, "equal versions never reach here anyway"),
        ("3.14.7", "3.14.5", plan.SEVERITY_MATERIAL, "the interpreter went backwards"),
        ("3.14.5", "3.15.0", plan.SEVERITY_VIOLATION, "a different minor line is unverified"),
        ("3.14.5", "2.7.18", plan.SEVERITY_VIOLATION, "a different major line, likewise"),
        ("3.14.5", "unknown", plan.SEVERITY_VIOLATION, "an unreadable version is not benign"),
        ("", "3.14.5", plan.SEVERITY_VIOLATION, "an absent baseline value, likewise"),
    ],
)
def test_an_interpreter_version_is_judged_by_direction_not_only_by_difference(
    before: str, after: str, expected: str, why: str
) -> None:
    """The three-way answer is the reason this gate is not one more runtime finding.

    A forward patch must stay benign, because failing on it would reinstate the
    exact pin `runtime-contract.toml` refused. A backward one must not, because
    `runtime` passes on it — the contract is a floor — and something still changed
    the machine.
    """
    assert plan.interpreter_severity(before, after) == expected, why


def test_a_conditional_class_naming_an_unimplemented_rule_is_refused() -> None:
    """A rule nobody wrote that quietly resolved to benign is a classification nobody made."""
    entry = plan.DriftClass(
        key="k",
        severity=plan.SEVERITY_CONDITIONAL,
        repair=plan.REPAIR_RECREATE,
        action="",
        writes=plan.WRITES_NOTHING,
        rule="invented",
        reason="r",
    )
    difference = plan.Difference(key="k", before="1", after="2", kind=plan.KIND_CHANGED)
    with pytest.raises(plan.DriftPolicyError, match="implements"):
        plan.resolve_severity(entry, difference)


def test_a_plain_severity_passes_through_resolution_unchanged(policy: plan.Policy) -> None:
    """Only a conditional class consults a rule; everything else already said its answer."""
    entry = policy.for_key("host.kernel")
    assert entry is not None
    difference = plan.Difference(key="host.kernel", before="1", after="2", kind=plan.KIND_CHANGED)
    assert plan.resolve_severity(entry, difference) == plan.SEVERITY_MATERIAL


# ---------------------------------------------------------------------------
# Classifying
# ---------------------------------------------------------------------------


def test_a_classified_difference_carries_the_policy_s_judgement(policy: plan.Policy) -> None:
    """The action reaches the report, because a finding with no remedy is a complaint."""
    differences = plan.compare(
        {"environment.system_site_packages": "false"},
        {"environment.system_site_packages": "true"},
    )
    (judgement,) = plan.classify(differences, policy)
    assert judgement.severity == plan.SEVERITY_VIOLATION
    assert judgement.repair == plan.REPAIR_IN_PLACE
    assert "include-system-site-packages" in judgement.action


def test_a_benign_judgement_carries_no_repair(policy: plan.Policy) -> None:
    """Offering to correct a forward patch would be offering to undo a security fix.

    The class declares `recreate`, which is what applies when the rule says the
    change was wrong. On a run where it says the change was fine, there is nothing
    to repair and the judgement must not claim there is.
    """
    differences = plan.compare({"interpreter.version": "3.14.5"}, {"interpreter.version": "3.14.7"})
    (judgement,) = plan.classify(differences, policy)
    assert judgement.severity == plan.SEVERITY_BENIGN
    assert judgement.repair == plan.REPAIR_NONE
    assert judgement.action == ""


def test_a_non_benign_conditional_judgement_keeps_its_declared_repair(policy: plan.Policy) -> None:
    """The other side of the same rule."""
    differences = plan.compare({"interpreter.version": "3.14.5"}, {"interpreter.version": "3.15.0"})
    (judgement,) = plan.classify(differences, policy)
    assert judgement.severity == plan.SEVERITY_VIOLATION
    assert judgement.repair == plan.REPAIR_RECREATE


def test_an_unclassified_difference_is_omitted_rather_than_assumed_benign(
    policy: plan.Policy,
) -> None:
    """Calling it benign here would be the gate deciding what the policy declined to."""
    differences = plan.compare({}, {"nobody.declared.this": "1"})
    assert plan.classify(differences, policy) == ()


def test_an_unclassified_difference_is_named(policy: plan.Policy) -> None:
    """And it is named, so that it fails rather than passing quietly."""
    differences = plan.compare({}, {"nobody.declared.this": "1"})
    (message,) = plan.undeclared(differences, policy)
    assert "nobody.declared.this" in message


def test_a_classified_difference_is_not_reported_as_undeclared(policy: plan.Policy) -> None:
    """The other direction, so the detector cannot pass by matching nothing."""
    differences = plan.compare({"host.kernel": "1"}, {"host.kernel": "2"})
    assert plan.undeclared(differences, policy) == ()


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ((plan.SEVERITY_BENIGN, plan.SEVERITY_VIOLATION), plan.SEVERITY_VIOLATION),
        ((plan.SEVERITY_BENIGN, plan.SEVERITY_MATERIAL), plan.SEVERITY_MATERIAL),
        ((plan.SEVERITY_BENIGN,), plan.SEVERITY_BENIGN),
        ((), plan.SEVERITY_BENIGN),
    ],
)
def test_the_worst_severity_is_the_one_reported(severities: tuple[str, ...], expected: str) -> None:
    """A run is as bad as its worst finding, and an empty run is not bad."""
    judgements = [
        plan.Judgement(
            difference=plan.Difference(key="k", before="", after="", kind=plan.KIND_CHANGED),
            severity=severity,
            repair=plan.REPAIR_NONE,
            action="",
            reason="r",
        )
        for severity in severities
    ]
    assert plan.worst(judgements) == expected


# ---------------------------------------------------------------------------
# Recomputing the declaration's own claims
# ---------------------------------------------------------------------------


def test_a_consistent_declaration_has_nothing_to_report(policy: plan.Policy) -> None:
    """The guard has to pass on a correct file, or it is measuring something else."""
    assert plan.policy_problems(policy) == ()


def test_a_repair_promised_in_place_with_no_action_is_refused() -> None:
    """A verdict with no action is a promise nobody can keep."""
    text = POLICY.replace('action = "set include-system-site-packages to false"\n', "")
    (problem,) = plan.policy_problems(plan.parse_declaration(text))
    assert "declares no action" in problem


def test_a_repair_promised_in_place_that_writes_nothing_is_refused() -> None:
    """It repairs nothing, whatever it says it does."""
    text = POLICY.replace(
        'action = "set include-system-site-packages to false"\nwrites = "environment"',
        'action = "set include-system-site-packages to false"\nwrites = "nothing"',
    )
    (problem,) = plan.policy_problems(plan.parse_declaration(text))
    assert "repairs nothing" in problem


def test_an_action_recorded_against_a_verdict_that_would_never_run_it_is_refused() -> None:
    """A description of something that does not happen."""
    text = POLICY.replace(
        'repair = "operator"\nwrites = "nothing"\nreason = "Windows was patched."',
        'repair = "operator"\naction = "do something"\nwrites = "nothing"\n'
        'reason = "Windows was patched."',
    )
    problems = plan.policy_problems(plan.parse_declaration(text))
    assert any("would never run" in problem for problem in problems)


def test_a_verdict_other_than_in_place_that_writes_somewhere_is_refused() -> None:
    """The boundary, asserted in the declaration rather than only in the code."""
    text = POLICY.replace(
        'repair = "operator"\nwrites = "nothing"\nreason = "Windows was patched."',
        'repair = "operator"\nwrites = "environment"\nreason = "Windows was patched."',
    )
    problems = plan.policy_problems(plan.parse_declaration(text))
    assert any("but writes to" in problem for problem in problems)


def test_a_benign_class_that_declares_a_repair_is_refused() -> None:
    """A change that means nothing needs no correction."""
    text = (
        "schema = 1\n"
        '\n[[class]]\nkey = "k"\nseverity = "benign"\nrepair = "recreate"\n'
        'writes = "nothing"\nreason = "r"\n'
    )
    (problem,) = plan.policy_problems(plan.parse_declaration(text))
    assert "benign but declares repair" in problem


def test_a_conditional_class_with_no_rule_is_refused() -> None:
    """Conditional on what?"""
    text = POLICY.replace('rule = "interpreter-version"\n', "")
    (problem,) = plan.policy_problems(plan.parse_declaration(text))
    assert "names no rule" in problem


def test_a_rule_named_by_a_class_that_is_not_conditional_is_refused() -> None:
    """The rule would never run, so naming it claims a decision nothing makes."""
    text = POLICY.replace(
        'severity = "material"\nrepair = "operator"\nwrites = "nothing"\n'
        'reason = "Windows was patched."',
        'severity = "material"\nrule = "interpreter-version"\nrepair = "operator"\n'
        'writes = "nothing"\nreason = "Windows was patched."',
    )
    problems = plan.policy_problems(plan.parse_declaration(text))
    assert any("so the rule never runs" in problem for problem in problems)


def test_one_key_classified_twice_is_refused() -> None:
    """Two verdicts about one fact, resolved by whichever line came first."""
    text = POLICY + (
        '\n[[class]]\nkey = "host.kernel"\nseverity = "benign"\nrepair = "none"\n'
        'writes = "nothing"\nreason = "again"\n'
    )
    (problem,) = plan.duplicate_classes(plan.parse_declaration(text))
    assert "host.kernel" in problem


def test_a_policy_using_every_implemented_rule_reports_none_unreachable(
    policy: plan.Policy,
) -> None:
    """The closed set, in the direction that catches an implemented rule nobody uses."""
    assert plan.unreachable_rules(policy) == ()


def test_an_implemented_rule_no_class_uses_is_reported() -> None:
    """Code with no caller is where a defect hides until the day somebody calls it."""
    text = "schema = 1\n"
    (problem,) = plan.unreachable_rules(plan.parse_declaration(text))
    assert plan.RULE_INTERPRETER_VERSION in problem
