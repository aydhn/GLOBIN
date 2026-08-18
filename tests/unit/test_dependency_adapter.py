"""Reading a lock, the marker environment and what is installed.

Every lock document here is a literal string, so a malformed file, a major
version from the future and a key the specification does not define are all
exercised without one existing on disk.

The refusals are the interesting half. `read_lock` never raises: it is called by
a start-up check whose job is to report a problem with a remedy, and a parser
that threw would push that classification out to every caller.
"""

import pytest

from globin.adapters.dependency import (
    host_tags,
    installed_versions,
    interpreter_version,
    known_package_keys,
    known_top_level,
    marker_environment,
    python_full_version,
    read_lock,
    unknown_keys,
)
from globin.domain.dependency import LockState

WHEEL = (
    "[[packages.wheels]]\n"
    'name = "thing-1.0-py3-none-any.whl"\n'
    'url = "https://files.pythonhosted.org/thing-1.0-py3-none-any.whl"\n'
    'hashes = {sha256 = "0123456789abcdef"}\n'
)


def document(*, header: str = "", package: str = "") -> str:
    """A minimal valid PEP 751 document, with optional extra keys spliced in.

    A package entry must carry exactly one source, which is why every fixture
    here ends with a wheel. Omitting it produces a validation error rather than
    the condition under test -- a trap worth encoding once rather than
    rediscovering per test.
    """
    return (
        'lock-version = "1.0"\n'
        'created-by = "globin-tests"\n'
        f"{header}"
        "[[packages]]\n"
        'name = "thing"\n'
        'version = "1.0"\n'
        f"{package}"
        f"{WHEEL}"
    )


# ---------------------------------------------------------------------------
# read_lock
# ---------------------------------------------------------------------------


def test_a_well_formed_lock_is_read_into_entries() -> None:
    reading = read_lock(document())
    assert reading.state is LockState.PRESENT
    assert reading.lock_version == "1.0"
    assert [entry.name for entry in reading.entries] == ["thing"]
    assert reading.entries[0].version == "1.0"


def test_text_that_is_not_toml_is_unreadable_rather_than_an_exception() -> None:
    assert read_lock("this is not toml {{{").state is LockState.UNREADABLE


def test_a_document_missing_a_required_key_is_unreadable() -> None:
    assert read_lock('lock-version = "1.0"\npackages = []\n').state is (LockState.UNREADABLE)


def test_a_major_version_this_reader_does_not_implement_is_refused() -> None:
    """An unsupported major version is refused rather than read optimistically.

    The specification's words are "If a tool doesn't support a major version, it
    MUST raise an error".

    The reference implementation enforces `1 <= lock-version < 2` and raises;
    this reader turns that raise into a state, and keeps the version so the
    refusal can name it.
    """
    reading = read_lock('lock-version = "2.0"\ncreated-by = "x"\npackages = []\n')
    assert reading.state is LockState.UNSUPPORTED
    assert reading.lock_version == "2.0"


def test_an_unsupported_major_is_distinguished_from_a_merely_invalid_document() -> None:
    """The order of the two `except` clauses is load-bearing, not stylistic.

    `PylockUnsupportedVersionError` subclasses `PylockValidationError`, so a
    broader clause placed first would swallow the distinction entirely.
    """
    unsupported = read_lock('lock-version = "9.9"\ncreated-by = "x"\npackages = []\n')
    invalid = read_lock('lock-version = "1.0"\npackages = []\n')
    assert unsupported.state is LockState.UNSUPPORTED
    assert invalid.state is LockState.UNREADABLE


def test_an_unrecognised_top_level_key_warns_rather_than_refusing() -> None:
    """PEP 751: "a tool SHOULD warn when an unknown key is seen"."""
    reading = read_lock(document(header="future-thing = 1\n"))
    assert reading.state is LockState.NEWER_MINOR
    assert reading.unknown_keys == ("future-thing",)
    assert [entry.name for entry in reading.entries] == ["thing"]


def test_an_unrecognised_package_key_is_reported_under_its_level() -> None:
    reading = read_lock(document(package="future-field = 2\n"))
    assert reading.state is LockState.NEWER_MINOR
    assert reading.unknown_keys == ("packages.future-field",)


def test_a_marker_and_a_requires_python_survive_into_the_entry() -> None:
    reading = read_lock(
        document(package='marker = "sys_platform == \'linux\'"\nrequires-python = ">=3.12"\n')
    )
    entry = reading.entries[0]
    assert "linux" in entry.marker
    assert entry.requires_python == ">=3.12"


def test_the_documents_own_requires_python_is_read() -> None:
    reading = read_lock(document(header='requires-python = ">=3.12"\n'))
    assert reading.requires_python == ">=3.12"


def test_the_specification_itself_refuses_a_name_that_is_not_normalised() -> None:
    """Measured rather than assumed, and it makes our own canonicalising defensive.

    A valid PEP 751 document cannot carry `Foo_Bar`: the reference implementation
    reports "Name 'Foo_Bar' is not normalized". So `canonical_name` on the way in
    never has anything to do for a document that parsed -- it is there for the
    day a different producer is trusted, not for this one.
    """
    text = (
        'lock-version = "1.0"\ncreated-by = "x"\n'
        "[[packages]]\n"
        'name = "Foo_Bar"\n'
        'version = "1.0"\n' + WHEEL
    )
    assert read_lock(text).state is LockState.UNREADABLE


# A test asserting that a wheel filename disagreeing with its package name is
# refused was written here and then deleted, and the reason is worth keeping.
# `packaging` 26.3 performs that check and 26.0 does not, so the test passed on
# this machine and failed on a bare 3.12 interpreter carrying the older release.
# It was asserting the LIBRARY's validation strictness rather than any behaviour
# of GLOBIN's, and that strictness is free to move between releases. The
# normalised-name test above makes the same point -- the reference implementation
# checks more than a hand-rolled reader would -- using a rule that has been in
# the specification from the start.


# ---------------------------------------------------------------------------
# The key audit
# ---------------------------------------------------------------------------


def test_the_specification_key_sets_are_the_ones_pep_751_defines() -> None:
    assert "lock-version" in known_top_level()
    assert "created-by" in known_top_level()
    assert "packages" in known_top_level()
    assert "attestation-identities" in known_package_keys()
    assert "wheels" in known_package_keys()


def test_a_document_using_only_defined_keys_reports_nothing() -> None:
    assert unknown_keys({"lock-version": "1.0", "created-by": "x", "packages": []}) == ()


def test_the_tool_table_is_where_the_specification_puts_undefined_keys() -> None:
    """`tool` is reserved, so its contents must not be reported as unknown."""
    assert unknown_keys({"tool": {"anything": {"at": "all"}}}) == ()


def test_keys_are_sorted_and_deduplicated_across_packages() -> None:
    found = unknown_keys(
        {
            "zebra": 1,
            "alpha": 2,
            "packages": [{"name": "a", "wat": 1}, {"name": "b", "wat": 2}],
        }
    )
    assert found == ("alpha", "packages.wat", "zebra")


def test_a_packages_value_that_is_not_a_list_is_survived() -> None:
    assert unknown_keys({"packages": "not a list"}) == ()


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


def test_the_marker_environment_carries_string_values_only() -> None:
    """The domain is typed `Mapping[str, str]`, and `Environment` is not."""
    environment = marker_environment()
    assert environment
    assert all(isinstance(value, str) for value in environment.values())


def test_the_marker_environment_carries_the_interpreters_full_version() -> None:
    assert python_full_version(marker_environment())


def test_an_environment_without_the_version_key_yields_empty_rather_than_raising() -> None:
    assert python_full_version({}) == ""


def test_this_host_offers_tags_to_install_against() -> None:
    tags = host_tags()
    assert tags
    assert all(tag.interpreter for tag in tags)


def test_the_interpreter_version_is_three_dotted_numbers() -> None:
    parts = interpreter_version().split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


# ---------------------------------------------------------------------------
# What is installed
# ---------------------------------------------------------------------------


def test_installed_distributions_are_reported_with_their_versions() -> None:
    """The defect this phase fixes: the predecessor discarded the version."""
    installed = installed_versions()
    assert installed
    assert all(installed.values())


def test_a_distribution_this_test_needs_is_present_and_canonically_named() -> None:
    installed = installed_versions()
    assert "packaging" in installed
    assert all(name == name.lower() for name in installed)
    assert not any("_" in name for name in installed)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("packaging", id="packaging"),
        pytest.param("pytest", id="pytest"),
    ],
)
def test_the_libraries_the_suite_itself_runs_on_are_visible(name: str) -> None:
    assert name in installed_versions()
