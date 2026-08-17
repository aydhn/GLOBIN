"""The configuration layout, held against the tree and against the roadmap.

`test_config_layout.py` owns the kind — what a layout computes and which names it
refuses. This module owns the register: that the profiles the composition root
declares are the ones `ROADMAP.md` row 026 names, that every one of them has a
committed document where the layout says it would be, and that none of those
documents can assert anything the model would not accept.
"""

import tomllib
from pathlib import Path

import pytest

from globin.adapters.configuration import flatten
from globin.domain.config_layout import ConfigRole
from globin.domain.configuration import (
    ConfigLayer,
    as_config,
    default_config,
    default_layer,
    resolve,
)
from globin.domain.observability import is_sensitive
from globin.runtime.composition import DEFAULT_PROFILE, PROFILES, build_config_layout
from tests.support import parse_roadmap

CONFIGURATION_PHASE: int = 26
"""The roadmap row whose purpose text names the profiles."""


def _layer_for(document: Path, origin: str) -> ConfigLayer:
    """Read one configuration document as a layer.

    Args:
        document: The file.
        origin: What to call it when a value is refused.

    Returns:
        The layer it flattens to.
    """
    values = flatten(tomllib.loads(document.read_text(encoding="utf-8")), origin)
    return ConfigLayer(origin=origin, values=tuple(sorted(values.items())))


# ---------------------------------------------------------------------------
# The register, against the roadmap
# ---------------------------------------------------------------------------


def test_the_declared_profiles_are_the_ones_the_roadmap_names(repo_root: Path) -> None:
    """`ROADMAP.md` row 026 is the source; `PROFILES` is a restatement of it.

    `MEMORY.md`'s standing rule is that a number or a list written in prose is
    bound to the thing it describes. The four names appear in the roadmap's own
    purpose text, so that sentence is what this compares against — in both
    directions, so a fifth profile added to either side fails.
    """
    rows = {row.phase: row for row in parse_roadmap((repo_root / "ROADMAP.md").read_text("utf-8"))}
    purpose = rows[CONFIGURATION_PHASE].purpose.lower()
    for profile in PROFILES:
        assert profile in purpose, f"{profile!r} is declared but the roadmap row does not name it"
    named = [word.strip(" ,.") for word in purpose.split() if word.strip(" ,.") in set(PROFILES)]
    assert set(named) == set(PROFILES)


def test_the_default_profile_is_declared_and_is_not_live() -> None:
    """ADR-0006's rule, read in the direction nobody writes down.

    "Never downgraded to production" also means never silently *upgraded* to it,
    and a default is the quietest upgrade there is.
    """
    assert DEFAULT_PROFILE in PROFILES
    assert DEFAULT_PROFILE != "live"


# ---------------------------------------------------------------------------
# The register, against the tree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_every_declared_profile_has_a_committed_document(repo_root: Path, profile: str) -> None:
    """A profile nothing can select is a name, not a profile."""
    layout = build_config_layout()
    document = repo_root / layout.document_for(ConfigRole.PROFILE, profile)
    assert document.is_file(), f"{profile!r} is declared but {document} does not exist"


def test_every_committed_profile_document_is_declared(repo_root: Path) -> None:
    """The other direction, so a stale document cannot survive a rename."""
    layout = build_config_layout()
    directory = repo_root / layout.directory / layout.profiles_directory
    found = sorted(path.stem for path in directory.glob("*.toml"))
    assert found == sorted(PROFILES)


def test_the_base_document_exists(repo_root: Path) -> None:
    """The one document that applies whatever profile is selected."""
    layout = build_config_layout()
    assert (repo_root / layout.document_for(ConfigRole.BASE, DEFAULT_PROFILE)).is_file()


def test_the_operator_directory_is_ignored_and_absent(repo_root: Path) -> None:
    """`config/local/` belongs to the machine, and the ignore rule precedes it.

    Anchored with a leading slash on purpose: a bare `local/` would match at every
    depth, which is how Phase 018 silently lost a whole package.
    """
    layout = build_config_layout()
    ignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert f"/{layout.local_prefix()}/" in ignore
    assert not (repo_root / layout.local_prefix()).exists()


# ---------------------------------------------------------------------------
# What a document can and cannot say
# ---------------------------------------------------------------------------


def test_every_committed_document_binds_and_changes_nothing(repo_root: Path) -> None:
    """Four properties in one assertion, and the fourth is the deliverable.

    Each document parses as TOML; each flattens without a dotted-key collision;
    none carries a key `as_config` would refuse; and folding all of them over the
    declared defaults produces exactly the declared defaults.

    That last one is the point. GLOBIN does not trade, so there is no setting that
    differs between the four profiles for a reason anybody could defend today, and
    writing one in would be inventing a difference to justify the files. This test
    is what makes "a profile changes nothing yet" a decision rather than an
    oversight — the day one of them sets a value, this fails and somebody has to
    say why.
    """
    layout = build_config_layout()
    directory = repo_root / layout.directory
    documents = sorted(path for path in directory.rglob("*.toml"))
    assert documents, "no configuration document was found"
    layers = [
        _layer_for(document, document.relative_to(repo_root).as_posix()) for document in documents
    ]
    assert as_config(resolve([default_layer(), *layers])) == default_config()


def test_no_committed_document_carries_a_credential_shaped_setting(repo_root: Path) -> None:
    """A profile document is committed and world-readable; treat it as public.

    The model already makes an environment claim unrepresentable — `as_config`
    refuses every key outside `known_keys()`. This covers the half a key check
    cannot: a *setting* whose name says it holds a credential.

    **The parsed document, never the raw text.** A first version of this compared
    the file's characters and failed on `config/globin.toml`'s own header comment,
    which warns a reader that no secret belongs here — the trap `MEMORY.md`
    records as "a test asserting a forbidden string will match a comment that
    names it". A comment *mentioning* a credential is documentation; a key or
    value *carrying* one is the defect, and only the second survives parsing.

    `is_sensitive` is reused rather than restated, so this check and the redaction
    the logger performs cannot drift apart.
    """
    layout = build_config_layout()
    for document in sorted((repo_root / layout.directory).rglob("*.toml")):
        origin = document.relative_to(repo_root).as_posix()
        for key, value in _layer_for(document, origin).values:
            assert not is_sensitive(key), f"{origin} declares the credential-shaped key {key!r}"
            assert not is_sensitive(str(value)), f"{origin} carries a credential-shaped value"


def test_the_documents_carry_the_sections_the_model_declares(repo_root: Path) -> None:
    """An empty document is the identity element, but it should still say so.

    A file with no section headers at all would leave a reader guessing what may
    go in it. A file whose headers name sections the model does not have would be
    worse. Both are checked here rather than trusted to review.
    """
    declared = set(default_config().__dataclass_fields__)
    layout = build_config_layout()
    for document in sorted((repo_root / layout.directory).rglob("*.toml")):
        sections = set(tomllib.loads(document.read_text(encoding="utf-8")))
        assert sections, f"{document} declares no section"
        assert sections <= declared, f"{document} names a section the model does not have"
