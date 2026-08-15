"""Reading a workflow file without a YAML parser, and judging what it fetches.

**Why there is no parser here.** PyYAML would be a seventh entry in a toolchain
three contract tests pin at six, and it is present on this machine only as a
transitive dependency of ``pre-commit``, which four of the six CI jobs do not
install — so a module importing it would work here and fail there.
[ADR-0043](../../../docs/adr/0043-ci-trust-is-declared-in-a-manifest-and-every-job-is-bounded.md)
refused it for exactly that reason. The patterns below are therefore narrow on
purpose: they recognise the specific shapes this policy covers and make no
attempt to understand YAML.

**Why the parser lives here rather than in the test that first needed it.**
It was written in ``tests/contract/test_ci_security_contract.py`` at Phase 013,
which was the right place while only that test read a workflow. Phase 014 needs
the same reading to build a dependency inventory, and ``tools`` cannot import
``tests``. Copying it would have produced two parsers that agree until the day
they do not — ``docs/engineering/SOURCE_OF_TRUTH.md`` calls that drift. The
functions moved here unchanged; the contract test now imports them and still
exercises every one against a deliberately broken copy.

Every function returns *what is wrong* rather than a boolean, so a caller
reporting a failure can name the offender instead of announcing that something,
somewhere, is off.
"""

import re
from pathlib import Path
from typing import Final

WORKFLOW_DIRECTORY: Final[str] = ".github/workflows"
"""Where GitHub looks for workflows, and therefore where this module does."""

#: A `uses:` line, with the trailing version comment when there is one. The
#: comment is optional in the pattern and mandatory in the contract, so that a
#: missing one is reported by name rather than silently not matching.
ACTION_USE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)(?:[ \t]+#[ \t]*(?P<comment>\S+))?[ \t]*$",
    re.MULTILINE,
)

#: A reference pinned to a full commit: owner, repository, optional subdirectory,
#: then exactly forty lowercase hex characters. The anchors are what make the
#: length exact — thirty-nine fails to reach the end, forty-one leaves a
#: character behind, and an uppercase or non-hex digit matches nothing.
SHA_PINNED_RE: Final[re.Pattern[str]] = re.compile(
    r"^[\w.\-]+/[\w.\-]+(?:/[\w.\-]+)*@[0-9a-f]{40}$"
)

#: A version comment worth having: `v` and three dotted numbers. A bare major
#: such as `v5` is refused because it is precisely the ambiguity the pin removes.
VERSION_COMMENT_RE: Final[re.Pattern[str]] = re.compile(r"^v\d+\.\d+\.\d+$")

#: A Docker action reference. `uses: docker://image:tag` is mutable in exactly the
#: way a Git tag is; only a `@sha256:` digest freezes it. None is used today, and
#: the check exists so that adding one is a decision rather than an accident.
DOCKER_USE_RE: Final[re.Pattern[str]] = re.compile(r"^docker://(?P<image>.+)$")

#: A Docker reference frozen to a content digest.
DOCKER_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^docker://.+@sha256:[0-9a-f]{64}$")

#: A job key: two spaces, a name, a colon, nothing else. Only ever applied to the
#: region after `jobs:`, because the trigger block has keys at that indentation.
JOB_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^  ([a-z][\w-]*):$", re.MULTILINE)

#: The first top-level key, used to find where a top-level block ends. Comments
#: begin with `#` and blank lines are empty, so neither can end a block early.
TOP_LEVEL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z]", re.MULTILINE)

#: The start of a `run:` step, capturing its indentation and whatever follows.
RUN_START_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<indent> *)(?:- )?run:(?P<rest>.*)$")

#: The block scalar indicators. A `run:` introduced by one of these carries its
#: body on the following lines rather than on its own.
BLOCK_SCALARS: Final[frozenset[str]] = frozenset({"|", "|-", "|+", ">", ">-", ">+"})

#: An exact version pin inside a `pip install` line: `"name==version"`. Only the
#: `==` form is recognised, because only that form is a pin. A range is a
#: resolution instruction, and what it resolves to is not knowable from the text.
PIP_PIN_RE: Final[re.Pattern[str]] = re.compile(r"[\"']([A-Za-z0-9._-]+)==([A-Za-z0-9._+!-]+)[\"']")


def workflow_paths(repo_root: Path) -> tuple[Path, ...]:
    """Every workflow file in the repository, in a stable order.

    Args:
        repo_root: The repository root.

    Returns:
        Each ``.yml`` and ``.yaml`` file under ``.github/workflows``, sorted by
        name so that two runs enumerate them identically.

    Sorted rather than left in directory order because directory order is a
    filesystem property, and an inventory whose contents depend on one is not
    reproducible on another machine.
    """
    directory = repo_root / WORKFLOW_DIRECTORY
    if not directory.is_dir():
        return ()
    found = [path for path in directory.iterdir() if path.suffix in {".yml", ".yaml"}]
    return tuple(sorted(found, key=lambda path: path.name))


def top_level_block(text: str, key: str) -> str:
    """Everything under a top-level key, up to the next one.

    Args:
        text: The workflow.
        key: The top-level key, without its colon.

    Returns:
        The block's body, or the empty string if the key is absent.
    """
    parts = text.split(f"\n{key}:\n", maxsplit=1)
    if len(parts) == 1:
        return ""
    rest = parts[1]
    end = TOP_LEVEL_KEY_RE.search(rest)
    return rest[: end.start()] if end else rest


def job_blocks(text: str) -> dict[str, str]:
    """Split the jobs region into one block per job.

    Args:
        text: The workflow.

    Returns:
        Each job key mapped to its body, in declaration order.
    """
    region = text.split("\njobs:\n", maxsplit=1)[-1]
    keys = list(JOB_KEY_RE.finditer(region))
    blocks: dict[str, str] = {}
    for index, key in enumerate(keys):
        end = keys[index + 1].start() if index + 1 < len(keys) else len(region)
        blocks[key.group(1)] = region[key.end() : end]
    return blocks


def run_bodies(text: str) -> tuple[str, ...]:
    """Every shell script the workflow runs.

    Args:
        text: The workflow.

    Returns:
        One entry per ``run:`` step: the command itself for an inline step, and
        the whole indented body for a block scalar.

    Written by hand rather than by regex because a block scalar's extent is
    decided by indentation, which is the one thing a regular expression cannot
    follow. It reads only far enough to know where each script ends.
    """
    lines = text.splitlines()
    bodies: list[str] = []
    index = 0
    while index < len(lines):
        start = RUN_START_RE.match(lines[index])
        index += 1
        if start is None:
            continue
        rest = start.group("rest").strip()
        if rest not in BLOCK_SCALARS:
            bodies.append(rest)
            continue
        indent = len(start.group("indent"))
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            body.append(line)
            index += 1
        bodies.append("\n".join(body))
    return tuple(bodies)


def remote_references(text: str) -> tuple[tuple[str, str | None], ...]:
    """Every action this workflow fetches from elsewhere, with its version comment.

    Args:
        text: The workflow.

    Returns:
        Each remote ``uses:`` reference paired with its trailing comment, or
        ``None`` where there is no comment.

    A reference beginning with ``./`` names something inside this repository,
    which is already pinned by the commit being tested and has no upstream to be
    pinned to. Those are excluded here rather than exempted later.
    """
    return tuple(
        (match.group("ref"), match.group("comment"))
        for match in ACTION_USE_RE.finditer(text)
        if not match.group("ref").startswith("./")
    )


def unpinned_references(text: str) -> tuple[str, ...]:
    """Remote references not frozen to a full commit.

    Args:
        text: The workflow.

    Returns:
        Every offending reference, including duplicates, so a count means something.

    A ``docker://`` reference is judged by :func:`undigested_docker_references`
    instead: it is frozen by a content digest rather than by a commit, so testing
    it against the Git pattern would report every one of them as unpinned even
    when correctly digested.
    """
    return tuple(
        ref
        for ref, _ in remote_references(text)
        if not DOCKER_USE_RE.match(ref) and not SHA_PINNED_RE.match(ref)
    )


def undigested_docker_references(text: str) -> tuple[str, ...]:
    """Docker actions named by tag rather than by content digest.

    Args:
        text: The workflow.

    Returns:
        Every ``docker://`` reference without an ``@sha256:`` digest.

    ``docker://alpine:3.20`` is mutable in exactly the way ``actions/checkout@v5``
    is: the tag is a label the publisher can move. None is used in this repository
    today, which is why this is worth asserting — the check costs nothing until
    somebody pastes one in, and then it costs them a conversation.
    """
    return tuple(
        ref
        for ref, _ in remote_references(text)
        if DOCKER_USE_RE.match(ref) and not DOCKER_DIGEST_RE.match(ref)
    )


def undocumented_pins(text: str) -> tuple[str, ...]:
    """Pins with no readable version beside them, or an unreadable one.

    Args:
        text: The workflow.

    Returns:
        Every reference whose comment is missing or is not a three-part version.

    The three-part form is also what Dependabot writes when it updates a
    SHA-pinned action, so keeping the requirement here aligned with that keeps a
    Dependabot pull request compliant with this policy rather than in violation
    of it the moment it opens.
    """
    return tuple(
        ref
        for ref, comment in remote_references(text)
        if comment is None or not VERSION_COMMENT_RE.match(comment)
    )


def action_repository(reference: str) -> str:
    """The upstream repository a ``uses:`` reference comes from.

    Args:
        reference: A reference such as ``github/codeql-action/init@<sha>``.

    Returns:
        ``owner/repo``, with any subdirectory and revision removed.

    An action may live in a subdirectory of a repository — ``codeql-action/init``
    and ``codeql-action/analyze`` are two programs at one commit in one
    repository — and the thing that gets pinned, verified and recorded in
    ``action-pins.toml`` is the repository. Comparing the full path against the
    manifest would report a disagreement that is really a difference of
    vocabulary, and comparing it in an inventory would count one dependency
    twice.
    """
    path = reference.partition("@")[0]
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else path


def pinned_versions(text: str) -> dict[str, tuple[str, str]]:
    """What the workflow claims each pinned commit is.

    Args:
        text: The workflow.

    Returns:
        Each SHA mapped to the repository it was fetched from and the version the
        comment beside it claims. Repeated pins collapse, which is intended: the
        same commit named twice with two different versions is caught by the
        disagreement rather than by the repetition.

    The repository is normalised by :func:`action_repository`, so two subpaths of
    one repository at one commit — ``codeql-action/init`` and
    ``codeql-action/analyze`` — collapse to the single entry the manifest records.
    """
    claims: dict[str, tuple[str, str]] = {}
    for ref, comment in remote_references(text):
        if comment is None or "@" not in ref:
            continue
        claims[ref.partition("@")[2]] = (action_repository(ref), comment)
    return claims


def installed_pins(text: str) -> dict[str, str]:
    """Every exactly-pinned package the workflow installs, across all its jobs.

    Args:
        text: The workflow.

    Returns:
        Each distribution name mapped to the version pinned for it.

    Raises:
        ValueError: If one name is pinned to two different versions. Four jobs in
            this repository each install an overlapping subset of the same
            toolchain, and the whole point of writing exact versions in all of
            them is that they agree. Two jobs disagreeing is not an inventory
            question to be resolved by picking one — it is a defect, and a
            silently-picked winner would hide it.
    """
    pins: dict[str, str] = {}
    for body in run_bodies(text):
        for match in PIP_PIN_RE.finditer(body):
            name, version = match.group(1), match.group(2)
            existing = pins.get(name)
            if existing is not None and existing != version:
                msg = (
                    f"{name} is installed as {existing} by one job and {version} by "
                    f"another; the jobs must agree about the toolchain they measure with"
                )
                raise ValueError(msg)
            pins[name] = version
    return pins
