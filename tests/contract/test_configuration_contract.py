"""The configuration policy document and the configuration code say the same thing.

``docs/CONFIGURATION_POLICY.md`` is where an operator reads which settings exist,
what each is called and what happens when they leave one out. The code is where
the answer actually comes from. Two statements of one register diverge unless
something compares them, and a documented setting the code does not implement is
the worse direction of that failure: it reads as a promise, and an operator who
acts on it gets a refusal naming a key they copied out of this repository.

The comparison is bidirectional, and it goes further than names. The documented
*default* is fed back through the binding, so the table cannot claim a default
the model does not use — a check on names alone would let the column drift
unnoticed, which is the column an operator is most likely to rely on without
testing.

What this file does not do is restate the rules. Whether the fold and the
binding behave is ``tests/unit`` and ``tests/property``; whether the document
exists and is well-formed is
``tests/contract/test_documentation_contract.py``.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from globin.domain.configuration import (
    DIAGNOSTICS_HTTP_SECTION,
    DIAGNOSTICS_SECTION,
    LOGGING_SECTION,
    TELEMETRY_SECTION,
    WATCHDOG_SECTION,
    DiagnosticsConfig,
    DiagnosticsHttpConfig,
    LoggingConfig,
    TelemetryConfig,
    WatchdogConfig,
    as_config,
    config_layer,
    default_config,
    default_layer,
    known_keys,
    resolve,
    section_defaults,
)

POLICY_RELATIVE_PATH: Final[str] = "docs/CONFIGURATION_POLICY.md"

#: A row of the settings table: four cells, the first three inline-code spans.
#: Keys are lowercase and dotted, which is what keeps this from also matching the
#: refusal table further down, whose first cell is prose.
#:
#: The default cell admits dots and colons as well as word characters. Until Phase
#: 027 every default was a number, a boolean or a severity name, so ``\w+`` was
#: enough — and it therefore *silently skipped* the first row whose default was an
#: IP address rather than failing on it. A parser that quietly matches less than it
#: should makes every comparison below weaker without making any of them red, which
#: is why ``test_the_row_reader_finds_its_own_failing_case`` now includes a dotted
#: default among its examples.
SETTING_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<key>[a-z][a-z0-9_.]*)` \| `(?P<type>\w+)` \| `(?P<default>[\w.:]+)` \|",
    re.MULTILINE,
)


class Row(tuple[str, str, str]):
    """One parsed settings row: key, declared type, declared default."""


def settings_rows(document: str) -> tuple[Row, ...]:
    """Return every settings row the document declares.

    Args:
        document: The Markdown source.

    Returns:
        One ``(key, type, default)`` triple per row, in document order.
    """
    return tuple(
        Row((match.group("key"), match.group("type"), match.group("default")))
        for match in SETTING_ROW_RE.finditer(document)
    )


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> str:
    """The configuration policy document as written."""
    return (repo_root / POLICY_RELATIVE_PATH).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows(policy: str) -> tuple[Row, ...]:
    """Every settings row the document declares."""
    return settings_rows(policy)


def test_the_row_reader_finds_its_own_failing_case() -> None:
    """Guard the guard.

    Every assertion below is only as good as this parser. One that silently
    matched nothing would make each of them pass while comparing empty sets
    against each other.
    """
    document = "\n".join(
        [
            "| Key | Type | Default | Meaning |",
            "|---|---|---|---|",
            "| `alpha.one` | `Severity` | `DEBUG` | Something. |",
            "| `alpha.two` | `str` | `127.0.0.1` | A default that is not one word. |",
            "| `alpha.three` | `str` | `::1` | Nor is this one. |",
            "| Prose in the first cell | `X` | `Y` | Not a setting. |",
            "",
        ]
    )
    assert settings_rows(document) == (
        Row(("alpha.one", "Severity", "DEBUG")),
        Row(("alpha.two", "str", "127.0.0.1")),
        Row(("alpha.three", "str", "::1")),
    )
    assert settings_rows("no table here") == ()


def test_the_document_declares_at_least_one_setting(rows: tuple[Row, ...]) -> None:
    """An empty register would make every comparison below vacuous."""
    assert rows


def test_the_documented_settings_are_exactly_the_settings_that_exist(
    rows: tuple[Row, ...],
) -> None:
    documented = tuple(key for key, _type, _default in rows)
    assert documented == known_keys()


def test_every_documented_type_is_the_type_the_default_actually_has(
    rows: tuple[Row, ...],
) -> None:
    defaults = {
        **section_defaults(LOGGING_SECTION, LoggingConfig),
        **section_defaults(DIAGNOSTICS_SECTION, DiagnosticsConfig),
        **section_defaults(WATCHDOG_SECTION, WatchdogConfig),
        **section_defaults(TELEMETRY_SECTION, TelemetryConfig),
        **section_defaults(DIAGNOSTICS_HTTP_SECTION, DiagnosticsHttpConfig),
    }
    for key, declared, _default in rows:
        assert type(defaults[key]).__name__ == declared, key


def test_writing_a_documented_default_changes_nothing(rows: tuple[Row, ...]) -> None:
    """The strong form of the check.

    Comparing the default column against the model as a string would prove the
    two spellings match. Feeding it back through the binding proves the spelling
    is one the parser accepts *and* that it resolves to what the model would have
    used anyway — so a stale default column cannot survive here.
    """
    for key, _declared, default in rows:
        stated = as_config(
            resolve((default_layer(), config_layer(POLICY_RELATIVE_PATH, {key: default})))
        )
        assert stated == default_config(), key


def test_the_document_names_the_phases_it_defers_to(policy: str) -> None:
    """The register is small, and a reader's first question is what is missing.

    Naming the owning phase is what stops the answer being inferred from the
    absence of a row.
    """
    for phase in ("015", "026", "027", "028", "029", "035"):
        assert phase in policy
