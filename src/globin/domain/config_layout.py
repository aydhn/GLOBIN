"""Where GLOBIN's configuration documents live, and what shape a profile name has.

[`configuration.py`](configuration.py) owns the *model*: what a setting is, how
layers fold, and which values are refused. This module owns the *layout*: which
documents exist, what they are called, and how a profile name is spelled. The
split is the one ADR-0027 drew — a source is handed a path and never searches for
one — and this module is what finally supplies the paths without breaking it.

**Nothing here searches.** Given a layout and a profile, the set of candidate
documents is a pure function of the two. There is no upward walk, no fallback
chain and no "first one that exists wins", because each of those is a *precedence*
decision. `adapters/configuration.py` says the path is given rather than guessed;
this module keeps that sentence true by computing spellings rather than by looking
anything up.

**Phase 027 answered the precedence question, and the answer is one function.**
:func:`precedence` declares the order the four roles fold in, and it is the only
place that order exists. What did *not* change is
:meth:`ConfigLayout.documents_for`'s return type: it still hands back a mapping,
because the *set* of candidates and the *order* they fold in are different facts
and conflating them is how a reader starts believing a listing order is a
precedence. Ask `documents_for` what exists; ask :func:`precedence` what wins.

**This module registers a kind, never the instances**, which is `identifiers.py`'s
discipline applied to a second subject. It states what a profile name may look
like and refuses anything else; it does **not** enumerate the four the programme
schedules. Those live in `globin.runtime.composition`, beside `DEFAULT_PROFILE`,
which is where the placeholder they replace has sat since Phase 022.

That placement is not tidiness. Three of the four names — `demo`, `testnet`,
`live` — are venue vocabulary, and
`tests/architecture/test_identifier_discipline.py` refuses venue vocabulary as a
live constant anywhere under `globin.domain`. The refusal is right and it is not
worked around here: a set of environment names compiled into the innermost layer
would answer, quietly and in the wrong place, the question Phase 035 exists to
ask. The domain bounds the shape; the composition root names the instances; and
because the set is supplied rather than assumed, an unknown name is still
**refused** rather than matched to a neighbour or silently defaulted.

**A profile names a document. It does not name an environment.** Phase 035 decides
what an environment *is* and Phase 036 which product/environment pairs are usable.
The boundary is also held by a mechanism that already exists: `as_config` rejects
every key outside `known_keys()`, and not one of those keys can say anything about
a venue, a URL or a product. **A profile document is structurally incapable of
asserting what an environment is**, which is stronger than a rule anybody has to
remember.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.runtime_state import segment_problems
from globin.errors import ConfigurationError, InternalError, ValidationError

#: The separator between segments of a project-relative document spelling.
#:
#: POSIX, on Windows, deliberately. These strings are compared in tests, written
#: into evidence and read by people; a backslash would make the same document
#: spell differently depending on who wrote the string down. `RecordedPath`
#: reaches the same conclusion for the same reason.
PATH_SEPARATOR: Final[str] = "/"

#: The extension every configuration document carries.
#:
#: TOML because `tomllib` is already in the I/O-capable list, already what
#: `TomlConfigurationSource` reads, and already what `flatten()` is written
#: against. The argument that is *not* merely "it is already here": `tomllib` is
#: read-only, so GLOBIN can never write a configuration file back, and an
#: operator's comments and ordering cannot be destroyed by the program.
DOCUMENT_SUFFIX: Final[str] = ".toml"

#: Every character a profile name may contain.
#:
#: Written out rather than compiled, for the reason `EVENT_NAME_ALPHABET` gives
#: about itself: a layer package performs no call at import, so `re.compile` is
#: unavailable, and a spelled alphabet is readable by somebody who does not read
#: regular expressions. Lowercase only, because a profile name reaches a filename
#: and Windows compares filenames case-insensitively — two profiles differing only
#: in case would name one document.
PROFILE_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz"

#: The shortest a profile name may be.
MINIMUM_PROFILE_LENGTH: Final[int] = 3

#: The longest a profile name may be.
#:
#: Short on purpose. A profile name appears in a filename, in the instance record
#: and in every health snapshot; a long one is a description wearing a name's
#: clothes.
MAXIMUM_PROFILE_LENGTH: Final[int] = 16


class ConfigRole(StrEnum):
    """What one configuration document is *for*.

    Four roles rather than four paths, so that Phase 027 can order them without
    this module having expressed an opinion about the order.

    `BASE` and `PROFILE` are committed and reviewable. `LOCAL_BASE` and
    `LOCAL_PROFILE` are the operator's own and are Git-ignored — defence in depth
    rather than a licence, because `SECURITY_BASELINE.md` says a secret never
    arrives through configuration at all and Phase 028 stores a *reference*.
    """

    BASE = "base"
    PROFILE = "profile"
    LOCAL_BASE = "local_base"
    LOCAL_PROFILE = "local_profile"


@dataclass(frozen=True, slots=True)
class ConfigLayout:
    """Where configuration documents sit, relative to the project root.

    Args:
        directory: The configuration tree's own directory.
        profiles_directory: Where the profile documents sit inside it.
        local_directory: Where an operator's uncommitted documents sit inside it.
        base_name: The document that applies whatever profile is selected.

    Raises:
        ValidationError: If any segment could leave the configuration tree.

    Every field is a single segment validated on construction by the same
    :func:`~globin.domain.runtime_state.segment_problems` the runtime tree uses.
    Sharing that validator rather than restating it is deliberate: the four
    escapes it refuses — ``..``, a separator, a drive letter, an empty string —
    are the same four here, and two copies would eventually disagree.
    """

    directory: str = "config"
    profiles_directory: str = "profiles"
    local_directory: str = "local"
    base_name: str = "globin.toml"

    def __post_init__(self) -> None:
        """Refuse a layout that could address anything outside its own directory."""
        problems = [
            problem
            for name, segment in self.declared().items()
            for problem in segment_problems(segment, named=name)
        ]
        if not self.base_name.endswith(DOCUMENT_SUFFIX):
            problems.append(
                f"the base_name segment {self.base_name!r} does not end in {DOCUMENT_SUFFIX!r}"
            )
        if problems:
            raise ValidationError("; ".join(problems))

    def declared(self) -> dict[str, str]:
        """Every declared segment, by field name.

        Returns:
            Field name to segment.
        """
        return {
            "directory": self.directory,
            "profiles_directory": self.profiles_directory,
            "local_directory": self.local_directory,
            "base_name": self.base_name,
        }

    def document_for(self, role: ConfigRole, profile: str) -> str:
        """The project-relative spelling of one document.

        Args:
            role: Which of the four documents.
            profile: Which profile, used by the two profile roles and ignored by
                the two base ones.

        Returns:
            A POSIX, project-relative path with no leading separator.

        Raises:
            ValidationError: If the profile name is not canonical.
            InternalError: If the role has no spelling, which can only happen
                if :class:`ConfigRole` gained a member and `_spellings` did
                not. That is a GLOBIN defect rather than a caller's mistake,
                which is why it is not a `ConfigurationError`.

        The profile is validated here rather than trusted, because this is the
        function that turns it into a path. A name that reached this point
        unchecked would be a caller-supplied filename.
        """
        problems = profile_problems(profile)
        if problems:
            raise ValidationError("; ".join(problems))
        declared = self._spellings(f"{profile}{DOCUMENT_SUFFIX}")
        spelling = declared.get(role)
        if spelling is None:
            msg = (
                f"config role {role!r} has no document; every member of ConfigRole "
                f"must be spelled in ConfigLayout._spellings()"
            )
            raise InternalError(msg)
        return spelling

    def _spellings(self, document: str) -> dict[ConfigRole, str]:
        """Every role's spelling, for one already-validated profile document.

        Args:
            document: The profile's filename, suffix included.

        Returns:
            Each role mapped to its project-relative spelling.

        A mapping rather than an ``if`` chain over the members, which is
        :func:`~globin.domain.identifiers.specification`'s shape and is chosen for
        its reason: a lookup that can miss keeps the "this module was edited in
        half" branch **reachable**, where a chain mypy can prove exhaustive makes
        the same branch unreachable and `warn_unreachable` refuses the module.
        """
        return {
            ConfigRole.BASE: self._join(self.directory, self.base_name),
            ConfigRole.PROFILE: self._join(self.directory, self.profiles_directory, document),
            ConfigRole.LOCAL_BASE: self._join(self.directory, self.local_directory, self.base_name),
            ConfigRole.LOCAL_PROFILE: self._join(
                self.directory, self.local_directory, self.profiles_directory, document
            ),
        }

    def documents_for(self, profile: str) -> dict[ConfigRole, str]:
        """Every candidate document for one profile.

        Args:
            profile: Which profile.

        Returns:
            Each role mapped to its project-relative spelling.

        Raises:
            ValidationError: If the profile name is not canonical.

        **A mapping, never a sequence.** A tuple has an order and a reader would
        read that order as precedence. Which documents are consulted, in what
        order, and whether a missing one is fatal are all Phase 027's, and the
        return type is where that boundary is held rather than in a comment.
        """
        return {role: self.document_for(role, profile) for role in roles()}

    def local_prefix(self) -> str:
        """The project-relative directory holding the operator's own documents.

        Returns:
            A POSIX, project-relative path with no leading separator.

        Exists so that `.gitignore` and the contract test that reads it can name
        the same directory without either spelling it by hand.
        """
        return self._join(self.directory, self.local_directory)

    def _join(self, *segments: str) -> str:
        """Join validated segments into a project-relative spelling.

        Args:
            segments: The segments, in order.

        Returns:
            The joined spelling.
        """
        return PATH_SEPARATOR.join(segments)


def roles() -> tuple[ConfigRole, ...]:
    """Every configuration role.

    Returns:
        The four roles, in declaration order.

    A function rather than a module-level constant because a layer package
    performs no call at import, which rules out both ``frozenset({...})`` and
    ``tuple(ConfigRole)``. Declaration order here is a *listing* order for
    documents and tests; it is emphatically not a precedence, which is why
    :meth:`ConfigLayout.documents_for` returns a mapping and why
    :func:`precedence` exists separately.
    """
    return (
        ConfigRole.BASE,
        ConfigRole.PROFILE,
        ConfigRole.LOCAL_BASE,
        ConfigRole.LOCAL_PROFILE,
    )


def precedence() -> tuple[ConfigRole, ...]:
    """The order the four documents fold in, weakest first.

    Returns:
        Every role exactly once, weakest first, so the last one that mentions a
        key wins.

    **This is the whole of Phase 027's document-ordering decision**, and it is one
    function so that there is one place to read it and one place to change it.

    The order encodes two rules, each with a reason a reader can check:

    * **Specific beats general.** A profile document is chosen deliberately for
      this run, so it outranks the base document that applies to every run.
    * **Uncommitted beats committed.** The two `local` documents are the
      operator's own and are Git-ignored, so they exist precisely to override what
      the repository ships. If they were folded first they could never override
      anything and there would be no reason for them.

    Composing the two gives base, profile, local base, local profile — which is
    :func:`roles`' declaration order. **That coincidence is not the reason**, and
    the two functions stay separate because of it rather than in spite of it: a
    later layout that added a role would have to decide where it folds, and a
    reader who had been told "the listing order is the precedence" would not know
    that a decision was owed.

    Nothing here says whether a missing document is fatal. That is a property of
    the *source*, not of the order, and `adapters/configuration.py` answers it.
    """
    return (
        ConfigRole.BASE,
        ConfigRole.PROFILE,
        ConfigRole.LOCAL_BASE,
        ConfigRole.LOCAL_PROFILE,
    )


def profile_problems(name: str) -> tuple[str, ...]:
    """Judge whether a string is a canonical profile name.

    Args:
        name: The candidate.

    Returns:
        One sentence per reason it is not, empty when it is canonical.

    Problems rather than an exception, so a caller checking several names reports
    all of them at once — the shape `member_problems` and `segment_problems`
    already have.

    This is the *kind*, not the register. It says nothing about which profiles
    exist, which is :func:`resolve_profile`'s question and the composition root's
    data.
    """
    problems: list[str] = []
    if not name:
        return ("the profile name is empty",)
    if len(name) < MINIMUM_PROFILE_LENGTH:
        problems.append(
            f"the profile name {name!r} is shorter than {MINIMUM_PROFILE_LENGTH} characters"
        )
    if len(name) > MAXIMUM_PROFILE_LENGTH:
        problems.append(
            f"the profile name {name!r} is longer than {MAXIMUM_PROFILE_LENGTH} characters"
        )
    outside = sorted({character for character in name if character not in PROFILE_ALPHABET})
    if outside:
        problems.append(
            f"the profile name {name!r} contains {''.join(outside)!r}, "
            f"which is outside the profile alphabet"
        )
    return tuple(problems)


def resolve_profile(name: str, declared: Sequence[str]) -> str:
    """Resolve a profile name against the set that exists, refusing anything else.

    Args:
        name: The candidate spelling.
        declared: Every profile this installation declares, in listing order.

    Returns:
        The declared spelling it names.

    Raises:
        ConfigurationError: If it names none of them, or if ``declared`` is empty.

    **Refusal, never a nearest match and never a default.** A name that is nearly
    ``live`` is not ``live``, and a selection that silently became something else
    because it was misspelled would be a configuration error reported as a
    successful start. The message names every accepted spelling, which is what
    ``_severity`` does for the same reason: the reader is one line from the fix.

    Case and surrounding whitespace are forgiving because a profile name arrives
    from a launcher argument or an environment variable, where both are accidents
    of transport rather than of intent. Nothing else is.
    """
    if not declared:
        msg = "no profile is declared, so no profile name can be resolved"
        raise ConfigurationError(msg)
    candidate = name.strip().lower()
    for profile in declared:
        if candidate == profile:
            return profile
    accepted = ", ".join(declared)
    msg = f"{name!r} is not a profile; accepted profiles are {accepted}"
    raise ConfigurationError(msg)


def profile_from(
    *,
    requested: str | None,
    environment_value: str | None,
    declared: Sequence[str],
    default: str,
) -> str:
    """Decide which profile a run uses: from the launcher, the environment, or neither.

    Args:
        requested: What a launcher argument asked for, or ``None`` when it said
            nothing. A string of whitespace also counts as saying nothing.
        environment_value: What the environment asked for, or ``None``.
        declared: Every profile this installation declares.
        default: The profile to use when nobody asked.

    Returns:
        The declared spelling of the selected profile.

    Raises:
        ConfigurationError: If a selection names no declared profile, or if the
            default itself is not declared.

    **Launcher beats environment beats default, and that order is the only thing
    this function decides.** The reasoning is the one every precedence in Phase 027
    follows: the more deliberate act wins. A launcher argument is a decision taken
    for this run; an exported variable is a decision taken for a shell and then
    forgotten about; a default is nobody's decision at all.

    **A selection that names nothing is refused, never defaulted.** A misspelled
    profile quietly becoming the safe one would be the reassuring half of a bad
    mechanism — the same mistake in the other direction is a misspelling that
    quietly becomes ``live``, and refusing both is how one rule covers both. The
    default is reached only when *nobody asked*, which is a different situation from
    somebody asking and being wrong.

    This is the profile half of Phase 027's ordering; :func:`precedence` is the
    document half. They live in one module because a reader who wants to know how a
    profile reaches a document should not have to find two.
    """
    for candidate in (requested, environment_value):
        if candidate is not None and candidate.strip():
            return resolve_profile(candidate, declared)
    return resolve_profile(default, declared)
