"""Parsing the endpoint contract, and every judgement it makes about the source.

**Nothing here performs I/O.** Each function takes the contract, or a module's
source *text*, and returns problems — so every judgement below is exercised from
literals rather than from this repository's own tree. `gate.py` supplies the text
and the sequencing, which is the division `tools/quality/gpu/plan.py` draws.

**Every check recomputes rather than compares strings.** A gate that asserted the
contract said what the contract says would pass forever. What these functions do
instead is recover the value from the *source* — a route table, a constant, a
dataclass default, an attribute vocabulary — and hold it against the declaration.
The interesting one is :func:`family_problems`, which multiplies the vocabulary
sizes it found in the source and refuses a declared budget that is not the product.

**Text inspection, not import, and the limitation is stated rather than implied.**
`tools/` cannot import `globin`, so these read source with regular expressions.
That is a proxy: a constant assembled at run time, or a route table built by a
loop, would defeat it. It catches what actually erodes a contract — somebody
editing one of two places — and every detector below has failing cases in both
directions in `tests/unit/test_endpoint_plan.py`.
"""

import re
import tomllib
from dataclasses import dataclass
from typing import Final

CONFIGURATION_FILE: Final[str] = "docs/engineering/endpoint-contract.toml"
"""Where the declared contract lives, relative to the repository root."""

DOMAIN_MODULE: Final[str] = "src/globin/domain/diagnostics_http.py"
"""The module holding the route table, the bounds and the vocabularies."""

CONFIG_MODULE: Final[str] = "src/globin/domain/configuration.py"
"""The module holding the section's defaults."""

METRICS_MODULE: Final[str] = "src/globin/domain/metrics.py"
"""The module holding the metric descriptors."""

SCHEMA_VERSION: Final[int] = 1
"""The contract shape this reader implements."""

ROADMAP_TOTAL_PHASES: Final[int] = 320
"""How many phases the programme has."""

#: One entry of the route table, as the source spells it.
ROUTE_ENTRY: Final[re.Pattern[str]] = re.compile(
    r'\(\s*"(?P<path>/[^"]*)"\s*,\s*DiagnosticsRoute\.(?P<member>[A-Z_]+)\s*\)'
)

#: A `Final` integer constant, however the source spaces its digits.
INTEGER_CONSTANT: Final[re.Pattern[str]] = re.compile(
    r"^(?P<name>[A-Z][A-Z0-9_]*)\s*:\s*Final\[int\]\s*=\s*(?P<value>[0-9_]+)\s*$", re.MULTILINE
)

#: A `Final` string constant.
STRING_CONSTANT: Final[re.Pattern[str]] = re.compile(
    r'^(?P<name>[A-Z][A-Z0-9_]*)\s*:\s*Final\[str\]\s*=\s*"(?P<value>[^"]*)"\s*$', re.MULTILINE
)

#: An enum member's value, for recovering a vocabulary.
ENUM_MEMBER: Final[re.Pattern[str]] = re.compile(
    r'^\s{4}(?P<member>[A-Z][A-Z0-9_]*)\s*=\s*"(?P<value>[^"]*)"\s*$', re.MULTILINE
)

#: A field of a frozen dataclass carrying an integer or boolean default. The
#: default may be a literal or a named constant, and both spellings are recovered.
DATACLASS_FIELD: Final[re.Pattern[str]] = re.compile(
    r"^\s{4}(?P<field>[a-z][a-z0-9_]*)\s*:\s*(?P<annotation>bool|int|str)\s*=\s*"
    r"(?P<value>[A-Za-z0-9_.]+)\s*$",
    re.MULTILINE,
)

#: An IP address literal, in either family. Deliberately loose: what matters is
#: catching anything that *looks* like an address in the binding module, and a
#: false positive there is a conversation rather than a silent hole.
ADDRESS_LITERAL: Final[re.Pattern[str]] = re.compile(
    r'"(?P<address>(?:\d{1,3}\.){3}\d{1,3}|(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F]{0,4})"'
)


class EndpointContractError(Exception):
    """The contract could not be read, or does not describe a contract.

    Distinct from a *finding*: a finding is something the gate concluded about a
    tree it could read, and this is the gate not getting that far.
    """


@dataclass(frozen=True, slots=True)
class Route:
    """One declared route.

    Args:
        path: The exact request target.
        route: The label value recorded in metrics.
        switch: Which configuration field decides whether it answers.
        answers_by_default: Whether it answers under the declared defaults, given
            that the surface itself is enabled.
    """

    path: str
    route: str
    switch: str
    answers_by_default: bool


@dataclass(frozen=True, slots=True)
class Exposition:
    """One declared exposition format.

    Args:
        format: The format's identifier.
        content_type: The exact content type it is served under.
    """

    format: str
    content_type: str


@dataclass(frozen=True, slots=True)
class Bound:
    """One declared numeric bound.

    Args:
        name: What it bounds.
        constant: The stem of the ``MINIMUM_``/``MAXIMUM_`` pair in the source.
        default_field: The configuration field carrying the default.
        minimum: The lowest permitted value.
        maximum: The highest.
        default: What it defaults to.
    """

    name: str
    constant: str
    default_field: str
    minimum: int
    maximum: int
    default: int


@dataclass(frozen=True, slots=True)
class Family:
    """One declared metric family.

    Args:
        name: The metric's canonical name.
        kind: Counter, gauge or histogram.
        attributes: The attribute keys it carries.
        series: The product of its attribute vocabularies' sizes.
        budget: The cardinality ceiling declared for it.
    """

    name: str
    kind: str
    attributes: tuple[str, ...]
    series: int
    budget: int


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole contract, parsed.

    Args:
        schema_version: The shape this was written against.
        phase: The phase that introduced the surface.
        addresses: Every address the surface may bind.
        default_address: Which it binds when nobody says.
        binding_module: The one module that may open a socket.
        value_type_module: Where the address value type lives.
        value_type: That type's name.
        forbidden_tokens: Spellings of "every interface" that must appear nowhere.
        routes: Every route.
        expositions: Every exposition format.
        bounds: Every numeric bound.
        families: Every metric family.
        vocabulary: Each attribute key's bounded value set.
        tests: The test modules that hold these claims, by kind.
    """

    schema_version: int
    phase: int
    addresses: tuple[str, ...]
    default_address: str
    binding_module: str
    value_type_module: str
    value_type: str
    forbidden_tokens: tuple[str, ...]
    routes: tuple[Route, ...]
    expositions: tuple[Exposition, ...]
    bounds: tuple[Bound, ...]
    families: tuple[Family, ...]
    vocabulary: dict[str, tuple[str, ...]]
    tests: dict[str, str]


def parse_declaration(text: str) -> Declaration:
    """Read the contract.

    Args:
        text: The TOML source.

    Returns:
        The declaration.

    Raises:
        EndpointContractError: If it is not valid TOML, declares an unknown schema
            version, or omits a table this reader requires.

    An unknown version is **refused, never read**, which is the rule
    `SERIALIZATION_POLICY.md` states and every manifest here follows: a reader that
    guessed at a shape it does not implement would report confidently about fields
    it had misunderstood.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as fault:
        msg = f"{CONFIGURATION_FILE} is not valid TOML: {fault}"
        raise EndpointContractError(msg) from fault
    meta = _table(document, "meta")
    version = meta.get("schema_version")
    if version != SCHEMA_VERSION:
        msg = (
            f"{CONFIGURATION_FILE} declares schema version {version!r}, "
            f"and this reader implements {SCHEMA_VERSION}"
        )
        raise EndpointContractError(msg)
    loopback = _table(document, "loopback")
    return Declaration(
        schema_version=SCHEMA_VERSION,
        phase=_integer(meta, "introduced_in_phase"),
        addresses=tuple(_strings(loopback, "addresses")),
        default_address=_string(loopback, "default"),
        binding_module=_string(loopback, "binding_module"),
        value_type_module=_string(loopback, "value_type_module"),
        value_type=_string(loopback, "value_type"),
        forbidden_tokens=tuple(_strings(loopback, "forbidden_tokens")),
        routes=tuple(
            Route(
                path=_string(entry, "path"),
                route=_string(entry, "route"),
                switch=_string(entry, "switch"),
                answers_by_default=bool(entry.get("answers_by_default")),
            )
            for entry in _array(document, "route")
        ),
        expositions=tuple(
            Exposition(format=_string(entry, "format"), content_type=_string(entry, "content_type"))
            for entry in _array(document, "exposition")
        ),
        bounds=tuple(
            Bound(
                name=_string(entry, "name"),
                constant=_string(entry, "constant"),
                default_field=_string(entry, "default_field"),
                minimum=_integer(entry, "minimum"),
                maximum=_integer(entry, "maximum"),
                default=_integer(entry, "default"),
            )
            for entry in _array(document, "bound")
        ),
        families=tuple(
            Family(
                name=_string(entry, "name"),
                kind=_string(entry, "kind"),
                attributes=tuple(_strings(entry, "attributes")),
                series=_integer(entry, "series"),
                budget=_integer(entry, "budget"),
            )
            for entry in _array(document, "family")
        ),
        vocabulary={
            key: tuple(str(value) for value in values)
            for key, values in _table(document, "vocabulary").items()
            if isinstance(values, list)
        },
        tests={
            key: str(value)
            for key, value in _table(document, "tests").items()
            if isinstance(value, str)
        },
    )


def contract_problems(declaration: Declaration) -> tuple[str, ...]:
    """Judge the contract against itself, before any source is read.

    Args:
        declaration: The parsed contract.

    Returns:
        One sentence per way the contract contradicts itself.

    **A contract that disagrees with itself is worth catching before the source
    is.** Every finding below is reachable by editing one number and forgetting
    another, and each would otherwise be reported as a *source* problem — sending
    a reader to the wrong file.
    """
    problems: list[str] = []
    if declaration.default_address not in declaration.addresses:
        problems.append(
            f"the default address {declaration.default_address!r} is not one of the "
            f"permitted addresses {list(declaration.addresses)}"
        )
    if not 0 < declaration.phase <= ROADMAP_TOTAL_PHASES:
        problems.append(
            f"the introducing phase {declaration.phase} is outside 1..{ROADMAP_TOTAL_PHASES}"
        )
    paths = [route.path for route in declaration.routes]
    if len(set(paths)) != len(paths):
        problems.append("two routes declare the same path")
    labels = [route.route for route in declaration.routes]
    if len(set(labels)) != len(labels):
        problems.append("two routes declare the same label")
    for bound in declaration.bounds:
        if bound.minimum > bound.maximum:
            problems.append(f"{bound.name} declares a minimum above its maximum")
        elif not bound.minimum <= bound.default <= bound.maximum:
            problems.append(
                f"{bound.name} defaults to {bound.default}, outside its own declared "
                f"{bound.minimum}..{bound.maximum}"
            )
    for family in declaration.families:
        expected = 1
        for key in family.attributes:
            expected *= len(declaration.vocabulary.get(key, ()))
        if expected != family.series:
            problems.append(
                f"{family.name} declares {family.series} series, and the vocabularies "
                f"it names multiply to {expected}"
            )
        if family.series != family.budget:
            problems.append(
                f"{family.name} declares a budget of {family.budget} against "
                f"{family.series} series; these five must be equal"
            )
        for key in family.attributes:
            if key not in declaration.vocabulary:
                problems.append(f"{family.name} names attribute {key!r}, which has no vocabulary")
    return tuple(problems)


def route_problems(declaration: Declaration, source: str) -> tuple[str, ...]:
    """Judge the declared routes against the route table in the source.

    Args:
        declaration: The parsed contract.
        source: The text of the domain module.

    Returns:
        One sentence per disagreement, in both directions.

    Bidirectional on purpose. A route in the source that this file does not
    describe is the worse direction: it is a reachable endpoint nobody wrote down.
    """
    found = {match.group("path"): match.group("member") for match in ROUTE_ENTRY.finditer(source)}
    if not found:
        return ("no route table could be recovered from the source",)
    problems: list[str] = []
    for route in declaration.routes:
        member = found.get(route.path)
        if member is None:
            problems.append(f"the source serves no route at {route.path!r}")
        elif member.lower() != route.route:
            problems.append(
                f"{route.path!r} is labelled {route.route!r} here and "
                f"{member.lower()!r} in the source"
            )
    declared = {route.path for route in declaration.routes}
    for path in sorted(set(found) - declared):
        problems.append(f"the source serves {path!r}, which this contract does not describe")
    return tuple(problems)


def loopback_problems(declaration: Declaration, source: str) -> tuple[str, ...]:
    """Judge the declared addresses against the constants in the source.

    Args:
        declaration: The parsed contract.
        source: The text of the domain module.

    Returns:
        One sentence per address the source does not declare.
    """
    constants = {match.group("value") for match in STRING_CONSTANT.finditer(source)}
    missing = [address for address in declaration.addresses if address not in constants]
    if missing:
        return tuple(f"the source declares no constant for the address {a!r}" for a in missing)
    if declaration.value_type not in source:
        return (f"the source does not name the value type {declaration.value_type!r}",)
    return ()


def binding_problems(declaration: Declaration, source: str) -> tuple[str, ...]:
    """Judge that the binding module spells no address at all.

    Args:
        declaration: The parsed contract.
        source: The text of the binding module.

    Returns:
        One sentence per address literal found.

    **Stronger than checking for a wildcard, and that is the whole point.** An
    address the module cannot spell is an address it cannot bind, so the only one
    reachable is the one it was handed — and the only way to hand it one is the
    value type, which has already refused everything but loopback. A future edit
    hardcoding *any* address fails here, whether or not somebody would have
    recognised it as dangerous.
    """
    found = sorted({match.group("address") for match in ADDRESS_LITERAL.finditer(source)})
    if found:
        return tuple(
            f"{declaration.binding_module} spells the address {address!r} rather than "
            f"being handed one"
            for address in found
        )
    return ()


def wildcard_problems(declaration: Declaration, sources: dict[str, str]) -> tuple[str, ...]:
    """Judge that no spelling of "every interface" appears in the package.

    Args:
        declaration: The parsed contract.
        sources: Every package module, by repository-relative path.

    Returns:
        One sentence per module carrying a forbidden token.

    The absence that sits beside the value type, because the type cannot see this:
    it can only refuse an address that reaches it, and a wildcard written straight
    into a bind call reaches nothing.
    """
    problems: list[str] = []
    for name in sorted(sources):
        found = [token for token in declaration.forbidden_tokens if token in sources[name]]
        if found:
            problems.append(f"{name} spells {', '.join(repr(token) for token in found)}")
    return tuple(problems)


def bound_problems(declaration: Declaration, domain: str, config: str) -> tuple[str, ...]:
    """Judge every declared bound against the constants and defaults in the source.

    Args:
        declaration: The parsed contract.
        domain: The text of the domain module.
        config: The text of the configuration module.

    Returns:
        One sentence per number that disagrees.

    Four numbers per bound, recovered from two files. The arithmetic error a reader
    of either file alone could not catch is a default outside its own range, and
    :func:`contract_problems` catches the declared form of that while this catches
    the form where the source and the contract have drifted apart.
    """
    constants = {
        match.group("name"): int(match.group("value"))
        for match in INTEGER_CONSTANT.finditer(domain)
    }
    defaults = _section_defaults(config)
    problems: list[str] = []
    for bound in declaration.bounds:
        for edge, declared in (("MINIMUM", bound.minimum), ("MAXIMUM", bound.maximum)):
            name = f"{edge}_{bound.constant}"
            found = constants.get(name)
            if found is None:
                problems.append(f"the source declares no {name}")
            elif found != declared:
                problems.append(f"{name} is {found} in the source and {declared} here")
        recorded = defaults.get(bound.default_field)
        if recorded is None:
            problems.append(f"the source declares no default for {bound.default_field}")
        elif recorded != str(bound.default):
            problems.append(
                f"{bound.default_field} defaults to {recorded} in the source and "
                f"{bound.default} here"
            )
    return tuple(problems)


def switch_problems(declaration: Declaration, config: str) -> tuple[str, ...]:
    """Judge every route's switch, and what it defaults to.

    Args:
        declaration: The parsed contract.
        config: The text of the configuration module.

    Returns:
        One sentence per switch that is missing or defaults the other way.

    **The snapshot route defaulting off is the claim worth a test of its own.** It
    is the most detailed thing the surface can say, and the whole reason it has a
    second switch is that turning the surface on must not turn it on too.
    """
    defaults = _section_defaults(config)
    problems: list[str] = []
    for route in declaration.routes:
        recorded = defaults.get(route.switch)
        if recorded is None:
            problems.append(f"the source declares no switch {route.switch!r}")
        elif recorded != str(route.answers_by_default):
            problems.append(
                f"{route.switch} defaults to {recorded} in the source, and this contract "
                f"says {route.path!r} answers by default: {route.answers_by_default}"
            )
    return tuple(problems)


def exposition_problems(declaration: Declaration, source: str) -> tuple[str, ...]:
    """Judge every declared content type against the constants in the source.

    Args:
        declaration: The parsed contract.
        source: The text of the domain module.

    Returns:
        One sentence per content type the source does not carry.

    A content type is the one string in this surface that a consumer parses rather
    than reads, so a drifted parameter is a scrape that a conforming client refuses.
    """
    constants = {match.group("value") for match in STRING_CONSTANT.finditer(source)}
    return tuple(
        f"the source declares no content type {exposition.content_type!r} for {exposition.format!r}"
        for exposition in declaration.expositions
        if exposition.content_type not in constants
    )


def family_problems(declaration: Declaration, domain: str, metrics: str) -> tuple[str, ...]:
    """Recompute every family's cardinality from the vocabularies in the source.

    Args:
        declaration: The parsed contract.
        domain: The text of the domain module, holding the vocabularies.
        metrics: The text of the metrics module, holding the descriptors.

    Returns:
        One sentence per family whose arithmetic does not hold.

    **This is the check that earns the gate.** Every other function here compares
    two statements of one value; this one multiplies the vocabulary sizes it found
    in the source and refuses a budget that is not the product. So a seventh route
    added to the enum — which grows the ``route`` vocabulary — fails here until both
    the affected budgets and this contract are corrected, in one edit.
    """
    vocabularies = _vocabularies(domain)
    problems: list[str] = []
    for family in declaration.families:
        if family.name not in metrics:
            problems.append(f"the registry declares no family named {family.name!r}")
            continue
        product = 1
        unknown = []
        for key in family.attributes:
            values = vocabularies.get(key)
            if values is None:
                unknown.append(key)
            else:
                product *= len(values)
        if unknown:
            problems.append(
                f"{family.name} names {', '.join(repr(k) for k in unknown)}, whose "
                f"vocabulary could not be recovered from the source"
            )
            continue
        if product != family.budget:
            problems.append(
                f"{family.name} declares a budget of {family.budget}, and the "
                f"vocabularies in the source multiply to {product}"
            )
    return tuple(problems)


def vocabulary_problems(declaration: Declaration, domain: str) -> tuple[str, ...]:
    """Judge every declared vocabulary against the enum members in the source.

    Args:
        declaration: The parsed contract.
        domain: The text of the domain module.

    Returns:
        One sentence per vocabulary that disagrees, in both directions.

    Bidirectional, because a value in the source that this contract omits is a
    label a dashboard can see and nobody declared.
    """
    found = _vocabularies(domain)
    problems: list[str] = []
    for key, declared in sorted(declaration.vocabulary.items()):
        recovered = found.get(key)
        if recovered is None:
            problems.append(f"no vocabulary for {key!r} could be recovered from the source")
        elif set(recovered) != set(declared):
            missing = sorted(set(declared) - set(recovered))
            extra = sorted(set(recovered) - set(declared))
            problems.append(
                f"the {key!r} vocabulary disagrees: this contract has "
                f"{missing or '[]'} the source does not, and the source has "
                f"{extra or '[]'} this contract does not"
            )
    return tuple(problems)


def test_problems(declaration: Declaration, present: dict[str, bool]) -> tuple[str, ...]:
    """Judge that every test module the contract names exists.

    Args:
        declaration: The parsed contract.
        present: Whether each named path was found, keyed by the same kind.

    Returns:
        One sentence per named module that is absent.

    Existence, not passing. Whether they pass is the suite's business; what this
    catches is a claim whose test was deleted, leaving the claim asserted here and
    enforced nowhere.
    """
    return tuple(
        f"the {kind} test {declaration.tests[kind]!r} does not exist"
        for kind in sorted(declaration.tests)
        if not present.get(kind, False)
    )


def _vocabularies(domain: str) -> dict[str, tuple[str, ...]]:
    """Recover each attribute key's value set from the enums in the source.

    Args:
        domain: The text of the domain module.

    Returns:
        Each key mapped to the values found, for the three keys this surface uses.

    The mapping from an attribute key to the enum that supplies it is declared here
    rather than derived, because the two names differ — ``status_class`` comes from
    ``StatusClass`` and ``reason`` from ``RejectionReason``, and a derivation would
    have to guess.
    """
    owners = {
        "route": "class DiagnosticsRoute(StrEnum):",
        "status_class": "class StatusClass(StrEnum):",
        "reason": "class RejectionReason(StrEnum):",
    }
    recovered: dict[str, tuple[str, ...]] = {}
    for key, header in owners.items():
        if header not in domain:
            continue
        body = domain.split(header, 1)[1]
        # Stop at the next top-level definition, so one enum's members cannot be
        # read as another's.
        for terminator in ("\nclass ", "\ndef ", "\n@dataclass"):
            body = body.split(terminator, 1)[0]
        values = tuple(match.group("value") for match in ENUM_MEMBER.finditer(body))
        if values:
            recovered[key] = values
    return recovered


def _section_defaults(config: str) -> dict[str, str]:
    """Recover the diagnostics section's field defaults from the source.

    Args:
        config: The text of the configuration module.

    Returns:
        Each field mapped to its default, as the source spells it — a literal
        resolved to its value where the default is a named constant.
    """
    header = "class DiagnosticsHttpConfig:"
    if header not in config:
        return {}
    body = config.split(header, 1)[1]
    for terminator in ("\nclass ", "\ndef ", "\n@dataclass"):
        body = body.split(terminator, 1)[0]
    constants = {
        match.group("name"): match.group("value").replace("_", "")
        for match in INTEGER_CONSTANT.finditer(config)
    }
    strings = {
        match.group("name"): match.group("value") for match in STRING_CONSTANT.finditer(config)
    }
    defaults: dict[str, str] = {}
    for match in DATACLASS_FIELD.finditer(body):
        raw = match.group("value")
        if raw in constants:
            defaults[match.group("field")] = constants[raw]
        elif raw in strings:
            defaults[match.group("field")] = strings[raw]
        else:
            defaults[match.group("field")] = raw.replace("_", "")
    return defaults


def _table(document: dict[str, object], name: str) -> dict[str, object]:
    """One required table.

    Args:
        document: The parsed TOML.
        name: The table's name.

    Returns:
        The table.

    Raises:
        EndpointContractError: If it is absent or is not a table.
    """
    found = document.get(name)
    if not isinstance(found, dict):
        msg = f"{CONFIGURATION_FILE} has no [{name}] table"
        raise EndpointContractError(msg)
    return found


def _array(document: dict[str, object], name: str) -> list[dict[str, object]]:
    """One required array of tables.

    Args:
        document: The parsed TOML.
        name: The array's name.

    Returns:
        The entries.

    Raises:
        EndpointContractError: If it is absent, empty, or holds a non-table.
    """
    found = document.get(name)
    if not isinstance(found, list) or not found:
        msg = f"{CONFIGURATION_FILE} declares no [[{name}]] entries"
        raise EndpointContractError(msg)
    for entry in found:
        if not isinstance(entry, dict):
            msg = f"{CONFIGURATION_FILE} has a [[{name}]] entry that is not a table"
            raise EndpointContractError(msg)
    return found


def _string(table: dict[str, object], key: str) -> str:
    """One required string.

    Args:
        table: The table to read.
        key: The key.

    Returns:
        The value.

    Raises:
        EndpointContractError: If it is absent or not a string.
    """
    found = table.get(key)
    if not isinstance(found, str) or not found:
        msg = f"{CONFIGURATION_FILE}: {key!r} is missing or is not a non-empty string"
        raise EndpointContractError(msg)
    return found


def _integer(table: dict[str, object], key: str) -> int:
    """One required integer.

    Args:
        table: The table to read.
        key: The key.

    Returns:
        The value.

    Raises:
        EndpointContractError: If it is absent, not an integer, or a boolean.
    """
    found = table.get(key)
    if isinstance(found, bool) or not isinstance(found, int):
        msg = f"{CONFIGURATION_FILE}: {key!r} is missing or is not an integer"
        raise EndpointContractError(msg)
    return found


def _strings(table: dict[str, object], key: str) -> list[str]:
    """One required list of strings, which may be empty.

    Args:
        table: The table to read.
        key: The key.

    Returns:
        The values.

    Raises:
        EndpointContractError: If it is absent or holds a non-string.
    """
    found = table.get(key)
    if not isinstance(found, list):
        msg = f"{CONFIGURATION_FILE}: {key!r} is missing or is not a list"
        raise EndpointContractError(msg)
    for value in found:
        if not isinstance(value, str):
            msg = f"{CONFIGURATION_FILE}: {key!r} holds something that is not a string"
            raise EndpointContractError(msg)
    return list(found)
