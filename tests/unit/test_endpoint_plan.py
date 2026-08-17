"""The endpoint gate's judgements, every one exercised from literals in both directions.

**A detector that never fires is worse than no detector**, because it reports a
guarantee nobody has. So each function below is given a source that should trip it and a
source that should not, and the passing case matters as much as the failing one: a
regular expression that silently matched nothing would make every check here pass while
comparing empty sets.

Nothing in this file reads the repository. The source fragments are written inline, so a
change to `src/globin` cannot make these tests pass or fail for a reason that is not
about the judgement under test. Whether the *real* contract holds against the *real*
tree is `tests/integration/test_endpoint_end_to_end.py`.
"""

from typing import Final

import pytest

from tools.quality.endpoint.plan import (
    Declaration,
    EndpointContractError,
    binding_problems,
    bound_problems,
    contract_problems,
    exposition_problems,
    family_problems,
    loopback_problems,
    parse_declaration,
    route_problems,
    switch_problems,
    vocabulary_problems,
    wildcard_problems,
)
from tools.quality.endpoint.plan import (
    test_problems as judge_tests,
)

CONTRACT: Final[str] = """
[meta]
schema_version = 1
introduced_in_phase = 27

[loopback]
addresses = ["127.0.0.1", "::1"]
default = "127.0.0.1"
binding_module = "src/globin/adapters/diagnostics_http.py"
value_type_module = "src/globin/domain/diagnostics_http.py"
value_type = "LoopbackAddress"
forbidden_tokens = ["0.0.0.0"]

[[route]]
path = "/health/live"
route = "liveness"
switch = "health_enabled"
answers_by_default = true

[[route]]
path = "/diagnostics/snapshot"
route = "snapshot"
switch = "diagnostics_snapshot_enabled"
answers_by_default = false

[[exposition]]
format = "prometheus_text_0_0_4"
content_type = "text/plain; version=0.0.4; charset=utf-8"

[[bound]]
name = "port"
constant = "PORT"
default_field = "port"
minimum = 1024
maximum = 65535
default = 9464

[[family]]
name = "globin.diagnostics.http.requests.total"
kind = "counter"
attributes = ["route", "status_class"]
series = 6
budget = 6

[vocabulary]
route = ["liveness", "snapshot"]
status_class = ["2xx", "4xx", "5xx"]

[tests]
unit = "tests/unit/test_diagnostics_http.py"
"""
"""A small but complete contract, so every parse below has something to read."""

DOMAIN: Final[str] = '''
LOOPBACK_IPV4: Final[str] = "127.0.0.1"
LOOPBACK_IPV6: Final[str] = "::1"
MINIMUM_PORT: Final[int] = 1_024
MAXIMUM_PORT: Final[int] = 65_535
CONTENT_TYPE_PROMETHEUS: Final[str] = "text/plain; version=0.0.4; charset=utf-8"


class DiagnosticsRoute(StrEnum):
    """Which endpoint."""

    LIVENESS = "liveness"
    SNAPSHOT = "snapshot"


class StatusClass(StrEnum):
    """A status class."""

    SUCCESS = "2xx"
    CLIENT_ERROR = "4xx"
    SERVER_ERROR = "5xx"


class RejectionReason(StrEnum):
    """Why refused."""

    ADMISSION = "admission"


@dataclass(frozen=True, slots=True)
class LoopbackAddress:
    """An address only this machine can reach."""

    text: str


def route_paths() -> tuple[tuple[str, DiagnosticsRoute], ...]:
    """The table."""
    return (
        ("/health/live", DiagnosticsRoute.LIVENESS),
        ("/diagnostics/snapshot", DiagnosticsRoute.SNAPSHOT),
    )
'''
"""A domain module carrying everything the contract above describes."""

CONFIG: Final[str] = """
DEFAULT_ENDPOINT_PORT: Final[int] = 9_464


@dataclass(frozen=True, slots=True)
class DiagnosticsHttpConfig:
    \"\"\"The section.\"\"\"

    enabled: bool = False
    port: int = DEFAULT_ENDPOINT_PORT
    diagnostics_snapshot_enabled: bool = False
    health_enabled: bool = True
"""
"""A configuration module carrying the defaults the contract above declares."""

METRICS: Final[str] = """
def metrics():
    return (
        MetricDescriptor(name="globin.diagnostics.http.requests.total"),
    )
"""
"""A metrics module naming the one family the contract above declares."""


def _declaration(text: str = CONTRACT) -> Declaration:
    """Parse a contract."""
    return parse_declaration(text)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_a_well_formed_contract_parses() -> None:
    """The positive case, without which nothing below means anything."""
    declaration = _declaration()
    assert declaration.phase == 27
    assert declaration.addresses == ("127.0.0.1", "::1")
    assert [route.path for route in declaration.routes] == [
        "/health/live",
        "/diagnostics/snapshot",
    ]
    assert declaration.vocabulary["status_class"] == ("2xx", "4xx", "5xx")
    assert declaration.tests["unit"] == "tests/unit/test_diagnostics_http.py"


def test_a_contract_that_is_not_toml_is_refused() -> None:
    """A malformed file is the gate not getting as far as checking."""
    with pytest.raises(EndpointContractError, match="not valid TOML"):
        parse_declaration("this is not = = toml")


def test_an_unknown_schema_version_is_refused_rather_than_read() -> None:
    """A reader that guessed at a shape it does not implement would report confidently.

    `SERIALIZATION_POLICY.md`'s rule, and the one every manifest here follows.
    """
    with pytest.raises(EndpointContractError, match="schema version"):
        parse_declaration(CONTRACT.replace("schema_version = 1", "schema_version = 99"))


@pytest.mark.parametrize(
    ("removed", "expected"),
    [
        pytest.param("[meta]", "no \\[meta\\] table", id="meta"),
        pytest.param("[loopback]", "no \\[loopback\\] table", id="loopback"),
        pytest.param("[vocabulary]", "no \\[vocabulary\\] table", id="vocabulary"),
    ],
)
def test_a_missing_table_is_refused(removed: str, expected: str) -> None:
    """Each table this reader requires, absent in turn."""
    with pytest.raises(EndpointContractError, match=expected):
        parse_declaration(CONTRACT.replace(removed, "[unused]"))


def test_a_missing_array_of_tables_is_refused() -> None:
    """An empty register would make every comparison vacuous."""
    with pytest.raises(EndpointContractError, match="no \\[\\[route\\]\\] entries"):
        parse_declaration(CONTRACT.replace("[[route]]", "[[unused]]"))


def test_a_value_of_the_wrong_type_is_refused() -> None:
    """A port declared as a string is a contract nobody can compare numbers against."""
    with pytest.raises(EndpointContractError, match="is not an integer"):
        parse_declaration(CONTRACT.replace("minimum = 1024", 'minimum = "1024"'))


# ---------------------------------------------------------------------------
# The contract against itself
# ---------------------------------------------------------------------------


def test_a_self_consistent_contract_has_no_problems() -> None:
    """The positive case."""
    assert contract_problems(_declaration()) == ()


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        pytest.param(
            ('default = "127.0.0.1"', 'default = "10.0.0.1"'),
            "is not one of the permitted addresses",
            id="a-default-outside-the-permitted-set",
        ),
        pytest.param(
            ("introduced_in_phase = 27", "introduced_in_phase = 999"),
            "outside 1..320",
            id="a-phase-beyond-the-programme",
        ),
        pytest.param(
            ("default = 9464", "default = 80"),
            "outside its own declared",
            id="a-default-below-its-own-minimum",
        ),
        pytest.param(
            ("minimum = 1024\nmaximum = 65535", "minimum = 65535\nmaximum = 1024"),
            "minimum above its maximum",
            id="an-inverted-range",
        ),
        pytest.param(
            ("series = 6\nbudget = 6", "series = 6\nbudget = 12"),
            "must be equal",
            id="a-budget-above-its-own-series",
        ),
        pytest.param(
            ("series = 6\nbudget = 6", "series = 7\nbudget = 7"),
            "multiply to 6",
            id="a-series-count-the-vocabularies-do-not-support",
        ),
        pytest.param(
            ('attributes = ["route", "status_class"]', 'attributes = ["route", "invented"]'),
            "which has no vocabulary",
            id="an-attribute-with-no-vocabulary",
        ),
    ],
)
def test_a_contract_that_contradicts_itself_is_caught(edit: tuple[str, str], expected: str) -> None:
    """Each of these is reachable by editing one number and forgetting another.

    Caught before any source is read, so a reader is sent to the contract rather than
    to the wrong file.
    """
    problems = contract_problems(_declaration(CONTRACT.replace(*edit)))
    assert any(expected in problem for problem in problems), problems


def test_two_routes_sharing_a_path_are_caught() -> None:
    """Two answers for one target is a contract that cannot be implemented."""
    doubled = CONTRACT.replace('path = "/diagnostics/snapshot"', 'path = "/health/live"')
    assert any("same path" in problem for problem in contract_problems(_declaration(doubled)))


def test_two_routes_sharing_a_label_are_caught() -> None:
    """Two routes under one label would merge two series into one."""
    doubled = CONTRACT.replace('route = "snapshot"', 'route = "liveness"')
    assert any("same label" in problem for problem in contract_problems(_declaration(doubled)))


# ---------------------------------------------------------------------------
# The contract against the source
# ---------------------------------------------------------------------------


def test_a_matching_route_table_has_no_problems() -> None:
    """The positive case."""
    assert route_problems(_declaration(), DOMAIN) == ()


def test_a_route_the_source_does_not_serve_is_caught() -> None:
    """A promise nobody implemented."""
    problems = route_problems(_declaration(), DOMAIN.replace("/health/live", "/health/alive"))
    assert any("serves no route at '/health/live'" in problem for problem in problems)


def test_a_route_the_contract_does_not_describe_is_caught() -> None:
    """The worse direction: a reachable endpoint nobody wrote down."""
    declared = '("/health/live", DiagnosticsRoute.LIVENESS),'
    smuggled = '("/secret", DiagnosticsRoute.LIVENESS),'
    extra = DOMAIN.replace(declared, f"{declared}\n        {smuggled}")
    problems = route_problems(_declaration(), extra)
    assert any("which this contract does not describe" in problem for problem in problems)


def test_a_route_labelled_differently_in_the_source_is_caught() -> None:
    """A label is a metric dimension, so a drifted one is a wrong number on a dashboard."""
    relabelled = DOMAIN.replace(
        '("/health/live", DiagnosticsRoute.LIVENESS)', '("/health/live", DiagnosticsRoute.SNAPSHOT)'
    )
    problems = route_problems(_declaration(), relabelled)
    assert any("in the source" in problem for problem in problems)


def test_a_source_with_no_recoverable_route_table_is_caught() -> None:
    """The parser matching nothing must be a failure, not a silent pass."""
    assert route_problems(_declaration(), "nothing here") == (
        "no route table could be recovered from the source",
    )


def test_the_declared_addresses_are_found_in_the_source() -> None:
    """The positive case."""
    assert loopback_problems(_declaration(), DOMAIN) == ()


def test_an_address_the_source_does_not_declare_is_caught() -> None:
    """A permitted address nothing implements."""
    problems = loopback_problems(_declaration(), DOMAIN.replace('"::1"', '"::2"'))
    assert any("no constant for the address" in problem for problem in problems)


def test_a_source_that_does_not_name_the_value_type_is_caught() -> None:
    """The type is the mechanism, so its absence is the guarantee's absence."""
    problems = loopback_problems(_declaration(), DOMAIN.replace("LoopbackAddress", "PlainString"))
    assert any("does not name the value type" in problem for problem in problems)


def test_a_binding_module_that_spells_no_address_has_no_problems() -> None:
    """The positive case, and the property the real module has."""
    assert binding_problems(_declaration(), "policy.address.text\nsocket.AF_INET\n") == ()


@pytest.mark.parametrize(
    "literal",
    [
        pytest.param('"127.0.0.1"', id="loopback-is-refused-too"),
        pytest.param('"0.0.0.0"', id="a-wildcard"),
        pytest.param('"192.168.1.10"', id="a-lan-address"),
        pytest.param('"::1"', id="ipv6-loopback"),
    ],
)
def test_any_address_literal_in_the_binding_module_is_caught(literal: str) -> None:
    """Loopback included, and that is the point.

    An address the module cannot spell is one it cannot bind, so the only one reachable
    is the one the value type handed it — and a future edit hardcoding *any* address
    fails, whether or not somebody would have recognised it as dangerous.
    """
    problems = binding_problems(_declaration(), f"server.bind(({literal}, port))\n")
    assert any("rather than being handed one" in problem for problem in problems)


def test_a_package_with_no_wildcard_has_no_problems() -> None:
    """The positive case."""
    assert wildcard_problems(_declaration(), {"a.py": "loopback only\n"}) == ()


def test_a_wildcard_anywhere_in_the_package_is_caught() -> None:
    """The absence that sits beside the value type, because the type cannot see this."""
    sources = {"a.py": "fine\n", "b.py": 'addr = "0.0.0.0"\n'}
    problems = wildcard_problems(_declaration(), sources)
    assert problems == ("b.py spells '0.0.0.0'",)


def test_matching_bounds_have_no_problems() -> None:
    """The positive case."""
    assert bound_problems(_declaration(), DOMAIN, CONFIG) == ()


@pytest.mark.parametrize(
    ("module", "edit", "expected"),
    [
        pytest.param(
            "domain",
            ("MINIMUM_PORT: Final[int] = 1_024", "MINIMUM_PORT: Final[int] = 1"),
            "MINIMUM_PORT is 1 in the source",
            id="a-drifted-minimum",
        ),
        pytest.param(
            "domain",
            ("MAXIMUM_PORT: Final[int] = 65_535", "MAXIMUM_PORT: Final[int] = 70_000"),
            "MAXIMUM_PORT is 70000 in the source",
            id="a-drifted-maximum",
        ),
        pytest.param(
            "domain",
            ("MINIMUM_PORT: Final[int] = 1_024", "UNRELATED: Final[int] = 1_024"),
            "declares no MINIMUM_PORT",
            id="a-missing-constant",
        ),
        pytest.param(
            "config",
            (
                "DEFAULT_ENDPOINT_PORT: Final[int] = 9_464",
                "DEFAULT_ENDPOINT_PORT: Final[int] = 8_080",
            ),
            "defaults to 8080 in the source",
            id="a-drifted-default",
        ),
        pytest.param(
            "config",
            ("    port: int = DEFAULT_ENDPOINT_PORT\n", ""),
            "declares no default for port",
            id="a-missing-default",
        ),
    ],
)
def test_a_bound_that_drifted_from_the_source_is_caught(
    module: str, edit: tuple[str, str], expected: str
) -> None:
    """Four numbers per bound, recovered from two files, each broken in turn."""
    domain = DOMAIN.replace(*edit) if module == "domain" else DOMAIN
    config = CONFIG.replace(*edit) if module == "config" else CONFIG
    problems = bound_problems(_declaration(), domain, config)
    assert any(expected in problem for problem in problems), problems


def test_a_default_declared_as_a_literal_is_recovered_too() -> None:
    """Both spellings, because either is legitimate in the source."""
    literal = CONFIG.replace("port: int = DEFAULT_ENDPOINT_PORT", "port: int = 9_464")
    assert bound_problems(_declaration(), DOMAIN, literal) == ()


def test_matching_switches_have_no_problems() -> None:
    """The positive case."""
    assert switch_problems(_declaration(), CONFIG) == ()


def test_the_snapshot_switch_defaulting_on_is_caught() -> None:
    """The claim worth a test of its own: turning the surface on must not turn it on too."""
    flipped = CONFIG.replace(
        "diagnostics_snapshot_enabled: bool = False", "diagnostics_snapshot_enabled: bool = True"
    )
    problems = switch_problems(_declaration(), flipped)
    assert any("diagnostics_snapshot_enabled defaults to True" in p for p in problems)


def test_a_missing_switch_is_caught() -> None:
    """A route whose switch does not exist cannot be turned off."""
    without = CONFIG.replace("    health_enabled: bool = True\n", "")
    problems = switch_problems(_declaration(), without)
    assert any("declares no switch 'health_enabled'" in problem for problem in problems)


def test_matching_content_types_have_no_problems() -> None:
    """The positive case."""
    assert exposition_problems(_declaration(), DOMAIN) == ()


def test_a_content_type_the_source_does_not_serve_is_caught() -> None:
    """A drifted parameter is a scrape a conforming client refuses."""
    drifted = DOMAIN.replace("version=0.0.4", "version=0.0.5")
    problems = exposition_problems(_declaration(), drifted)
    assert any("no content type" in problem for problem in problems)


def test_matching_vocabularies_have_no_problems() -> None:
    """The positive case."""
    assert vocabulary_problems(_declaration(), DOMAIN) == ()


def test_a_value_in_the_source_the_contract_omits_is_caught() -> None:
    """The worse direction: a label a dashboard can see and nobody declared."""
    extra = DOMAIN.replace(
        '    SNAPSHOT = "snapshot"', '    SNAPSHOT = "snapshot"\n    EXTRA = "extra"'
    )
    problems = vocabulary_problems(_declaration(), extra)
    assert any("'extra'" in problem for problem in problems)


def test_a_vocabulary_the_source_does_not_carry_is_caught() -> None:
    """A key whose enum was renamed, so no vocabulary can be found for it at all."""
    renamed = DOMAIN.replace("class StatusClass(StrEnum):", "class Renamed(StrEnum):")
    problems = vocabulary_problems(_declaration(), renamed)
    assert any("no vocabulary for 'status_class'" in problem for problem in problems)


def test_one_enums_members_are_not_read_as_anothers() -> None:
    """The reason the recovery stops at the next definition.

    Without that, `DiagnosticsRoute` would absorb `StatusClass`'s members and every
    cardinality product would be wrong in the permissive direction.
    """
    declaration = _declaration()
    assert declaration.vocabulary["route"] == ("liveness", "snapshot")
    assert vocabulary_problems(declaration, DOMAIN) == ()


# ---------------------------------------------------------------------------
# The arithmetic that earns the gate
# ---------------------------------------------------------------------------


def test_a_budget_that_is_the_product_has_no_problems() -> None:
    """The positive case: two routes times three status classes is six."""
    assert family_problems(_declaration(), DOMAIN, METRICS) == ()


def test_a_budget_that_is_not_the_product_is_caught() -> None:
    """The check that is arithmetic rather than comparison."""
    wrong = CONTRACT.replace("series = 6\nbudget = 6", "series = 12\nbudget = 12")
    problems = family_problems(_declaration(wrong), DOMAIN, METRICS)
    assert any("multiply to 6" in problem for problem in problems)


def test_growing_a_vocabulary_in_the_source_breaks_the_budget() -> None:
    """The property this gate exists for.

    A seventh route added to the enum grows the `route` vocabulary, so every budget
    naming it must move in the same edit — and until it does, this fails.
    """
    grown = DOMAIN.replace(
        '    SNAPSHOT = "snapshot"', '    SNAPSHOT = "snapshot"\n    EXTRA = "extra"'
    )
    problems = family_problems(_declaration(), grown, METRICS)
    assert any("multiply to 9" in problem for problem in problems)


def test_a_family_the_registry_does_not_declare_is_caught() -> None:
    """A metric named here and recorded nowhere."""
    problems = family_problems(_declaration(), DOMAIN, "def metrics():\n    return ()\n")
    assert any("declares no family named" in problem for problem in problems)


def test_a_family_whose_vocabulary_cannot_be_recovered_is_caught() -> None:
    """Reported as unrecoverable rather than silently multiplied to one."""
    renamed = DOMAIN.replace("class StatusClass(StrEnum):", "class Renamed(StrEnum):")
    problems = family_problems(_declaration(), renamed, METRICS)
    assert any("could not be recovered" in problem for problem in problems)


# ---------------------------------------------------------------------------
# The tests the contract names
# ---------------------------------------------------------------------------


def test_a_named_test_that_exists_has_no_problems() -> None:
    """The positive case."""
    assert judge_tests(_declaration(), {"unit": True}) == ()


def test_a_named_test_that_is_absent_is_caught() -> None:
    """A claim asserted in the contract and enforced nowhere."""
    problems = judge_tests(_declaration(), {"unit": False})
    assert problems == ("the unit test 'tests/unit/test_diagnostics_http.py' does not exist",)


def test_a_named_test_nobody_reported_on_counts_as_absent() -> None:
    """Silence is not evidence, which is the rule every gate here follows."""
    assert judge_tests(_declaration(), {}) != ()


# ---------------------------------------------------------------------------
# The remaining refusals in the reader, none reachable through a valid contract
# ---------------------------------------------------------------------------


def test_an_array_entry_that_is_not_a_table_is_refused() -> None:
    """TOML permits an array of scalars where an array of tables was meant.

    Built by dropping the `[[route]]` blocks and declaring a root-level `route` list
    instead, because the two spellings cannot coexist in one document — and what has to
    be reached is a key that *is* a non-empty list whose entries are not tables.
    """
    kept = [
        line
        for line in CONTRACT.splitlines()
        if not line.startswith("[[route]]")
        and not line.startswith("path =")
        and not line.startswith("route = ")
        and not line.startswith("switch =")
        and not line.startswith("answers_by_default =")
    ]
    broken = "route = [1, 2]\n" + "\n".join(kept)
    with pytest.raises(EndpointContractError, match="entry that is not a table"):
        parse_declaration(broken)


def test_a_missing_string_is_refused() -> None:
    """An empty value is refused as well as an absent one: neither names anything."""
    with pytest.raises(EndpointContractError, match="is not a non-empty string"):
        parse_declaration(CONTRACT.replace('default = "127.0.0.1"', 'default = ""'))


def test_a_list_declared_as_something_else_is_refused() -> None:
    """A single address where a list was meant would silently permit exactly one."""
    with pytest.raises(EndpointContractError, match="is not a list"):
        parse_declaration(
            CONTRACT.replace('addresses = ["127.0.0.1", "::1"]', 'addresses = "127.0.0.1"')
        )


def test_a_list_holding_something_that_is_not_a_string_is_refused() -> None:
    """A number among the addresses is a value nothing downstream could compare."""
    with pytest.raises(EndpointContractError, match="not a string"):
        parse_declaration(
            CONTRACT.replace('addresses = ["127.0.0.1", "::1"]', "addresses = [127, 1]")
        )


def test_a_boolean_where_an_integer_was_meant_is_refused() -> None:
    """``true`` is an ``int`` to Python, and a port of one is nobody's intent."""
    with pytest.raises(EndpointContractError, match="is not an integer"):
        parse_declaration(CONTRACT.replace("minimum = 1024", "minimum = true"))


def test_a_source_with_no_configuration_section_yields_no_defaults() -> None:
    """Reported as every default missing, rather than as every default matching."""
    problems = bound_problems(_declaration(), DOMAIN, "nothing here\n")
    assert any("declares no default for port" in problem for problem in problems)


def test_a_default_spelled_as_a_named_string_constant_is_recovered() -> None:
    """The real ``bind_host`` defaults to a constant rather than a literal.

    Both spellings are recovered, so a section mixing them cannot make one field look
    absent while its neighbour is read.
    """
    config = 'LOOPBACK_IPV4: Final[str] = "127.0.0.1"\n' + CONFIG.replace(
        "    enabled: bool = False\n",
        "    enabled: bool = False\n    bind_host: str = LOOPBACK_IPV4\n",
    )
    assert bound_problems(_declaration(), DOMAIN, config) == ()
