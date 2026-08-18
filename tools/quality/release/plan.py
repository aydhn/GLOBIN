"""What the release contract declares, and every judgement made about it.

Pure. Every function here takes text or values and returns findings; nothing
reads a file, starts a process or looks at the clock. That is what lets the whole
of the reasoning be tested from literals, offline, in the way
``tools/quality/governance/plan.py`` separates its judgements from its gate.

**The declaration is a record, not a re-run.** ``foundation-acceptance.toml``
states what each foundation criterion requires and what evidence answers it. This
module does not re-execute fifteen phases of gates to decide whether a criterion
holds — it checks the mechanical half: that no identifier is used twice, that
every named evidence path exists, that no blocking criterion has been left
un-passed, and that the status is one of exactly four words. The judgement itself
is written down by a human in a reviewable file, exactly as
``docs/engineering/mutation-baseline.toml`` records a survivor's argument and
``docs/engineering/dependency-reviews.toml`` records a licence read. A gate that
claimed to re-derive the judgement would be claiming more than it does.

**Four statuses, and no fifth.** ``PASS``, ``FAIL``, ``BLOCKED`` and
``NOT_APPLICABLE``. There is deliberately no ``WARN``: a warning has no release
semantics until somebody defines them, and in practice the definition arrives as
"proceed anyway". ``BLOCKED`` is the honest word for a criterion whose answer
depends on something outside this repository, and it is **never** a pass —
:mod:`tools.quality.release.gate` maps it onto the unmeasured verdict, which
ADR-0045 already established outranks a failure.

**There is no YAML parser here.** ``.github/release.yml`` is recognised by shape
rather than parsed, for the reason ``tools/quality/supply/workflows.py`` gives at
length: PyYAML would be an eighth entry in a toolchain three contract tests pin
at seven, and it is absent from most CI jobs. The patterns below therefore
recognise the specific structures GitHub's schema defines and make no attempt to
understand YAML in general.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

CONFIGURATION_FILE: Final[str] = "docs/engineering/foundation-acceptance.toml"
"""The first matrix's declaration, kept under the name callers already import.

`tests/contract/test_release_contract.py` asserts this equals
`MATRICES[0].declaration`, so the two cannot become two spellings of one path.
"""
"""Where the declaration lives, relative to the repository root."""

SCHEMA: Final[int] = 1
"""The declaration format this module reads."""

TAG_PREFIX: Final[str] = "v"
"""What a release tag carries in front of the version.

A tag is a Git ref and a version is a Python distribution string; they are
related by exactly this prefix and by nothing else. Keeping the relationship in
one constant is what lets :func:`tag_for` and :func:`version_for` be inverses
that a property test can hold to account.
"""

#: A final release version: three dotted non-negative integers, no leading zeros.
#:
#: Deliberately narrower than PEP 440, which also admits epochs, pre-releases,
#: post-releases and local versions. A GLOBIN release tag names a final release
#: and nothing else, so admitting the other forms here would mean admitting
#: shapes the release procedure has no answer for. A version this pattern refuses
#: is refused by name rather than tagged anyway.
RELEASE_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
)

#: The version assignment in the package's ``__init__.py``.
#:
#: The same shape Hatchling's ``[tool.hatch.version] path`` reads, so that this
#: module and the build backend cannot disagree about which line is the version.
VERSION_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^__version__\s*(?::\s*[^=]+)?=\s*[\"'](?P<version>[^\"']+)[\"']", re.MULTILINE
)

#: A changelog release heading: ``## [0.1.0]`` or ``## 0.1.0``, with anything
#: after it. The brackets are optional because both spellings are common and
#: neither is more correct; what matters is that the version is announced.
CHANGELOG_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^##\s+\[?(?P<version>\d+\.\d+\.\d+)\]?", re.MULTILINE
)

#: The heading reserved for work that has not been released.
CHANGELOG_UNRELEASED_RE: Final[re.Pattern[str]] = re.compile(
    r"^##\s+\[?Unreleased\]?", re.MULTILINE | re.IGNORECASE
)

#: The top-level key GitHub's release-notes configuration must carry.
RELEASE_NOTES_CHANGELOG_RE: Final[re.Pattern[str]] = re.compile(r"^changelog:", re.MULTILINE)

#: The categories block inside it.
RELEASE_NOTES_CATEGORIES_RE: Final[re.Pattern[str]] = re.compile(r"^\s{2}categories:", re.MULTILINE)

#: One category's title.
RELEASE_NOTES_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s+title:\s*(?P<title>.+?)\s*$", re.MULTILINE
)

#: A label entry inside a category's ``labels:`` list.
RELEASE_NOTES_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s+[\"']?(?P<label>[^\"'\n]+?)[\"']?\s*$", re.MULTILINE
)

#: The catch-all label. A configuration without one silently drops every pull
#: request whose labels match no category, which reads as "nothing else changed".
CATCH_ALL_LABEL: Final[str] = "*"

#: Every category a criterion may be filed under: the sixteen capability groups
#: the foundation band is certified across, in the order they are reported.
#:
#: Closed, so that a typo becomes a finding rather than a seventeenth category
#: with one member that nobody notices is orphaned.
FOUNDATION_CATEGORIES: Final[tuple[str, ...]] = (
    "repository-foundation",
    "engineering-contract",
    "architecture-boundaries",
    "decision-records",
    "living-documentation",
    "static-analysis",
    "deterministic-tests",
    "regression-controls",
    "runtime-isolation",
    "test-evidence",
    "ci-aggregation",
    "ci-hardening",
    "supply-chain",
    "security-governance",
    "release-governance",
    "release-readiness",
)

#: The thirteen capability groups the environment band (Phases 017-032) is
#: certified across, in the order they are reported. Closed, for the reason the
#: foundation set is closed.
#:
#: **Grouped by capability rather than by phase, and that is a decision.** The
#: foundation set happens to run one category per phase because that band's rows
#: described its work. This band's did not --- eleven consecutive phases
#: delivered the running application's substrate under rows that describe
#: provisioning steps, which is the finding
#: ``docs/engineering/GRANULARITY_REVIEW.md`` records. A matrix organised by
#: phase would encode that defect and read as a second roadmap.
ENVIRONMENT_CATEGORIES: Final[tuple[str, ...]] = (
    "host-baseline",
    "environment-lifecycle",
    "dependency-locking",
    "dependency-materialization",
    "scientific-stack",
    "gpu-capability",
    "application-bootstrap",
    "runtime-filesystem",
    "runtime-observability",
    "configuration-resolution",
    "secret-custody",
    "degraded-operation",
    "band-closure",
)


@dataclass(frozen=True, slots=True)
class MatrixSpec:
    """One band's acceptance matrix: which file, which prefix, which categories.

    Args:
        prefix: The three letters a criterion identifier starts with.
        band: The phases this matrix certifies, for messages.
        declaration: The TOML file declaring the criteria.
        document: The prose half.
        categories: The closed set a criterion may be filed under.

    Everything band-specific in this module lives here, and nothing else does.
    The evaluators below take a spec and are otherwise unchanged, which is what
    lets one evaluator answer for two declarations. A second copy of the rules
    would be exactly what ``docs/engineering/SOURCE_OF_TRUTH.md`` forbids, and is
    why this is a dataclass rather than a second module.
    """

    prefix: str
    band: str
    declaration: str
    document: str
    categories: tuple[str, ...]

    def last_letter(self) -> str:
        """The highest category letter this matrix uses.

        Returns:
            ``P`` for sixteen categories, ``M`` for thirteen.
        """
        return chr(ord("A") + len(self.categories) - 1)


MATRICES: Final[tuple[MatrixSpec, ...]] = (
    MatrixSpec(
        prefix="FND",
        band="001-016",
        declaration="docs/engineering/foundation-acceptance.toml",
        document="docs/release/FOUNDATION_ACCEPTANCE.md",
        categories=FOUNDATION_CATEGORIES,
    ),
    MatrixSpec(
        prefix="ENV",
        band="017-032",
        declaration="docs/engineering/environment-acceptance.toml",
        document="docs/release/ENVIRONMENT_ACCEPTANCE.md",
        categories=ENVIRONMENT_CATEGORIES,
    ),
)
"""Every band matrix this gate reads, in band order.

A twenty-first entry is what closing a band looks like from here: one row, one
declaration file, one document. Nothing in the evaluators has to change.
"""


def criterion_id_pattern(spec: MatrixSpec) -> re.Pattern[str]:
    """The identifier shape one matrix's criteria must follow.

    Args:
        spec: The matrix.

    Returns:
        A pattern matching the prefix, a category letter in range, and a
        two-digit number.

    Built from the spec rather than written out, so a matrix with thirteen
    categories cannot accept an identifier filed under a fourteenth letter.
    """
    return re.compile(rf"^{spec.prefix}-[A-{spec.last_letter()}]-\d{{2}}$")


class ReleaseError(Exception):
    """The release contract could not be read."""


class Status(StrEnum):
    """What a foundation criterion's answer is.

    Four words and no fifth. ``WARN`` is deliberately absent: it has no release
    semantics until somebody writes them down, and the semantics it acquires in
    practice are "proceed anyway", which is the failure mode this gate exists to
    prevent.
    """

    PASS = "PASS"  # noqa: S105 - a criterion's verdict, not a credential
    """Met, with evidence that exists."""

    FAIL = "FAIL"
    """Not met. A blocking criterion in this state stops a release."""

    BLOCKED = "BLOCKED"
    """The answer depends on something outside this repository.

    Never a pass. The gate maps it onto the unmeasured verdict, which ADR-0045
    established outranks a failure precisely so that "we could not tell" cannot
    be quietly rounded down to "fine".
    """

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """Genuinely out of scope, with the reason recorded rather than implied."""


@dataclass(frozen=True, slots=True, order=True)
class Criterion:
    """One thing the foundation band must satisfy before it may be frozen.

    Args:
        identifier: Stable across runs and across phases, so a criterion can be
            cited in a report months later and still mean the same requirement.
        category: One of :data:`CATEGORIES`.
        requirement: What must hold, in one sentence.
        evidence: Repository-relative paths that answer it. Checked to exist.
        command: A command that answers it, when a path cannot. Recorded rather
            than run — this gate reports what the release contract says, and
            re-running fifteen phases of gates is what ``full``, ``supply``,
            ``governance`` and ``mutation`` are each already for.
        blocking: Whether a release may proceed while this is not ``PASS``.
        status: The recorded answer.
        reason: Why the status is what it is. Required for every criterion, not
            only the failing ones, because a ``PASS`` nobody justified is a
            ``PASS`` nobody can argue with when it stops being true.
    """

    identifier: str
    category: str
    requirement: str
    blocking: bool
    status: Status
    reason: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    command: str = ""


@dataclass(frozen=True, slots=True)
class Matrix:
    """One band's criteria, paired with the spec that says how to read them.

    Args:
        spec: Which matrix this is.
        criteria: Every criterion it declares, in declaration order.
    """

    spec: MatrixSpec
    criteria: tuple[Criterion, ...]


@dataclass(frozen=True, slots=True)
class Contract:
    """The whole release arrangement, as declared.

    Args:
        version_source: The file holding ``__version__``, which Hatchling also
            reads. One source, named once.
        changelog: Where a released version must be announced.
        release_notes: GitHub's automatic release-notes configuration.
        policy: The document that owns release procedure.
        acceptance: The document that owns the foundation matrix.
        matrices: One entry per band matrix, in band order.

    **Only the first declaration carries a ``[release]`` table**, and that is
    deliberate. Those five paths are one fact about the repository rather than
    one fact per band, so a second copy of them in a second file is exactly the
    duplication ``docs/engineering/SOURCE_OF_TRUTH.md`` exists to prevent.
    :func:`parse_declaration` refuses a second copy by name rather than silently
    preferring one.
    """

    version_source: str
    changelog: str
    release_notes: str
    policy: str
    acceptance: str
    matrices: tuple[Matrix, ...]

    @property
    def criteria(self) -> tuple[Criterion, ...]:
        """Every criterion across every matrix, in band order.

        Returns:
            The criteria.

        Kept so that a caller asking a question genuinely about the whole release
        --- how many criteria are unresolved --- does not have to know how many
        bands there are. Anything judging an *identifier* uses the per-matrix
        pairs instead, because a prefix means nothing without its spec.
        """
        return tuple(criterion for matrix in self.matrices for criterion in matrix.criteria)

    def documents(self) -> tuple[str, ...]:
        """Every document a release requires to be present.

        Returns:
            The paths, in a stable order: the release-wide three, then one
            document per band matrix.
        """
        return (
            self.changelog,
            self.release_notes,
            self.policy,
            *(matrix.spec.document for matrix in self.matrices),
        )


def read_version(text: str) -> str:
    """The version a package's ``__init__.py`` declares.

    Args:
        text: The module's source.

    Returns:
        The version string.

    Raises:
        ReleaseError: If no ``__version__`` assignment is present.

    Read as text rather than by importing the package, exactly as
    ``tools/quality/supply/gate.py`` reads it. Importing would execute the
    package to learn one string, and the gate must work in a tree where the
    package does not import cleanly — which is one of the conditions it exists to
    report on.
    """
    found = VERSION_ASSIGNMENT_RE.search(text)
    if found is None:
        msg = "no __version__ assignment found; the version source declares no version"
        raise ReleaseError(msg)
    return found.group("version")


def valid_version(version: str) -> bool:
    """Whether a string is a final release version this project may tag.

    Args:
        version: The candidate.

    Returns:
        True when it is three dotted non-negative integers without leading
        zeros.
    """
    return RELEASE_VERSION_RE.fullmatch(version) is not None


def tag_for(version: str) -> str:
    """The release tag naming a version.

    Args:
        version: A final release version.

    Returns:
        The tag, which is the version with :data:`TAG_PREFIX` in front.
    """
    return f"{TAG_PREFIX}{version}"


def version_for(tag: str) -> str | None:
    """The version a release tag names.

    Args:
        tag: The tag.

    Returns:
        The version, or ``None`` when the tag is not a release tag or does not
        carry a version this project may tag.

    The inverse of :func:`tag_for` over valid versions, which is the property
    that makes tag-to-version parity checkable rather than assumed.
    """
    if not tag.startswith(TAG_PREFIX):
        return None
    version = tag[len(TAG_PREFIX) :]
    return version if valid_version(version) else None


def changelog_versions(text: str) -> tuple[str, ...]:
    """Every released version a changelog announces.

    Args:
        text: The changelog.

    Returns:
        The versions, in the order they appear. The ``Unreleased`` heading is not
        one of them.
    """
    return tuple(match.group("version") for match in CHANGELOG_HEADING_RE.finditer(text))


def changelog_problems(text: str, version: str) -> tuple[str, ...]:
    """What is wrong with a changelog, for the version about to be released.

    Args:
        text: The changelog.
        version: The version being released.

    Returns:
        One message per problem, empty when there is none.

    Two problems, and the second is the one that catches a careless re-run: a
    version announced twice means a section was appended rather than edited, and
    the reader of a changelog with two ``0.1.0`` headings cannot tell which one
    describes the release.
    """
    problems: list[str] = []
    announced = changelog_versions(text)
    if version not in announced:
        problems.append(f"the changelog does not announce {version}")
    repeated = sorted({item for item in announced if announced.count(item) > 1})
    problems.extend(f"the changelog announces {item} more than once" for item in repeated)
    if CHANGELOG_UNRELEASED_RE.search(text) is None:
        problems.append("the changelog carries no 'Unreleased' heading for work in flight")
    return tuple(problems)


def release_notes_problems(text: str) -> tuple[str, ...]:
    """What is wrong with GitHub's automatic release-notes configuration.

    Args:
        text: The contents of ``.github/release.yml``.

    Returns:
        One message per problem, empty when there is none.

    **Recognition, not parsing.** The checks below know the shapes GitHub's
    schema defines and nothing else, for the reason
    ``tools/quality/supply/workflows.py`` gives about workflow files. What that
    buys is real all the same: the three mistakes that actually get made here are
    a missing ``changelog:`` root, a category list with no catch-all, and a
    category with a title and no labels — and every one of them is visible in the
    text's shape.
    """
    problems: list[str] = []
    if RELEASE_NOTES_CHANGELOG_RE.search(text) is None:
        problems.append("no top-level 'changelog:' key")
    if RELEASE_NOTES_CATEGORIES_RE.search(text) is None:
        problems.append("no 'categories:' block under 'changelog:'")
    titles = RELEASE_NOTES_TITLE_RE.findall(text)
    if not titles:
        problems.append("no category declares a title")
    if CATCH_ALL_LABEL not in _quoted_labels(text):
        problems.append(
            f"no category carries the {CATCH_ALL_LABEL!r} catch-all label, so a pull "
            "request matching no category would be dropped from the notes silently"
        )
    return tuple(problems)


def _quoted_labels(text: str) -> tuple[str, ...]:
    """Every label named in a release-notes configuration.

    Args:
        text: The contents of ``.github/release.yml``.

    Returns:
        The labels, including the catch-all when it is present.

    A list item under ``labels:`` and a category's ``- title:`` line have the
    same leading shape, so titles are excluded explicitly rather than by hoping
    the patterns do not overlap.
    """
    titles = {title.strip().strip("\"'") for title in RELEASE_NOTES_TITLE_RE.findall(text)}
    labels: list[str] = []
    for match in RELEASE_NOTES_LABEL_RE.finditer(text):
        label = match.group("label").strip()
        if label.startswith("title:") or label in titles or ":" in label:
            continue
        labels.append(label)
    return tuple(labels)


def duplicate_identifiers(criteria: Sequence[Criterion]) -> tuple[str, ...]:
    """Every criterion identifier used more than once.

    Args:
        criteria: The declared criteria.

    Returns:
        The repeated identifiers, sorted.

    A duplicate is worse than a missing entry. Two criteria sharing an identifier
    means a report citing it names one of them and the reader cannot tell which,
    and the second silently shadows the first in anything keyed by identifier.
    """
    seen: dict[str, int] = {}
    for criterion in criteria:
        seen[criterion.identifier] = seen.get(criterion.identifier, 0) + 1
    return tuple(sorted(identifier for identifier, count in seen.items() if count > 1))


def malformed_identifiers(spec: MatrixSpec, criteria: Sequence[Criterion]) -> tuple[str, ...]:
    """Every criterion identifier that does not follow the declared shape.

    Args:
        spec: The matrix these criteria belong to.
        criteria: The declared criteria.

    Returns:
        The offending identifiers, sorted.
    """
    pattern = criterion_id_pattern(spec)
    return tuple(
        sorted(
            criterion.identifier
            for criterion in criteria
            if pattern.fullmatch(criterion.identifier) is None
        )
    )


def category_letter(spec: MatrixSpec, category: str) -> str:
    """The letter a category's criteria are numbered under.

    Args:
        spec: The matrix the category belongs to.
        category: One of ``spec.categories``.

    Returns:
        ``A`` for the first category through the matrix's last letter, or the
        empty string when the category is not declared.
    """
    if category not in spec.categories:
        return ""
    return chr(ord("A") + spec.categories.index(category))


def misfiled_identifiers(spec: MatrixSpec, criteria: Sequence[Criterion]) -> tuple[str, ...]:
    """Every criterion whose identifier letter disagrees with its category.

    Args:
        spec: The matrix these criteria belong to.
        criteria: The declared criteria.

    Returns:
        One message per offender, sorted.

    The identifier and the category say the same thing twice, which is usually a
    smell — here it is deliberate, because the identifier is what gets quoted in
    a report six months later and the category is what groups the matrix. Two
    spellings of one fact need a check that they agree, or the redundancy becomes
    a way for them to disagree quietly.
    """
    problems: list[str] = []
    for criterion in sorted(criteria):
        expected = category_letter(spec, criterion.category)
        if not expected:
            continue
        if not criterion.identifier.startswith(f"{spec.prefix}-{expected}-"):
            problems.append(
                f"{criterion.identifier} is filed under {criterion.category!r}, "
                f"whose criteria are numbered {spec.prefix}-{expected}-NN"
            )
    return tuple(problems)


def unknown_categories(spec: MatrixSpec, criteria: Sequence[Criterion]) -> tuple[str, ...]:
    """Every category named by a criterion but absent from the matrix's own set.

    Args:
        spec: The matrix these criteria belong to.
        criteria: The declared criteria.

    Returns:
        The unknown category names, sorted.
    """
    known = set(spec.categories)
    return tuple(
        sorted({criterion.category for criterion in criteria if criterion.category not in known})
    )


def empty_categories(spec: MatrixSpec, criteria: Sequence[Criterion]) -> tuple[str, ...]:
    """Every declared category no criterion files anything under.

    Args:
        spec: The matrix these criteria belong to.
        criteria: The declared criteria.

    Returns:
        The empty category names, in declaration order.

    The other direction of :func:`unknown_categories`, and the one that matters
    more: a category with no criteria is a capability group the matrix claims to
    cover and does not, which reads from the outside exactly like coverage.
    """
    used = {criterion.category for criterion in criteria}
    return tuple(category for category in spec.categories if category not in used)


def blocking_failures(criteria: Sequence[Criterion]) -> tuple[str, ...]:
    """Every blocking criterion whose status is not ``PASS``.

    Args:
        criteria: The declared criteria.

    Returns:
        One message per offender, sorted by identifier.
    """
    return tuple(
        f"{criterion.identifier} ({criterion.category}) is blocking and {criterion.status}: "
        f"{criterion.reason}"
        for criterion in sorted(criteria)
        if criterion.blocking and criterion.status is not Status.PASS
    )


def unjustified(criteria: Sequence[Criterion]) -> tuple[str, ...]:
    """Every criterion that names neither an evidence path nor a command.

    Args:
        criteria: The declared criteria.

    Returns:
        The offending identifiers, sorted.

    A criterion answered by nothing is an assertion, and the matrix exists so
    that the foundation is certified by evidence rather than by assertion.
    """
    return tuple(
        sorted(
            criterion.identifier
            for criterion in criteria
            if not criterion.evidence and not criterion.command.strip()
        )
    )


def parse_matrix(text: str, spec: MatrixSpec) -> tuple[Mapping[str, object], tuple[Criterion, ...]]:
    """Read one band matrix from TOML text.

    Args:
        text: The contents of the matrix's declaration file.
        spec: Which matrix it is, used for messages and for the schema check.

    Returns:
        The parsed document, and its criteria.

    Raises:
        ReleaseError: If the text is not TOML, the schema is unsupported, or the
            file declares no criteria.

    The document is returned alongside the criteria because only the first matrix
    carries a ``[release]`` table, and the caller is the one that knows whether to
    look for it.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{spec.declaration} is not valid TOML: {fault}"
        raise ReleaseError(msg) from fault

    schema = document.get("schema")
    if schema != SCHEMA:
        msg = (
            f"{spec.declaration}: this tool reads schema {SCHEMA}, and the file "
            f"declares {schema!r}. Regenerate it rather than reading it anyway"
        )
        raise ReleaseError(msg)

    criteria = tuple(_criterion(entry) for entry in _entries(document, "criterion"))
    if not criteria:
        msg = f"{spec.declaration} declares no criteria; an empty matrix certifies nothing"
        raise ReleaseError(msg)
    return document, criteria


def parse_declaration(texts: Mapping[str, str]) -> Contract:
    """Read the release contract from every band matrix's TOML text.

    Args:
        texts: Each matrix's declaration path mapped to its contents. Every entry
            of :data:`MATRICES` must be present.

    Returns:
        The contract.

    Raises:
        ReleaseError: If a text is not TOML, a declaration is malformed, a
            declared matrix is missing from ``texts``, or a matrix after the
            first carries a ``[release]`` table.
    """
    matrices: list[Matrix] = []
    release: Mapping[str, object] | None = None
    for spec in MATRICES:
        if spec.declaration not in texts:
            msg = f"{spec.declaration} was not read, so the {spec.band} matrix cannot be checked"
            raise ReleaseError(msg)
        document, criteria = parse_matrix(texts[spec.declaration], spec)
        if spec is MATRICES[0]:
            release = _table(document, "release")
        elif "release" in document:
            msg = (
                f"{spec.declaration} carries a [release] table. Those five paths are one "
                f"fact about the repository rather than one per band, and they are declared "
                f"in {MATRICES[0].declaration}"
            )
            raise ReleaseError(msg)
        matrices.append(Matrix(spec=spec, criteria=criteria))

    if release is None:  # pragma: no cover -- MATRICES is never empty.
        msg = "no matrix declared the release table"
        raise ReleaseError(msg)

    return Contract(
        version_source=_text(release, "version_source", "release"),
        changelog=_text(release, "changelog", "release"),
        release_notes=_text(release, "release_notes", "release"),
        policy=_text(release, "policy", "release"),
        acceptance=_text(release, "acceptance", "release"),
        matrices=tuple(matrices),
    )


def _criterion(entry: Mapping[str, object]) -> Criterion:
    """Read one criterion.

    Args:
        entry: The ``[[criterion]]`` table.

    Returns:
        The criterion.

    Raises:
        ReleaseError: If any field is absent or of the wrong type.
    """
    identifier = _text(entry, "id", "criterion")
    where = f"criterion {identifier}"
    status = _text(entry, "status", where)
    try:
        recorded = Status(status)
    except ValueError as fault:
        permitted = ", ".join(sorted(item.value for item in Status))
        msg = f"{CONFIGURATION_FILE}: {where}.status is {status!r}; permitted: {permitted}"
        raise ReleaseError(msg) from fault

    return Criterion(
        identifier=identifier,
        category=_text(entry, "category", where),
        requirement=_text(entry, "requirement", where),
        blocking=_boolean(entry, "blocking", where),
        status=recorded,
        reason=_text(entry, "reason", where),
        evidence=_strings(entry, "evidence", where, permit_empty=True),
        command=str(entry.get("command", "")),
    )


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Read a required sub-table.

    Args:
        document: The parsed declaration.
        name: The table's name.

    Returns:
        The table.

    Raises:
        ReleaseError: If it is absent or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise ReleaseError(msg)
    return value


def _entries(document: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    """Read an array of tables.

    Args:
        document: The parsed declaration.
        name: The array's name.

    Returns:
        Its entries, empty when the array is absent.

    Raises:
        ReleaseError: If the value is not a list of tables.
    """
    value = document.get(name, [])
    if not isinstance(value, list):
        msg = f"{CONFIGURATION_FILE}: [[{name}]] must be an array of tables"
        raise ReleaseError(msg)
    for entry in value:
        if not isinstance(entry, Mapping):
            found = type(entry).__name__
            msg = f"{CONFIGURATION_FILE}: [[{name}]] holds {found}, expected a table"
            raise ReleaseError(msg)
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
        ReleaseError: If it is absent, is not a string, or is empty.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty string"
        raise ReleaseError(msg)
    return value


def _strings(
    table: Mapping[str, object], key: str, where: str, *, permit_empty: bool = False
) -> tuple[str, ...]:
    """Read a list of strings.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.
        permit_empty: Whether an absent or empty list is acceptable.

    Returns:
        The values.

    Raises:
        ReleaseError: If it is not a list, holds anything that is not a string,
            or is empty when emptiness is not permitted.
    """
    value = table.get(key, [] if permit_empty else None)
    if not isinstance(value, list) or (not value and not permit_empty):
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be a non-empty list of strings"
        raise ReleaseError(msg)
    for item in value:
        if not isinstance(item, str):
            found = type(item).__name__
            msg = f"{CONFIGURATION_FILE}: {where}.{key} holds {found}, expected a string"
            raise ReleaseError(msg)
    return tuple(value)


def _boolean(table: Mapping[str, object], key: str, where: str) -> bool:
    """Read a boolean.

    Args:
        table: The table holding it.
        key: Which setting.
        where: The table's name, for the message.

    Returns:
        The value.

    Raises:
        ReleaseError: If it is absent or is not a boolean.

    A missing ``blocking`` is refused rather than defaulted. Defaulting it to
    false would make the safe-looking omission the dangerous one; defaulting it
    to true would file every new criterion as release-stopping without anybody
    deciding that. Neither default is right, so there is none.
    """
    value = table.get(key)
    if not isinstance(value, bool):
        msg = f"{CONFIGURATION_FILE}: {where}.{key} must be true or false"
        raise ReleaseError(msg)
    return value
