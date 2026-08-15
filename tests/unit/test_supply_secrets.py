"""The content secret scanner, and the property that it never repeats what it finds.

**Every credential-shaped string in this module is synthetic and worthless.** They
are the shapes each pattern is written for, built from repeated characters and
documentation placeholders, and none of them has ever been a live credential
anywhere. That is why this file appears in ``secrets.py``'s allowlist: a test
proving a pattern fires needs a string that matches it, and a scanner that
flagged its own test would be a scanner somebody switches off.

The most important test here is :func:`test_no_finding_contains_the_matched_text`.
Every other check is about whether the scanner sees a secret; that one is about
whether reporting it publishes the secret a second time — into a log, an
artifact and a CI step summary, all of which outlive the file.
"""

import json

import pytest

from tools.quality.supply import secrets

#: The two shapes `detect-private-key` also looks for, assembled at run time so
#: that neither literal ever appears in this file.
#:
#: The pre-commit hook is right to be suspicious of a source file carrying a PEM
#: header, and it flagged this one. Excluding the file from the hook was the
#: other option and the wrong one: it would switch off a real protection across a
#: whole file to silence one string. Splitting the literal keeps the hook fully
#: armed, and the scanner under test still receives exactly the bytes it is
#: written for.
_PEM_RSA: str = "-----BEGIN RSA PRIVATE" + " KEY-----"
_PEM_DSA: str = "-----BEGIN DSA PRIVATE" + " KEY-----"
_PUTTY: str = "PuTTY-User-Key" + "-File-2"

#: Synthetic values, one per pattern. Structurally valid, cryptographically
#: worthless: repeated characters and the placeholder AWS key from Amazon's own
#: documentation.
SAMPLES: dict[str, str] = {
    "private-key-header": _PEM_RSA,
    "github-token": "ghp_" + "A" * 36,
    "github-fine-grained-token": "github_pat_" + "B" * 60,
    "aws-access-key-id": "AKIAIOSFODNN7EXAMPLE",
    "slack-token": "xoxb-000000000000-abcdefghijkl",
    "google-api-key": "AIza" + "C" * 35,
    "telegram-bot-token": "123456789:AA" + "D" * 32,
    "putty-private-key": _PUTTY,
}

SCANNED_PATH = "src/globin/somewhere.py"
"""A path with no allowlist entry, so the patterns are live against it."""


def test_every_pattern_has_a_sample() -> None:
    """A pattern with no sample is a pattern nobody has watched fire.

    Asserted rather than assumed, so that adding a pattern without a sample fails
    here instead of shipping as coverage that does not exist.
    """
    assert set(SAMPLES) == set(secrets.PATTERNS)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_pattern_finds_its_own_shape(name: str) -> None:
    """Each pattern matches the thing it was written for."""
    found = secrets.scan_text(SCANNED_PATH, f"value = {SAMPLES[name]}")
    assert [entry.pattern for entry in found] == [name]
    assert found[0].line == 1
    assert found[0].path == SCANNED_PATH


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_no_finding_contains_the_matched_text(name: str) -> None:
    """The property the whole module exists to preserve.

    A scanner that prints what it found has published it again. The finding
    carries a truncated digest and nothing else, so this asserts the sample does
    not survive into the report in any form — not the value, and not a
    recognisable prefix of it.
    """
    sample = SAMPLES[name]
    finding = secrets.scan_text(SCANNED_PATH, f"value = {sample}")[0]
    rendered = json.dumps(finding.as_document())

    assert sample not in rendered
    assert sample[:12] not in rendered
    assert finding.fingerprint in rendered


def test_a_fingerprint_is_stable_and_short() -> None:
    """Two runs finding one secret must agree, or "still there" cannot be told from "new"."""
    first = secrets.fingerprint(_PEM_RSA)
    second = secrets.fingerprint(_PEM_RSA)
    assert first == second
    assert len(first) == secrets.FINGERPRINT_LENGTH
    assert first != secrets.fingerprint(_PEM_DSA)


def test_the_allowlist_is_per_file_and_per_pattern() -> None:
    """An exemption covers one pattern in one file, never a whole file.

    Exempting a file would blind the scanner to every other pattern in it, which
    is how an allowlist stops meaning anything.
    """
    allowed_path = "tools/quality/supply/secrets.py"
    assert not secrets.scan_text(allowed_path, SAMPLES["private-key-header"])

    for path, pattern in secrets.ALLOWED:
        assert pattern in secrets.PATTERNS, f"{path} exempts a pattern that does not exist"
        assert secrets.ALLOWED[path, pattern], "an exemption with no reason cannot be reviewed"


def test_an_allowlisted_file_is_still_scanned_for_nothing_else() -> None:
    """Every pattern is exempted in this module by name, which is the point.

    The entries are generated per pattern rather than as a wildcard, so a pattern
    added later is live here until somebody decides otherwise.
    """
    exempted = {pattern for path, pattern in secrets.ALLOWED if path.endswith("secrets.py")}
    assert exempted == set(secrets.PATTERNS)


def test_a_clean_file_produces_nothing() -> None:
    """The scanner is not an entropy heuristic, and this repository is full of digests.

    A forty-character commit, a SHA-256 and a Hypothesis seed all look random and
    none of them is a credential. A scanner that flagged them would be turned off
    within a week.
    """
    text = (
        "commit = 'fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09'\n"
        f"digest = 'sha256:{'e' * 64}'\n"
        "seed = 4294967295\n"
    )
    assert not secrets.scan_text(SCANNED_PATH, text)


def test_several_findings_in_one_file_are_reported_separately() -> None:
    """Naming the line beats reporting only that the file contains something."""
    text = f"one = {SAMPLES['aws-access-key-id']}\ntwo = {SAMPLES['github-token']}\n"
    found = secrets.scan_text(SCANNED_PATH, text)
    assert [entry.line for entry in found] == [1, 2]
    assert {entry.pattern for entry in found} == {"aws-access-key-id", "github-token"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("src/globin/thing.py", True, id="python"),
        pytest.param("LICENSE", True, id="no suffix"),
        pytest.param(".gitattributes", True, id="dotfile"),
        pytest.param("docs/diagram.png", False, id="image"),
        pytest.param("dist/globin.whl", False, id="wheel"),
    ],
)
def test_binary_files_are_not_read_as_text(path: str, expected: bool) -> None:
    """Judged by suffix, and by the POSIX flavour because ``git ls-files`` reports those."""
    assert secrets.scannable(path) is expected


def test_an_allowance_for_a_file_that_was_not_scanned_is_reported() -> None:
    """An allowlist keeping entries for deleted files is one nobody maintains."""
    stale = secrets.unused_allowances(frozenset({"tools/quality/supply/secrets.py"}))
    assert any("test_supply_secrets.py" in problem for problem in stale)


def test_no_allowance_is_stale_in_this_repository() -> None:
    """Both allowlisted files exist, so the register describes the tree it is in."""
    scanned = frozenset(path for path, _ in secrets.ALLOWED)
    assert not secrets.unused_allowances(scanned)
