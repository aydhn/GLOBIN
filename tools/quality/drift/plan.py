"""Judging drift: what changed, how bad it is, and what would put it right.

Every function here takes text or values and returns findings; nothing reads a
file, opens a socket or looks at the clock. That is what lets
``tests/unit/test_drift_plan.py`` drive every branch without building a host, and
what lets the gate above be about sequencing rather than about judgement.

**An observation is a flat mapping of dotted keys to text.** Nested structures
would force this module to answer whether a changed table is one difference or
several, and every answer to that question surprises somebody —
:mod:`globin.domain.configuration` refuses the same thing for the same reason and
says so at length. Flattening makes a difference exactly one key, which is what a
policy entry can be written against and what a person can be told about.

**Values are text, including numbers and flags.** A comparison between ``1`` and
``"1"`` has no defensible answer, and an observation crosses JSON on its way to
the next run, where ``True`` and ``"True"`` are different values that mean the
same thing. Normalising once, here, removes the class of mistake rather than
relying on every producer to be careful.

**A recorded verdict is recomputed, never trusted.** ADR-0052 established the
pattern for wheels: the evidence for a claim is recorded beside it so that the
claim can be checked rather than believed. The same applies to repair. An entry
declaring that a fault is repairable in place must also declare the action and
where that action writes, and :func:`policy_problems` refuses the entry when the
two do not agree — offline, without a host, and without anybody's permission.

What this module deliberately does not decide: where configuration files live and
what profiles exist (Phase 026), which sources are consulted and in what order
(Phase 027), and how dependencies are resolved and locked (Phase 020). It knows
about one environment, declared in one contract, on one machine.
"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from tools.quality.runtime.plan import RuntimeBaselineError, Version, parse_version

CONFIGURATION_FILE: Final[str] = "docs/engineering/drift-policy.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration format this module reads."""

SEVERITY_VIOLATION: Final[str] = "violation"
"""The change has taken the environment outside the runtime contract."""

SEVERITY_MATERIAL: Final[str] = "material"
"""The change is real and worth acting on, but the contract still holds."""

SEVERITY_BENIGN: Final[str] = "benign"
"""The value is expected to vary and its variation means nothing."""

SEVERITY_CONDITIONAL: Final[str] = "conditional"
"""How bad the change is depends on the values, and a named rule decides."""

SEVERITIES: Final[frozenset[str]] = frozenset(
    {SEVERITY_VIOLATION, SEVERITY_MATERIAL, SEVERITY_BENIGN, SEVERITY_CONDITIONAL}
)
"""Every severity a class may declare."""

REPAIR_IN_PLACE: Final[str] = "in-place"
"""A bounded action inside the environment corrects it, and this tool performs it."""

REPAIR_BOOTSTRAP: Final[str] = "bootstrap"
"""Re-running the bootstrap script corrects it, without destroying anything.

Distinct from :data:`REPAIR_RECREATE` and the distinction is this phase's whole
subject. ``scripts/bootstrap.ps1`` is idempotent and removes nothing unless
``-Recreate`` is passed, so re-running it reinstalls a toolchain that has drifted
without discarding the environment. Recording the two as one verdict is what
``RUNTIME_BASELINE.md`` does today, and it is why five different faults there are
all answered with "rebuild".
"""

REPAIR_RECREATE: Final[str] = "recreate"
"""Nothing short of rebuilding the environment corrects it."""

REPAIR_OPERATOR: Final[str] = "operator"
"""A person must change something this tooling may not touch."""

REPAIR_NONE: Final[str] = "none"
"""There is nothing to correct."""

REPAIRS: Final[frozenset[str]] = frozenset(
    {REPAIR_IN_PLACE, REPAIR_BOOTSTRAP, REPAIR_RECREATE, REPAIR_OPERATOR, REPAIR_NONE}
)
"""Every repair verdict a class may declare.

Only :data:`REPAIR_IN_PLACE` is performed by this tool. The other three name what
a person should run or change, and naming is the whole of the tool's part in them:
:data:`REPAIR_RECREATE` and :data:`REPAIR_BOOTSTRAP` are ``scripts/``' work, and
:data:`REPAIR_OPERATOR` is outside the repository altogether.
"""

WRITES_ENVIRONMENT: Final[str] = "environment"
"""The action writes inside the project environment."""

WRITES_REPOSITORY: Final[str] = "repository"
"""The action writes inside the repository, outside the environment."""

WRITES_NOTHING: Final[str] = "nothing"
"""The action writes nowhere, because there is no action."""

WRITES: Final[frozenset[str]] = frozenset({WRITES_ENVIRONMENT, WRITES_REPOSITORY, WRITES_NOTHING})
"""Every place a declared action may write.

There is no member for "outside the repository", and its absence is the boundary
rather than an oversight. ADR-0050 states that nothing here edits the registry,
``PATH``, the execution policy or any interpreter outside the environment, so an
action that would do so cannot be spelled — a class needing one is
:data:`REPAIR_OPERATOR`, and the tool reports it instead of performing it.
"""

RULE_INTERPRETER_VERSION: Final[str] = "interpreter-version"
"""How bad a changed interpreter version is depends on which way, and how far.

Three answers, and the middle one is why this rule exists rather than a plain
severity:

- **A different minor line is a violation.** The contract pins the line exactly,
  and a repository verified on one has not been verified on the next.
- **A later patch on the same line is benign.** Failing here would reinstate the
  exact pin ``runtime-contract.toml`` refused, for the reason it gives: "An exact
  pin would fail the build on the day a security patch was installed, which is the
  day it is least welcome."
- **An earlier patch on the same line is material.** The contract is a floor, so
  ``runtime`` still passes and is right to; but an interpreter that went backwards
  is a machine somebody changed, and reporting it is the whole difference between
  asking "does this host satisfy the contract" and asking "is this host what it
  was". A gate that only ever agreed with ``runtime`` would not be worth running.
"""

RULES: Final[frozenset[str]] = frozenset({RULE_INTERPRETER_VERSION})
"""Every conditional rule this module implements.

Closed, and compared against the declaration in both directions, so that a class
naming a rule nobody wrote is refused rather than silently treated as benign.
"""

KIND_ADDED: Final[str] = "added"
"""The key was absent from the baseline and is present now."""

KIND_REMOVED: Final[str] = "removed"
"""The key was present in the baseline and is absent now."""

KIND_CHANGED: Final[str] = "changed"
"""The key is present in both and its value differs."""

ABSENT: Final[str] = ""
"""What an observation reports for a key it does not carry."""


class DriftPolicyError(Exception):
    """The drift policy could not be read, or a value in it could not be decided."""


@dataclass(frozen=True, slots=True, order=True)
class DriftClass:
    """One kind of divergence, and what a person should do about it.

    Args:
        key: The observation key this classifies.
        severity: One of :data:`SEVERITIES`.
        repair: One of :data:`REPAIRS`.
        action: What the bounded repair does, in words. Empty unless ``repair`` is
            :data:`REPAIR_IN_PLACE`.
        writes: One of :data:`WRITES`.
        rule: The conditional rule deciding severity. Empty unless ``severity`` is
            :data:`SEVERITY_CONDITIONAL`.
        reason: Why this classification, in prose. The argument, not a label.

    Ordered by key first, so that a sorted policy reads the way the observation
    does and two policies carrying the same classes compare equal regardless of
    the order they were written in.
    """

    key: str
    severity: str
    repair: str
    action: str
    writes: str
    rule: str
    reason: str


@dataclass(frozen=True, slots=True)
class Policy:
    """Every declared drift class.

    Args:
        classes: The classes, in the order the declaration lists them.
    """

    classes: tuple[DriftClass, ...] = ()

    def for_key(self, key: str) -> DriftClass | None:
        """Return the class governing an observation key.

        Args:
            key: The dotted observation key.

        Returns:
            The class, or ``None`` when nothing declares one.

        An exact match first, then the longest declared prefix ending in ``.*``.
        Longest rather than first so that a specific class beats a general one
        however the file happens to be ordered — ordering that changes meaning is
        a thing that breaks when somebody tidies a file.
        """
        for entry in self.classes:
            if entry.key == key:
                return entry
        best: DriftClass | None = None
        for entry in self.classes:
            if not entry.key.endswith(".*"):
                continue
            prefix = entry.key[:-1]
            if key.startswith(prefix) and (best is None or len(entry.key) > len(best.key)):
                best = entry
        return best


@dataclass(frozen=True, slots=True, order=True)
class Difference:
    """One key whose value is not what it was.

    Args:
        key: The dotted observation key.
        before: What the baseline recorded, or :data:`ABSENT`.
        after: What this run observed, or :data:`ABSENT`.
        kind: One of :data:`KIND_ADDED`, :data:`KIND_REMOVED`, :data:`KIND_CHANGED`.
    """

    key: str
    before: str
    after: str
    kind: str


@dataclass(frozen=True, slots=True, order=True)
class Judgement:
    """A difference, and what the policy says about it.

    Args:
        difference: What changed.
        severity: The resolved severity — never :data:`SEVERITY_CONDITIONAL`, which
            is a declaration about how to decide rather than a decision.
        repair: The repair verdict that applies.
        action: What the bounded repair would do, or empty.
        reason: The declared argument for this classification.
    """

    difference: Difference
    severity: str
    repair: str
    action: str
    reason: str


def normalise(value: object) -> str:
    """Render an observed value as the text an observation carries.

    Args:
        value: Whatever the host reported.

    Returns:
        Its canonical text.

    A flag becomes ``"true"`` or ``"false"`` rather than ``"True"``, because the
    observation is compared after a round trip through JSON and through a person
    reading it, and one spelling means one thing to search for. Everything else is
    ``str``, and ``None`` is :data:`ABSENT` — a key whose value is missing and a
    key that is missing are the same fact, and treating them differently would
    report drift on the day a value became unavailable.
    """
    if value is None:
        return ABSENT
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def flatten(observation: Mapping[str, object], prefix: str = "") -> dict[str, str]:
    """Turn a nested observation into flat dotted keys.

    Args:
        observation: The observation, whose sections are nested mappings.
        prefix: What to prepend, used by the recursion.

    Returns:
        Dotted keys mapped to canonical text.

    A sequence becomes one key holding its members joined by ``", "``, sorted.
    Nothing observed here is a sequence whose order carries meaning — the two that
    exist are the ``PIP_*`` variable names and the pip configuration scopes, and
    for both the question is which are present rather than in what order they were
    enumerated. Sorting makes the answer independent of how the host listed them.
    """
    flat: dict[str, str] = {}
    for name, value in sorted(observation.items()):
        key = f"{prefix}{name}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, prefix=f"{key}."))
        elif isinstance(value, (list, tuple)):
            flat[key] = ", ".join(sorted(normalise(item) for item in value))
        else:
            flat[key] = normalise(value)
    return flat


def compare(baseline: Mapping[str, str], current: Mapping[str, str]) -> tuple[Difference, ...]:
    """Report every key on which two observations disagree.

    Args:
        baseline: What was recorded previously.
        current: What was observed now.

    Returns:
        One :class:`Difference` per disagreeing key, sorted by key.

    **This never raises, and it is total.** Two observations always have an answer,
    including when one is empty. Sorting by key makes the result independent of the
    order either mapping was built in, which is what makes the manifest
    reproducible and what ``tests/property/test_drift_properties.py`` asserts.
    """
    differences: list[Difference] = []
    for key in sorted(set(baseline) | set(current)):
        before = baseline.get(key, ABSENT)
        after = current.get(key, ABSENT)
        if before == after:
            continue
        if key not in baseline:
            kind = KIND_ADDED
        elif key not in current:
            kind = KIND_REMOVED
        else:
            kind = KIND_CHANGED
        differences.append(Difference(key=key, before=before, after=after, kind=kind))
    return tuple(differences)


def _version_or_none(text: str) -> Version | None:
    """Read a version, returning ``None`` rather than raising when it will not.

    Args:
        text: The recorded version.

    Returns:
        The parsed :class:`~tools.quality.runtime.plan.Version`, or ``None``.

    Refusing here would turn an unreadable version into an exception in the middle
    of a comparison, where the useful answer is that the two differ — which the
    caller already knows, because that is why it is asking.
    """
    try:
        return parse_version(text)
    except RuntimeBaselineError:
        return None


def interpreter_severity(before: str, after: str) -> str:
    """Decide how bad a changed interpreter version is.

    Args:
        before: What the baseline recorded.
        after: What this run observed.

    Returns:
        :data:`SEVERITY_BENIGN` for a later patch on the same line,
        :data:`SEVERITY_MATERIAL` for an earlier one, and
        :data:`SEVERITY_VIOLATION` for a different line or a version that cannot
        be read as one. An unreadable version is not benign: something wrote a
        value nothing here understands, and the honest reading of that is that the
        comparison has stopped meaning what it claims.

        Two equal versions read as benign. :func:`compare` never produces such a
        difference, so this is unreachable through the gate — but a function whose
        answer to "nothing changed" is "something is wrong" is one that will be
        wrong the first time somebody calls it directly.

    The reasoning for each answer is on :data:`RULE_INTERPRETER_VERSION`.
    """
    earlier = _version_or_none(before)
    later = _version_or_none(after)
    if earlier is None or later is None:
        return SEVERITY_VIOLATION
    if earlier.line != later.line:
        return SEVERITY_VIOLATION
    return SEVERITY_BENIGN if later >= earlier else SEVERITY_MATERIAL


def resolve_severity(entry: DriftClass, difference: Difference) -> str:
    """Decide a conditional severity, and pass every other kind through.

    Args:
        entry: The declared class.
        difference: What changed.

    Returns:
        A severity that is never :data:`SEVERITY_CONDITIONAL`.

    Raises:
        DriftPolicyError: If the class names a rule this module does not implement.
            Refused rather than defaulted, because a rule nobody wrote that quietly
            resolved to "benign" is a classification nobody made.
    """
    if entry.severity != SEVERITY_CONDITIONAL:
        return entry.severity
    if entry.rule != RULE_INTERPRETER_VERSION:
        msg = (
            f"{CONFIGURATION_FILE}: class {entry.key!r} names rule {entry.rule!r}, "
            f"and this tool implements {sorted(RULES)}"
        )
        raise DriftPolicyError(msg)
    return interpreter_severity(difference.before, difference.after)


def classify(differences: Sequence[Difference], policy: Policy) -> tuple[Judgement, ...]:
    """Attach the policy's judgement to every difference it classifies.

    Args:
        differences: What changed.
        policy: The declaration.

    Returns:
        One :class:`Judgement` per classified difference, in the order given.
        Differences nothing classifies are absent, and :func:`undeclared` names
        them — reporting them as benign here would be the gate deciding something
        the policy declined to.

    Raises:
        DriftPolicyError: As :func:`resolve_severity`.

    **A judgement that resolves to benign carries no repair**, whatever the class
    declares. A conditional class declares the repair that applies when its rule
    says something is wrong, because that is the only case in which a repair
    means anything; on the runs where the rule says the change was fine, offering
    to correct it would be offering to undo a security patch.
    """
    judged: list[Judgement] = []
    for difference in differences:
        entry = policy.for_key(difference.key)
        if entry is None:
            continue
        severity = resolve_severity(entry, difference)
        benign = severity == SEVERITY_BENIGN
        judged.append(
            Judgement(
                difference=difference,
                severity=severity,
                repair=REPAIR_NONE if benign else entry.repair,
                action="" if benign else entry.action,
                reason=entry.reason,
            )
        )
    return tuple(judged)


def undeclared(differences: Sequence[Difference], policy: Policy) -> tuple[str, ...]:
    """Name every difference the policy does not classify.

    Args:
        differences: What changed.
        policy: The declaration.

    Returns:
        One message per unclassified key, sorted.

    An unclassified difference fails the gate. The alternative — treating it as
    benign — means the day a new observation key starts moving is the day the gate
    quietly stops covering it, which is the failure the whole recompute discipline
    exists to prevent.
    """
    return tuple(
        sorted(
            f"{difference.key} changed and {CONFIGURATION_FILE} classifies no such key"
            for difference in differences
            if policy.for_key(difference.key) is None
        )
    )


def policy_problems(policy: Policy) -> tuple[str, ...]:
    """Recompute every declared repair verdict from the evidence beside it.

    Args:
        policy: The declaration.

    Returns:
        One message per entry whose verdict does not follow, sorted.

    The four rules, each of which is a claim the file makes about itself:

    - A class repairable **in place** must say what the repair does and where it
      writes. A verdict with no action is a promise nobody can keep.
    - A class that is **not** repairable in place must claim no action and write
      nowhere. An action recorded against a verdict that will never run it is a
      description of something that does not happen.
    - A **benign** class repairs nothing, because there is nothing wrong.
    - A **conditional** class names a rule, and only a conditional one may.
    """
    problems: list[str] = []
    for entry in sorted(policy.classes):
        where = f"class {entry.key!r}"
        if entry.repair == REPAIR_IN_PLACE:
            if not entry.action:
                problems.append(f"{where} is repairable in place but declares no action")
            if entry.writes == WRITES_NOTHING:
                problems.append(
                    f"{where} is repairable in place but writes nothing, so it repairs nothing"
                )
        else:
            if entry.action:
                problems.append(
                    f"{where} declares repair {entry.repair!r} and an action, which would never run"
                )
            if entry.writes != WRITES_NOTHING:
                problems.append(
                    f"{where} declares repair {entry.repair!r} but writes to {entry.writes!r}"
                )
        if entry.severity == SEVERITY_BENIGN and entry.repair != REPAIR_NONE:
            problems.append(
                f"{where} is benign but declares repair {entry.repair!r}; "
                f"a change that means nothing needs no correction"
            )
        if entry.severity == SEVERITY_CONDITIONAL and not entry.rule:
            problems.append(f"{where} is conditional but names no rule to decide it")
        if entry.severity != SEVERITY_CONDITIONAL and entry.rule:
            problems.append(
                f"{where} names rule {entry.rule!r} but its severity is {entry.severity!r}, "
                f"so the rule never runs"
            )
    return tuple(sorted(problems))


def duplicate_classes(policy: Policy) -> tuple[str, ...]:
    """Name every observation key classified more than once.

    Args:
        policy: The declaration.

    Returns:
        One message per repeated key, sorted.

    Two classes for one key means the policy holds two verdicts about the same
    fact and :meth:`Policy.for_key` returns whichever comes first, which makes the
    answer depend on file order.
    """
    seen: set[str] = set()
    repeated: set[str] = set()
    for entry in policy.classes:
        if entry.key in seen:
            repeated.add(entry.key)
        seen.add(entry.key)
    return tuple(sorted(f"{key} is classified more than once" for key in repeated))


def unreachable_rules(policy: Policy) -> tuple[str, ...]:
    """Name every implemented rule no class uses.

    Args:
        policy: The declaration.

    Returns:
        One message per unused rule, sorted.

    The other direction of the closed set. A rule this module implements that
    nothing names is code with no caller, which is where a defect hides until the
    day somebody finally uses it.
    """
    named = {entry.rule for entry in policy.classes if entry.rule}
    return tuple(
        sorted(f"rule {rule!r} is implemented but no class uses it" for rule in RULES - named)
    )


def worst(judgements: Sequence[Judgement]) -> str:
    """Return the most serious severity among judgements.

    Args:
        judgements: What was judged.

    Returns:
        The severity, or :data:`SEVERITY_BENIGN` when there is nothing to judge.
    """
    order = (SEVERITY_VIOLATION, SEVERITY_MATERIAL, SEVERITY_BENIGN)
    found = {judgement.severity for judgement in judgements}
    for severity in order:
        if severity in found:
            return severity
    return SEVERITY_BENIGN


def parse_declaration(text: str) -> Policy:
    """Read the drift policy from its TOML text.

    Args:
        text: The declaration.

    Returns:
        The parsed :class:`Policy`.

    Raises:
        DriftPolicyError: If the text is not TOML, declares another schema, or
            carries a value this module cannot read.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise DriftPolicyError(msg) from fault
    return read_declaration(document)


def read_declaration(document: Mapping[str, object]) -> Policy:
    """Read the drift policy from a parsed document.

    Args:
        document: The parsed declaration.

    Returns:
        The parsed :class:`Policy`.

    Raises:
        DriftPolicyError: If the document declares another schema, or carries a
            value this module cannot read.
    """
    schema = document.get("schema")
    if schema != SCHEMA:
        msg = (
            f"this tool reads {CONFIGURATION_FILE} schema {SCHEMA}, and the file "
            f"declares {schema!r}. Update the tool rather than reading it anyway"
        )
        raise DriftPolicyError(msg)
    return Policy(
        classes=tuple(
            _read_class(entry, index) for index, entry in enumerate(_entries(document, "class"))
        )
    )


def _read_class(table: Mapping[str, object], index: int) -> DriftClass:
    """Read one ``[[class]]`` entry.

    Args:
        table: The entry.
        index: Its position, for a message about an entry with no key to name it by.

    Returns:
        The parsed :class:`DriftClass`.

    Raises:
        DriftPolicyError: If a value is missing or is not the kind it must be.
    """
    where = f"class[{index}]"
    key = _text(table, "key", where)
    named = f"class {key!r}"
    return DriftClass(
        key=key,
        severity=_choice(table, "severity", named, SEVERITIES),
        repair=_choice(table, "repair", named, REPAIRS),
        action=_text(table, "action", named, optional=True),
        writes=_choice(table, "writes", named, WRITES),
        rule=_text(table, "rule", named, optional=True),
        reason=_text(table, "reason", named),
    )


def _entries(document: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    """Return an array of tables, refusing anything else.

    Args:
        document: The parsed declaration.
        key: The array's name.

    Returns:
        The tables, empty when the array is absent.

    Raises:
        DriftPolicyError: If the value is not an array of tables.
    """
    value = document.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        msg = f"{CONFIGURATION_FILE}: {key} must be an array of tables"
        raise DriftPolicyError(msg)
    return tuple(value)


def _text(table: Mapping[str, Any], key: str, where: str, *, optional: bool = False) -> str:
    """Return a string value, refusing anything else.

    Args:
        table: The table holding it.
        key: The value's name.
        where: What to call the table in a message.
        optional: Whether an absent value is permitted, in which case it reads as
            the empty string.

    Returns:
        The value.

    Raises:
        DriftPolicyError: If the value is absent and required, or is not a string.
    """
    if key not in table:
        if optional:
            return ""
        msg = f"{CONFIGURATION_FILE}: {where} must declare {key}"
        raise DriftPolicyError(msg)
    value = table[key]
    if not isinstance(value, str):
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a string, not {type(value).__name__}"
        raise DriftPolicyError(msg)
    return value.strip()


def _choice(table: Mapping[str, Any], key: str, where: str, permitted: frozenset[str]) -> str:
    """Return a string value that must be one of a closed set.

    Args:
        table: The table holding it.
        key: The value's name.
        where: What to call the table in a message.
        permitted: The values this tool understands.

    Returns:
        The value.

    Raises:
        DriftPolicyError: If the value is absent, is not a string, or names
            something outside ``permitted``. The message enumerates what is
            accepted, so a rejected declaration says what to write instead.
    """
    value = _text(table, key, where)
    if value not in permitted:
        msg = (
            f"{CONFIGURATION_FILE}: {where}.{key} is {value!r}; expected one of {sorted(permitted)}"
        )
        raise DriftPolicyError(msg)
    return value
