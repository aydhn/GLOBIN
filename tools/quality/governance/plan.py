"""What the governance arrangement declares, and every judgement made about it.

Pure. Every function here takes text or values and returns findings; nothing
reads a file, starts a process or looks at the clock. That is what lets the whole
of the reasoning be tested from literals, offline, in the way
``tools/quality/supply/capability.py`` separates :func:`classify` from ``probe``.

**The CODEOWNERS matcher is a deliberate subset, and saying so is the point.**
GitHub's syntax is gitignore-like and carries corners this repository does not
use — negation, character classes, `**` in the middle of a pattern. Implementing
those to a standard nobody here would exercise would be untested code guarding
nothing, while implementing them *badly* would report coverage that GitHub does
not agree with. So the supported forms are exactly the forms
``.github/CODEOWNERS`` uses, and :func:`matches` refuses a pattern outside them
rather than guessing. A pattern this module cannot reason about is a finding, not
a silent pass.

**Coverage means more than the catch-all.** ``*`` already names the only owner,
so a check satisfied by it would be satisfied on any repository with a catch-all
line — which is to say it would assert nothing. A declared sensitive path must be
matched by a pattern that names it more specifically, because that entry is what
survives the day a second maintainer makes the catch-all wrong.
"""

import fnmatch
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

CONFIGURATION_FILE: Final[str] = "docs/engineering/governance.toml"
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration format this module reads."""

CATCH_ALL_PATTERNS: Final[frozenset[str]] = frozenset({"*", "**", "/*", "/**"})
"""Patterns that match the whole repository.

Held as a set rather than tested for equality with ``"*"`` because all four
spellings appear in real CODEOWNERS files and all four would make a coverage
check vacuous.
"""

#: Words whose presence in an issue template means it is soliciting the technical
#: detail of a vulnerability. Matched case-insensitively against prose.
#:
#: Deliberately narrow. A template that merely says "do not report security
#: issues here" contains the word "security" and must not be flagged for it, so
#: the markers are phrases that only a *form asking for* an exploit would carry.
SOLICITATION_MARKERS: Final[tuple[str, ...]] = (
    "steps to exploit",
    "proof of concept",
    "proof-of-concept",
    "exploit code",
    "attack vector",
    "vulnerability details",
    "vulnerability detail",
    "affected versions",
    "cvss",
)


class GovernanceError(Exception):
    """The governance arrangement could not be read."""


@dataclass(frozen=True, slots=True, order=True)
class SensitivePath:
    """One path a change to which has a security consequence.

    Args:
        path: Repository-relative, forward slashes, directories ending in ``/``.
        category: How the path is grouped in the manifest and the documentation.
        reason: Why a change here is security-sensitive rather than merely
            important. Required, because an entry nobody justified is an entry
            nobody can argue with when it needs removing.
    """

    path: str
    category: str
    reason: str


@dataclass(frozen=True, slots=True, order=True)
class ExtensionPoint:
    """A path that will be security-sensitive when a later phase creates it.

    Args:
        pattern: The shape the future path will take.
        phase: The phase that owns it.
        reason: What makes it sensitive.

    These deliberately do not exist. Creating the directory early would settle a
    later phase's design question by accident, which
    ``docs/engineering/REPOSITORY_LAYOUT.md`` forbids. Declaring the shape costs
    nothing and means the path arrives claimed rather than unnoticed.
    """

    pattern: str
    phase: int
    reason: str


@dataclass(frozen=True, slots=True, order=True)
class DeclaredCapability:
    """A control whose state follows from a written decision rather than a setting.

    Args:
        name: How the manifest refers to it.
        state: One of ADR-0045's seven states, as a string.
        authority: The document that decided it.
        reason: The argument, in one sentence.

    Distinct from :mod:`tools.quality.supply.capability`'s controls, which are
    *probed*. No API answer would change one of these, because the reason it is
    off is an argument rather than a switch. Recording it is ADR-0045's rule: an
    absent key and a recorded ``NOT_APPLICABLE`` read very differently later, and
    only one of them says anything.
    """

    name: str
    state: str
    authority: str
    reason: str


@dataclass(frozen=True, slots=True)
class Locations:
    """Where each governing file is declared to live.

    Args:
        codeowners: The one authoritative code-owners file.
        security_policy: The vulnerability disclosure policy.
        governance_policy: The ownership and change-control model.
        security_baseline: The secret-handling rules.
        vulnerability_runbook: The response procedure.
        pull_request_template: The change-description standard.
        issue_template_config: The issue chooser, which carries the security link.
        issue_templates: The directory holding the public templates.
        codeowners_candidates: Every location GitHub would honour as a
            code-owners file. Exactly one may exist.
    """

    codeowners: str
    security_policy: str
    governance_policy: str
    security_baseline: str
    vulnerability_runbook: str
    pull_request_template: str
    issue_template_config: str
    issue_templates: str
    codeowners_candidates: tuple[str, ...]

    def required_files(self) -> tuple[str, ...]:
        """Every declared location that must exist as a file.

        Returns:
            The paths, in a stable order. ``issue_templates`` is excluded because
            it names a directory.
        """
        return (
            self.codeowners,
            self.security_policy,
            self.governance_policy,
            self.security_baseline,
            self.vulnerability_runbook,
            self.pull_request_template,
            self.issue_template_config,
        )


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole governance arrangement, as declared.

    Args:
        locations: Where the governing files live.
        security_policy_sections: Headings ``SECURITY.md`` must carry.
        reporting_url: The private advisory form the policy names.
        pull_request_sections: Headings the change template must carry.
        sensitive_paths: Paths a change to which is security-sensitive.
        extension_points: Paths a later phase will make sensitive.
        declared_capabilities: Controls decided by argument rather than setting.
    """

    locations: Locations
    security_policy_sections: tuple[str, ...]
    reporting_url: str
    pull_request_sections: tuple[str, ...]
    sensitive_paths: tuple[SensitivePath, ...]
    extension_points: tuple[ExtensionPoint, ...]
    declared_capabilities: tuple[DeclaredCapability, ...]


@dataclass(frozen=True, slots=True)
class Rule:
    """One CODEOWNERS line that assigns owners to a pattern.

    Args:
        pattern: The path pattern, as written.
        owners: Every owner named on the line.
        line: The one-based line number, so a finding can point at it.
    """

    pattern: str
    owners: tuple[str, ...]
    line: int


def parse_codeowners(text: str) -> tuple[Rule, ...]:
    """Read a CODEOWNERS file into rules.

    Args:
        text: The file's contents.

    Returns:
        Every rule, in file order. Comments and blank lines are skipped.

    Raises:
        GovernanceError: If a line names a pattern with no owner.

    A pattern with no owner is refused rather than ignored. GitHub treats such a
    line as *removing* ownership of the path — which is a legitimate thing to
    write and a catastrophic thing to write by accident, since it reads exactly
    like a line that assigns ownership until the owner column is noticed to be
    empty.
    """
    rules: list[Rule] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        if not owners:
            msg = (
                f"{CONFIGURATION_FILE.rsplit('/', 1)[-1]}: line {number} gives pattern "
                f"{pattern!r} no owner, which removes ownership rather than granting it"
            )
            raise GovernanceError(msg)
        rules.append(Rule(pattern=pattern, owners=tuple(owners), line=number))
    return tuple(rules)


def is_catch_all(pattern: str) -> bool:
    """Whether a pattern matches the entire repository.

    Args:
        pattern: The pattern as written.

    Returns:
        ``True`` for every spelling of "everything".
    """
    return pattern in CATCH_ALL_PATTERNS


def supported(pattern: str) -> bool:
    """Whether :func:`matches` can reason about a pattern.

    Args:
        pattern: The pattern as written.

    Returns:
        ``False`` for the CODEOWNERS syntax this module deliberately does not
        implement — negation, character classes, and ``**`` anywhere but at the
        ends.

    An unsupported pattern is reported rather than assumed to match nothing.
    Assuming would understate coverage; assuming the reverse would overstate it.
    Reporting asks a person to either simplify the pattern or extend this module.
    """
    if is_catch_all(pattern):
        return True
    if pattern.startswith("!") or "[" in pattern or "]" in pattern:
        return False
    return "**" not in pattern.strip("/")


def matches(pattern: str, path: str) -> bool:
    """Whether a CODEOWNERS pattern covers a repository-relative path.

    Args:
        pattern: The pattern as written.
        path: A repository-relative path with forward slashes. A directory ends
            with ``/``.

    Returns:
        Whether GitHub would consider the path owned by this pattern's owners.

    Only the forms :func:`supported` accepts are handled; anything else returns
    ``False`` and is reported separately, so an unsupported pattern cannot
    quietly appear to cover something.
    """
    if is_catch_all(pattern):
        return True
    if not supported(pattern):
        return False

    body = pattern.lstrip("/")
    if body.endswith("/"):
        return path == body or path.startswith(body)

    if "/" in body or pattern.startswith("/"):
        return path == body or path.startswith(f"{body}/") or fnmatch.fnmatch(path, body)

    name = path.rstrip("/").rsplit("/", 1)[-1]
    return fnmatch.fnmatch(name, body) or fnmatch.fnmatch(path, body)


def covering_rules(path: str, rules: Sequence[Rule], *, specific: bool = False) -> tuple[Rule, ...]:
    """Every rule that covers a path.

    Args:
        path: A repository-relative path.
        rules: The parsed CODEOWNERS rules.
        specific: When true, ignore catch-all rules.

    Returns:
        The matching rules, in file order.
    """
    return tuple(
        rule
        for rule in rules
        if not (specific and is_catch_all(rule.pattern)) and matches(rule.pattern, path)
    )


def duplicate_codeowners(present: Sequence[str], *, authoritative: str) -> tuple[str, ...]:
    """Report any code-owners file other than the authoritative one.

    Args:
        present: Every candidate location that exists in the tree.
        authoritative: The location the declaration names.

    Returns:
        One sentence per problem, empty when the arrangement is correct.

    GitHub reads the first candidate it finds rather than merging them, so a
    second file silently overrides the first. That is why an extra copy is a
    failure and not a duplicate to be tidied later: the file being ignored is the
    one somebody is maintaining.
    """
    problems: list[str] = []
    if authoritative not in present:
        problems.append(
            f"the declared code-owners file {authoritative!r} does not exist, "
            f"so no path in this repository has a recorded owner"
        )
    problems.extend(
        f"{location!r} is a second code-owners file; GitHub reads one of "
        f"{authoritative!r} and {location!r} and ignores the other"
        for location in sorted(present)
        if location != authoritative
    )
    return tuple(problems)


def uncovered_sensitive_paths(
    sensitive: Sequence[SensitivePath], rules: Sequence[Rule]
) -> tuple[str, ...]:
    """Report declared sensitive paths that no specific rule covers.

    Args:
        sensitive: The declared paths.
        rules: The parsed CODEOWNERS rules.

    Returns:
        One sentence per uncovered path.
    """
    return tuple(
        f"{entry.path!r} is declared security-sensitive ({entry.category}) but no CODEOWNERS "
        f"pattern names it more specifically than the catch-all"
        for entry in sorted(sensitive)
        if not covering_rules(entry.path, rules, specific=True)
    )


def unmatched_patterns(rules: Sequence[Rule], paths: Sequence[str]) -> tuple[str, ...]:
    """Report rules whose pattern matches nothing in the tree.

    Args:
        rules: The parsed CODEOWNERS rules.
        paths: Every repository-relative path, files and directories alike.

    Returns:
        One sentence per rule that owns nothing, and one per unsupported pattern.

    A pattern matching nothing is not a harmless precaution. It reads as coverage
    while providing none, and it is how a CODEOWNERS file survives a directory
    rename looking correct.
    """
    problems: list[str] = []
    for rule in rules:
        if not supported(rule.pattern):
            problems.append(
                f"line {rule.line}: pattern {rule.pattern!r} uses CODEOWNERS syntax this gate "
                f"does not implement, so its coverage cannot be established"
            )
        elif not is_catch_all(rule.pattern) and not any(
            matches(rule.pattern, path) for path in paths
        ):
            problems.append(
                f"line {rule.line}: pattern {rule.pattern!r} matches nothing in the tree, "
                f"so it declares an ownership that applies to no file"
            )
    return tuple(problems)


def ownerless(paths: Sequence[str], rules: Sequence[Rule]) -> tuple[str, ...]:
    """Report paths that no specific rule covers.

    Args:
        paths: The paths that must be specifically owned.
        rules: The parsed CODEOWNERS rules.

    Returns:
        One sentence per path.

    Used for the files under ``.github/workflows/``, which is the drift this
    exists to catch: adding a workflow is the single most security-relevant
    change anybody makes here, and nothing else notices when one arrives
    unclaimed.
    """
    return tuple(
        f"{path!r} is not covered by any CODEOWNERS pattern more specific than the catch-all"
        for path in sorted(paths)
        if not covering_rules(path, rules, specific=True)
    )


def missing_sections(text: str, required: Sequence[str]) -> tuple[str, ...]:
    """Report required headings a document does not carry.

    Args:
        text: The document.
        required: The headings, spelled exactly as they must appear.

    Returns:
        The missing headings, in declared order.

    Headings rather than prose, deliberately. A check on wording fails on every
    editorial improvement and teaches people to update expectations without
    reading them; a check on structure fails only when something was removed.
    """
    lines = {line.strip() for line in text.splitlines()}
    return tuple(heading for heading in required if heading not in lines)


def solicits_vulnerability_detail(name: str, text: str) -> tuple[str, ...]:
    """Report an issue template that asks for the technical detail of a vulnerability.

    Args:
        name: The template's file name, for the report.
        text: Its contents.

    Returns:
        One sentence per marker found, empty for an ordinary template.

    This is the check the whole issue-template arrangement exists for. A public
    form collecting exploit detail publishes the vulnerability at the moment it
    is reported, which is worse than having no channel at all — a reporter with
    no channel writes an email, whereas a reporter given a form uses it.

    HTML comments are stripped before matching, so a template that *warns*
    against reporting a vulnerability is not flagged for naming one. That
    distinction is why the markers are phrases a form would use to solicit
    detail, rather than the word "security".
    """
    prose = _without_comments(text).lower()
    return tuple(
        f"{name} asks for {marker!r}, which solicits vulnerability detail into a public issue"
        for marker in SOLICITATION_MARKERS
        if marker in prose
    )


def _without_comments(text: str) -> str:
    """Strip HTML comments from Markdown.

    Args:
        text: The document.

    Returns:
        The text with every ``<!-- ... -->`` block removed, including unclosed
        ones, which are treated as running to the end.
    """
    out: list[str] = []
    rest = text
    while True:
        before, marker, after = rest.partition("<!--")
        out.append(before)
        if not marker:
            return "".join(out)
        _, closed, rest = after.partition("-->")
        if not closed:
            return "".join(out)


def read_declaration(document: Mapping[str, object]) -> Declaration:
    """Read the governance declaration out of a parsed TOML document.

    Args:
        document: The parsed ``governance.toml``.

    Returns:
        The declaration.

    Raises:
        GovernanceError: If the schema is unknown, or a table or key is missing
            or the wrong type.

    Strict throughout, on the reasoning
    :func:`tools.quality.workflow.plan.read_configuration` gives: a declaration
    that defaulted a missing ``sensitive_path`` list to empty would pass every
    check, because there would be nothing left to be unhappy about.
    """
    schema = document.get("schema")
    if schema != SCHEMA:
        msg = (
            f"this tool reads {CONFIGURATION_FILE} schema {SCHEMA}, and the file "
            f"declares {schema!r}. Update the tool rather than reading it anyway"
        )
        raise GovernanceError(msg)

    locations = _table(document, "locations")
    policy = _table(document, "security_policy")
    template = _table(document, "pull_request_template")

    sensitive = tuple(
        SensitivePath(
            path=_text(entry, "path", "sensitive_path"),
            category=_text(entry, "category", "sensitive_path"),
            reason=_text(entry, "reason", "sensitive_path"),
        )
        for entry in _entries(document, "sensitive_path")
    )
    if not sensitive:
        msg = "sensitive_path is empty: a governance gate with no sensitive path checks nothing"
        raise GovernanceError(msg)

    return Declaration(
        locations=Locations(
            codeowners=_text(locations, "codeowners", "locations"),
            security_policy=_text(locations, "security_policy", "locations"),
            governance_policy=_text(locations, "governance_policy", "locations"),
            security_baseline=_text(locations, "security_baseline", "locations"),
            vulnerability_runbook=_text(locations, "vulnerability_runbook", "locations"),
            pull_request_template=_text(locations, "pull_request_template", "locations"),
            issue_template_config=_text(locations, "issue_template_config", "locations"),
            issue_templates=_text(locations, "issue_templates", "locations"),
            codeowners_candidates=_strings(locations, "codeowners_candidates", "locations"),
        ),
        security_policy_sections=_strings(policy, "required_sections", "security_policy"),
        reporting_url=_text(policy, "reporting_url", "security_policy"),
        pull_request_sections=_strings(template, "required_sections", "pull_request_template"),
        sensitive_paths=sensitive,
        extension_points=tuple(
            ExtensionPoint(
                pattern=_text(entry, "pattern", "extension_point"),
                phase=_integer(entry, "phase", "extension_point"),
                reason=_text(entry, "reason", "extension_point"),
            )
            for entry in _entries(document, "extension_point")
        ),
        declared_capabilities=tuple(
            DeclaredCapability(
                name=_text(entry, "name", "declared_capability"),
                state=_text(entry, "state", "declared_capability"),
                authority=_text(entry, "authority", "declared_capability"),
                reason=_text(entry, "reason", "declared_capability"),
            )
            for entry in _entries(document, "declared_capability")
        ),
    )


def parse_declaration(text: str) -> Declaration:
    """Read the declaration from TOML text.

    Args:
        text: The contents of ``governance.toml``.

    Returns:
        The declaration.

    Raises:
        GovernanceError: If the text is not TOML, or the declaration is
            malformed.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise GovernanceError(msg) from fault
    return read_declaration(document)


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Read a required sub-table.

    Args:
        document: The parsed declaration.
        name: The table's name.

    Returns:
        The table.

    Raises:
        GovernanceError: If it is absent or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise GovernanceError(msg)
    return value


def _entries(document: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    """Read an array of tables.

    Args:
        document: The parsed declaration.
        name: The array's name.

    Returns:
        Its entries, empty when the array is absent.

    Raises:
        GovernanceError: If the value is not a list of tables.
    """
    value = document.get(name, [])
    if not isinstance(value, list):
        msg = f"{CONFIGURATION_FILE}: [[{name}]] must be an array of tables"
        raise GovernanceError(msg)
    for entry in value:
        if not isinstance(entry, Mapping):
            msg = f"{CONFIGURATION_FILE}: [[{name}]] holds {type(entry).__name__}, expected a table"
            raise GovernanceError(msg)
    return tuple(value)


def _text(table: Mapping[str, object], key: str, where: str) -> str:
    """Read a non-empty string.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value.

    Raises:
        GovernanceError: If it is absent, is not a string, or is empty.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty string"
        raise GovernanceError(msg)
    return value


def _strings(table: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    """Read a non-empty list of strings.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The values.

    Raises:
        GovernanceError: If it is absent, is not a list, is empty, or holds
            anything that is not a string.
    """
    value = table.get(key)
    if not isinstance(value, list) or not value:
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty list of strings"
        raise GovernanceError(msg)
    for item in value:
        if not isinstance(item, str):
            found = type(item).__name__
            msg = f"{CONFIGURATION_FILE}: {where}.{key} holds {found}, expected a string"
            raise GovernanceError(msg)
    return tuple(value)


def _integer(table: Mapping[str, object], key: str, where: str) -> int:
    """Read a positive integer.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value.

    Raises:
        GovernanceError: If it is absent, is a :class:`bool`, is not an
            :class:`int`, or is not positive.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a positive integer"
        raise GovernanceError(msg)
    return value
