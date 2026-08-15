"""Every dependency this repository declares, read from the files that declare them.

**Declared, not resolved.** This module reads manifests. It does not run a
resolver, does not consult an index, and therefore does not know a transitive
tree. That is deliberate and it is a phase boundary: dependency resolution and
locking are Phase 020's subject, and an inventory that guessed at a transitive
set would be a lockfile nobody decided to build. What is recorded is what a
human wrote down, and :attr:`Dependency.resolution` says for each entry whether
that writing pins a version or merely bounds one.

**Three registers, and the reason there are three.** The ``dev`` extra in
``pyproject.toml`` carries lower bounds. ``.github/workflows/*.yml`` installs
exact versions. ``.pre-commit-config.yaml`` pins a hook revision. They describe
one toolchain from three angles, on purpose — the extra says what is required,
the workflow says what was measured, the hook says what runs before a commit.
:func:`drift` compares them, and a disagreement is a finding rather than a merge.

One pair was already compared: ``test_quality_contract.py`` has checked the ruff
hook against the ruff CI installs since Phase 004, by naming ``ruff`` in two
regular expressions. What is new here is generality — the same rule for any
``<tool>-pre-commit`` repository against any pinned distribution, so a second
hook is covered the day it is added.

**Canonical output.** Entries sort by a total key and render as one line of
JSON with sorted keys, so the same tree produces the same bytes on any machine.
Nothing here reads a clock, generates an identifier, or records an absolute
path.
"""

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.quality.supply.workflows import (
    action_repository,
    installed_pins,
    remote_references,
    workflow_paths,
)

PYPROJECT: Final[str] = "pyproject.toml"
PRE_COMMIT_CONFIG: Final[str] = ".pre-commit-config.yaml"
ACTION_PINS: Final[str] = "docs/engineering/action-pins.toml"

WORKFLOW_SOURCE_PREFIX: Final[str] = ".github/workflows/"
"""Written out rather than derived from the path, so the recorded source is
repository-relative and spelled identically on Windows and on a Linux runner."""

PYPI: Final[str] = "pypi"
GITHUB_ACTIONS: Final[str] = "github-actions"
PRE_COMMIT: Final[str] = "pre-commit"
"""The three ecosystems this repository actually has.

Named as constants rather than written inline because the same things are spelled
differently in three places: Dependabot's configuration says ``pip`` and
``github-actions``, the SBOM says ``pkg:pypi`` and ``pkg:github``, and this module
says the above. Three vocabularies is enough without a fourth appearing by typo.

:data:`PRE_COMMIT` is separate from :data:`GITHUB_ACTIONS` even though every hook
repository here is hosted on GitHub, because the two are not interchangeable to
anything downstream: Dependabot's ``github-actions`` ecosystem does not update a
``.pre-commit-config.yaml`` revision, and reporting a hook as an action would
promise coverage that does not exist.
"""

RUNTIME: Final[str] = "runtime"
DEVELOPMENT: Final[str] = "development"
BUILD: Final[str] = "build"
CONTINUOUS_INTEGRATION: Final[str] = "continuous-integration"
HOOK: Final[str] = "hook"

PINNED: Final[str] = "pinned"
"""An exact version or an immutable revision. Two runs get the same artefact."""

RANGED: Final[str] = "ranged"
"""A bound rather than a version. What it resolves to depends on when you ask."""

#: A requirement's distribution name and whatever follows it. Deliberately not a
#: PEP 508 parser: this repository's requirements are `name`, `name>=x` and
#: `name==x`, and a parser for the rest of PEP 508 would be code with no caller.
REQUIREMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<specifier>.*)$"
)

#: An exactly-pinned requirement, so that `ruff==0.15.14` is distinguished from
#: `ruff>=0.6`. Only `==` counts; `~=` and `<=` bound rather than fix.
EXACT_SPECIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^==\s*(?P<version>[A-Za-z0-9._+!-]+)$")

#: A `repo:`/`rev:` pair in the pre-commit configuration. Read by regex for the
#: reason `workflows.py` gives at length: there is no YAML parser in this
#: toolchain and adding one is a dependency decision, not a convenience.
PRE_COMMIT_REPO_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s*repo:\s*(?P<repo>\S+)\s*$\n(?:^\s*#.*$\n)*^\s*rev:\s*(?P<rev>\S+)\s*$",
    re.MULTILINE,
)


class SupplyChainError(Exception):
    """A supply-chain fact could not be established.

    Raised rather than returned wherever the alternative would be a value that
    reads like an answer. A manifest that cannot be parsed produces this; it does
    not produce an empty inventory, because an empty inventory is indistinguishable
    from a repository with no dependencies and would be reported as clean.
    """


@dataclass(frozen=True, slots=True, order=True)
class Dependency:
    """One declared dependency, as one manifest declares it.

    Ordering is structural and total — ecosystem, then name, then version, then
    scope, then source — so that sorting a set of these is deterministic without
    any caller supplying a key. That is what makes the inventory and the SBOM
    byte-stable.

    Args:
        ecosystem: :data:`PYPI` or :data:`GITHUB_ACTIONS`.
        name: The canonical distribution or ``owner/repo`` name.
        version: An exact version, a forty-character commit, or the specifier
            when the declaration only bounds one.
        scope: What the dependency is for. A runtime dependency is a promise to
            whoever runs GLOBIN; a development one is not.
        resolution: :data:`PINNED` or :data:`RANGED`.
        source: The repository-relative manifest that declares it.
        direct: Whether a human wrote it down. Always ``True`` here — see the
            module docstring on why no transitive set is claimed.
    """

    ecosystem: str
    name: str
    version: str
    scope: str
    resolution: str
    source: str
    direct: bool = True

    @property
    def purl(self) -> str:
        """The package URL, as the CycloneDX components will carry it.

        Returns:
            ``pkg:pypi/<name>@<version>`` or ``pkg:github/<owner>/<repo>@<sha>``.

        A ranged dependency still gets one, carrying the specifier where a
        version would be. That is honest rather than tidy: the alternative is
        omitting the identifier, and a component with no identifier is a
        component no downstream tool can match against an advisory.
        """
        if self.ecosystem in {GITHUB_ACTIONS, PRE_COMMIT}:
            return f"pkg:github/{self.name}@{self.version}"
        return f"pkg:pypi/{self.name}@{self.version}"

    def as_document(self) -> dict[str, object]:
        """This dependency as JSON-ready values, with keys in no particular order.

        Returns:
            The mapping. Rendering sorts keys, so insertion order here is not a
            fact anybody depends on.
        """
        return {
            "ecosystem": self.ecosystem,
            "name": self.name,
            "version": self.version,
            "scope": self.scope,
            "resolution": self.resolution,
            "source": self.source,
            "direct": self.direct,
            "purl": self.purl,
        }


def _requirement(text: str, *, scope: str, source: str) -> Dependency:
    """Turn one requirement string into a dependency.

    Args:
        text: A requirement such as ``pytest>=8.0``.
        scope: What it is for.
        source: The manifest that declared it.

    Returns:
        The dependency, marked :data:`PINNED` only when the specifier is ``==``.

    Raises:
        SupplyChainError: If the string does not begin with a distribution name.
    """
    match = REQUIREMENT_RE.match(text.strip())
    if match is None:
        msg = f"{source} declares a requirement this reader cannot name: {text!r}"
        raise SupplyChainError(msg)

    specifier = match.group("specifier").strip()
    exact = EXACT_SPECIFIER_RE.match(specifier)
    return Dependency(
        ecosystem=PYPI,
        name=match.group("name").lower(),
        version=exact.group("version") if exact else (specifier or "*"),
        scope=scope,
        resolution=PINNED if exact else RANGED,
        source=source,
    )


def from_pyproject(repo_root: Path) -> tuple[Dependency, ...]:
    """Runtime, build and development dependencies, as ``pyproject.toml`` declares them.

    Args:
        repo_root: The repository root.

    Returns:
        Every declared requirement. Empty runtime dependencies produce no
        entries, which is correct and is asserted elsewhere: ``dependencies = []``
        is an invariant this repository enforces by contract test, not an
        oversight this module should paper over.

    Raises:
        SupplyChainError: If the file is missing or is not valid TOML.
    """
    path = repo_root / PYPROJECT
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as fault:
        msg = f"{PYPROJECT} is missing; there is no inventory to take without it"
        raise SupplyChainError(msg) from fault
    except tomllib.TOMLDecodeError as fault:
        msg = f"{PYPROJECT} is not valid TOML: {fault}"
        raise SupplyChainError(msg) from fault

    project = document.get("project", {})
    build_system = document.get("build-system", {})
    optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}

    found: list[Dependency] = []
    for requirement in project.get("dependencies", []) if isinstance(project, dict) else []:
        found.append(_requirement(requirement, scope=RUNTIME, source=PYPROJECT))
    for requirement in build_system.get("requires", []) if isinstance(build_system, dict) else []:
        found.append(_requirement(requirement, scope=BUILD, source=PYPROJECT))
    if isinstance(optional, dict):
        for extra in sorted(optional):
            for requirement in optional[extra]:
                found.append(_requirement(requirement, scope=DEVELOPMENT, source=PYPROJECT))
    return tuple(found)


def from_workflows(repo_root: Path) -> tuple[Dependency, ...]:
    """What continuous integration fetches and what it installs.

    Args:
        repo_root: The repository root.

    Returns:
        One entry per remote action, at :data:`GITHUB_ACTIONS`, and one per
        exactly-pinned package the workflows install, at :data:`PYPI` in the
        :data:`CONTINUOUS_INTEGRATION` scope.

    Raises:
        SupplyChainError: If two jobs pin one package to two versions.

    Actions repeated across jobs collapse to one entry. The same action at two
    different commits does not collapse, because those are two different programs.
    """
    found: list[Dependency] = []
    seen: set[tuple[str, str]] = set()

    for path in workflow_paths(repo_root):
        source = WORKFLOW_SOURCE_PREFIX + path.name
        text = path.read_text(encoding="utf-8")

        for reference, _ in remote_references(text):
            repository, revision = action_repository(reference), reference.partition("@")[2]
            if not revision or (repository, revision) in seen:
                continue
            seen.add((repository, revision))
            found.append(
                Dependency(
                    ecosystem=GITHUB_ACTIONS,
                    name=repository,
                    version=revision,
                    scope=CONTINUOUS_INTEGRATION,
                    resolution=PINNED,
                    source=source,
                )
            )

        try:
            pins = installed_pins(text)
        except ValueError as fault:
            raise SupplyChainError(str(fault)) from fault
        for name in sorted(pins):
            found.append(
                Dependency(
                    ecosystem=PYPI,
                    name=name.lower(),
                    version=pins[name],
                    scope=CONTINUOUS_INTEGRATION,
                    resolution=PINNED,
                    source=source,
                )
            )
    return tuple(found)


def from_pre_commit(repo_root: Path) -> tuple[Dependency, ...]:
    """Every hook repository the pre-commit configuration runs, at its pinned revision.

    Args:
        repo_root: The repository root.

    Returns:
        One entry per remote hook repository. A ``repo: local`` entry produces
        none: it names hooks defined in this file, which have no upstream and are
        already fixed by the commit under test — the same reasoning that exempts
        a ``./`` action reference.

    Raises:
        SupplyChainError: If the file is missing.
    """
    path = repo_root / PRE_COMMIT_CONFIG
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as fault:
        msg = f"{PRE_COMMIT_CONFIG} is missing; the hook toolchain cannot be inventoried"
        raise SupplyChainError(msg) from fault

    found: list[Dependency] = []
    for match in PRE_COMMIT_REPO_RE.finditer(text):
        repository = match.group("repo")
        if repository == "local":
            continue
        found.append(
            Dependency(
                ecosystem=PRE_COMMIT,
                name=repository.removeprefix("https://github.com/").removesuffix(".git"),
                version=match.group("rev"),
                scope=HOOK,
                resolution=PINNED,
                source=PRE_COMMIT_CONFIG,
            )
        )
    return tuple(found)


def collect(repo_root: Path) -> tuple[Dependency, ...]:
    """The whole declared inventory, canonically ordered.

    Args:
        repo_root: The repository root.

    Returns:
        Every dependency from every manifest, deduplicated and sorted by the
        dataclass's own ordering.

    Raises:
        SupplyChainError: If any manifest cannot be read.
    """
    found = set(from_pyproject(repo_root))
    found |= set(from_workflows(repo_root))
    found |= set(from_pre_commit(repo_root))
    return tuple(sorted(found))


HOOK_MIRROR_SUFFIX: Final[str] = "-pre-commit"
"""How a hook repository names the tool it wraps.

``astral-sh/ruff-pre-commit`` runs ``ruff``. The convention is the upstream
project's, not this repository's, which is why the suffix is matched rather than
a mapping table maintained: a table would need an entry added by hand for every
new hook, and the one nobody adds is the one that drifts.
"""


def drift(dependencies: tuple[Dependency, ...]) -> tuple[str, ...]:
    """Where the three registers disagree about one tool.

    Args:
        dependencies: The collected inventory.

    Returns:
        One sentence per disagreement, empty when the registers agree.

    Three disagreements are worth catching.

    A package the workflow installs at an exact version while ``pyproject.toml``
    does not declare it at all is a tool CI measures with and a developer would
    not install. A package pinned to a version its own declared lower bound
    excludes is a pin nobody could satisfy.

    And a hook revision that disagrees with the version CI installs is the one
    that bites hardest, because both halves pass on their own: a developer would
    commit through a hook calling a file clean and watch CI call it dirty, with
    no diff between them to explain why.

    ``test_the_hook_ruff_and_the_ci_ruff_are_the_same_version`` in
    ``tests/contract/test_quality_contract.py`` has checked that for **ruff**
    since Phase 004, and it is what caught this repository's first Dependabot
    pull request. It names ``ruff`` in two regular expressions, so it covers one
    pair. This generalises the same rule to any ``<tool>-pre-commit`` repository
    against any pinned distribution, so a second hook is covered the day it is
    added rather than the day somebody remembers to widen a regex.
    """
    declared = {entry.name: entry for entry in dependencies if entry.source == PYPROJECT}
    installed = {
        entry.name: entry
        for entry in dependencies
        if entry.ecosystem == PYPI and entry.scope == CONTINUOUS_INTEGRATION
    }
    problems: list[str] = []

    for entry in installed.values():
        matching = declared.get(entry.name)
        if matching is None:
            problems.append(
                f"{entry.source} installs {entry.name}=={entry.version}, which "
                f"{PYPROJECT} does not declare; CI measures with a tool the "
                f"documented toolchain does not contain"
            )
            continue
        if matching.resolution == RANGED and not _satisfies(entry.version, matching.version):
            problems.append(
                f"{entry.source} pins {entry.name}=={entry.version}, which does not "
                f"satisfy the {matching.version!r} declared in {PYPROJECT}"
            )

    for entry in dependencies:
        if entry.ecosystem != PRE_COMMIT:
            continue
        tool = entry.name.rpartition("/")[2].removesuffix(HOOK_MIRROR_SUFFIX)
        if tool == entry.name.rpartition("/")[2]:
            continue
        mirrored = installed.get(tool.lower())
        if mirrored is None:
            continue
        if entry.version.removeprefix("v") != mirrored.version:
            problems.append(
                f"{PRE_COMMIT_CONFIG} pins {entry.name} at {entry.version} while "
                f"{mirrored.source} installs {tool}=={mirrored.version}; the hook and "
                f"the gate would disagree about whether a file is clean"
            )
    return tuple(problems)


def _satisfies(version: str, specifier: str) -> bool:
    """Whether an exact version satisfies a ``>=`` lower bound.

    Args:
        version: The exact version CI installs.
        specifier: The declared bound, such as ``>=8.0``.

    Returns:
        ``True`` when the bound is one this reader understands and the version
        clears it, and ``True`` for any bound it does not understand.

    Deliberately narrow, and deliberately permissive about what it cannot read.
    Every specifier in this repository is ``>=``. A full PEP 440 comparison is a
    dependency (``packaging``) and Phase 020's subject; guessing at one here and
    reporting a false disagreement would be worse than reporting none, because a
    gate that cries wolf is a gate somebody switches off.
    """
    if not specifier.startswith(">="):
        return True
    bound = specifier.removeprefix(">=").strip()
    return _release(version) >= _release(bound)


def _release(version: str) -> tuple[int, ...]:
    """The leading numeric release segment of a version, for comparison.

    Args:
        version: A version string.

    Returns:
        Its dotted numeric prefix. ``0.15.14`` becomes ``(0, 15, 14)``; a segment
        that is not a number ends the tuple, so ``1.0rc1`` becomes ``(1, 0)``.
    """
    parts: list[int] = []
    for segment in version.split("."):
        digits = ""
        for character in segment:
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        parts.append(int(digits))
        if digits != segment:
            break
    return tuple(parts)


def render(dependencies: tuple[Dependency, ...]) -> str:
    """The inventory as canonical JSON.

    Args:
        dependencies: The collected inventory, already ordered.

    Returns:
        One line of JSON followed by a newline, sorted keys, ASCII only — the
        same conventions ``tools/quality/evidence/manifest.py`` established, for
        the same reason: two writers must not be able to disagree about bytes.
    """
    document = {
        "ecosystems": sorted({entry.ecosystem for entry in dependencies}),
        "dependencies": [entry.as_document() for entry in dependencies],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
