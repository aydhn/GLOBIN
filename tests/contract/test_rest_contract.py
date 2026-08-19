"""The declared transport contract against the package, in both directions.

``docs/engineering/rest-transport.toml`` records every venue fact the transport
encodes, with a citation for each. The code holds the same values. That is a second
copy, which ``docs/engineering/SOURCE_OF_TRUTH.md`` permits only when a test
compares the copies and fails when they diverge — this is that test.

**And the absences.** Several rules of this phase are things the package must *not*
contain: a retry construct, a way to disable certificate verification, a venue host,
a claim to have observed anything. Those are asserted by scanning the source,
because a validator can only refuse what reaches it and none of these would.
"""

import ast
import tomllib
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.rest import CONTRACT_PATH, parse_contract, read_contract
from globin.application.rest import self_test
from globin.domain.api_reality import ProductFamily
from globin.domain.rest import (
    ACCEPT_HEADER,
    AMBIGUOUS_EXCHANGE_CODES,
    AMBIGUOUS_STATUSES,
    MAX_HEADERS,
    MAX_LOGGED_BODY_BYTES,
    MAX_OPERATION_LENGTH,
    MAX_PATH_LENGTH,
    MAX_QUERY_PARAMETERS,
    MAX_RESPONSE_BYTES,
    MEDIA_TYPE_JSON,
    MEDIA_TYPE_SBE,
    ORDER_COUNT_PREFIX,
    RETRY_AFTER_HEADER,
    SBE_SCHEMA_HEADER,
    TIME_UNIT_HEADER,
    TIME_UNIT_MICROSECOND,
    USED_WEIGHT_PREFIX,
)
from globin.domain.rest_contract import TransportContract
from globin.runtime.composition import PACKAGE_RELATIVE_PATH

REGISTRY_PATH: Final[str] = "docs/engineering/binance-api-reality.toml"
"""Phase 033's registry, which every source cited by the contract must live in."""

TRANSPORT_MODULES: Final[tuple[str, ...]] = (
    "domain/rest.py",
    "domain/rest_endpoint.py",
    "domain/rest_contract.py",
    "adapters/rest.py",
    "adapters/rest_transport.py",
    "application/rest.py",
)
"""Every module this phase added, named so an absence check has a defined scope."""

RETRY_TOKENS: Final[tuple[str, ...]] = (
    "retries",
    "max_retries",
    "backoff",
    "reattempt",
    "resend",
)
"""Identifiers a retry mechanism would be built out of.

Not a proof — a loop spelled some other way would defeat it — but it catches the
realistic erosion, which is somebody adding a ``retries=3`` parameter because it
was convenient. ``retry`` alone is deliberately absent from this list:
``Retry-After`` is a header GLOBIN reads and records, and forbidding the substring
would forbid the code that parses it.
"""

TLS_BYPASS_TOKENS: Final[tuple[str, ...]] = (
    "CERT_NONE",
    "CERT_OPTIONAL",
    "_create_unverified_context",
)
"""Every spelling of "do not verify" that the standard library offers.

The same absence check ``test_library_discipline.py`` applies to a wildcard bind
address, and for the same reason: ``secure_context`` can only assert about a context
it built, and a caller constructing its own would never reach it.

**Compared against the code rather than the raw text**, which is a correction this
test needed on its first run. ``rest_transport.py``'s own docstring explains that
the package contains no such token — prose that *names* a rule is the opposite of
breaking it, and a substring scan called it a violation.
``test_library_discipline.py`` records the identical lesson from Phase 026.
"""


def _live_identifiers(tree: ast.AST) -> set[str]:
    """Every name a module actually uses, ignoring prose.

    Args:
        tree: The parsed source.

    Returns:
        Bare names and attribute names. Docstrings and comments contribute nothing,
        so a module may explain what it refuses without refusing itself.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> TransportContract:
    """The declared transport contract."""
    found = read_contract(repo_root / CONTRACT_PATH)
    assert found is not None, f"{CONTRACT_PATH} is absent"
    return found


@pytest.fixture(scope="module")
def declared_sources(repo_root: Path) -> set[str]:
    """Every source identifier Phase 033's registry declares."""
    document = tomllib.loads((repo_root / REGISTRY_PATH).read_text(encoding="utf-8"))
    return {str(row["id"]) for row in document["source"]}


def _sources(repo_root: Path) -> list[str]:
    """Every module file this phase added.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return [str(repo_root / PACKAGE_RELATIVE_PATH / name) for name in TRANSPORT_MODULES]


class TestTheContractAgreesWithTheCode:
    """Every declared value against the constant the package actually uses."""

    def test_every_negotiation_constant_matches(self, contract: TransportContract) -> None:
        """A header name in the contract that the package does not send is a lie."""
        assert contract.negotiation.disagreements() == ()

    def test_the_comparison_would_notice_a_difference(self) -> None:
        """Guard the guard: a checker that silently stopped comparing reads as a pass."""
        from dataclasses import replace

        drifted = parse_contract(Path(CONTRACT_PATH).read_text(encoding="utf-8")).negotiation
        wrong = replace(drifted, sbe_schema_header="X-WRONG")
        assert wrong.disagreements() != ()

    def test_the_ambiguous_statuses_agree_in_both_directions(
        self, contract: TransportContract
    ) -> None:
        """Neither side may move without the other.

        A status the code treats as ambiguous with no declared reason is a judgement
        nobody wrote down; a declared one the code ignores is a document that lies.
        """
        assert contract.ambiguous_statuses() == frozenset(AMBIGUOUS_STATUSES)

    def test_the_ambiguous_venue_codes_agree_in_both_directions(
        self, contract: TransportContract
    ) -> None:
        """``-1007`` is the only one, and it is a transcription rather than a judgement."""
        assert contract.ambiguous_exchange_codes() == frozenset(AMBIGUOUS_EXCHANGE_CODES)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            pytest.param("max_response_bytes", MAX_RESPONSE_BYTES, id="response-cap"),
            pytest.param("max_logged_body_bytes", MAX_LOGGED_BODY_BYTES, id="log-cap"),
            pytest.param("max_query_parameters", MAX_QUERY_PARAMETERS, id="parameters"),
            pytest.param("max_headers", MAX_HEADERS, id="headers"),
            pytest.param("max_path_length", MAX_PATH_LENGTH, id="path"),
            pytest.param("max_operation_length", MAX_OPERATION_LENGTH, id="operation"),
        ],
    )
    def test_every_declared_bound_matches_the_package(
        self, contract: TransportContract, key: str, value: int
    ) -> None:
        """The whole envelope in one document, recomputed rather than believed."""
        assert contract.limits[key] == value

    def test_every_declared_header_is_one_the_package_names(
        self, contract: TransportContract
    ) -> None:
        """The other direction: a constant in the code that nothing declares has no citation."""
        used = {
            ACCEPT_HEADER,
            MEDIA_TYPE_JSON,
            MEDIA_TYPE_SBE,
            SBE_SCHEMA_HEADER,
            TIME_UNIT_HEADER,
            TIME_UNIT_MICROSECOND,
            RETRY_AFTER_HEADER,
            USED_WEIGHT_PREFIX,
            ORDER_COUNT_PREFIX,
        }
        declared = set(contract.negotiation.as_record().values())
        assert used <= declared

    def test_the_self_test_passes_against_the_committed_contract(
        self, contract: TransportContract
    ) -> None:
        """The same eight checks ``globin rest selftest`` runs, in the suite.

        Duplication with the command is deliberate: the command exists for a machine
        with no pytest, and this exists so a contributor cannot ship a mismatch and
        discover it only on an operator's laptop.
        """
        report = self_test(contract)
        assert report.passed, [item.detail for item in report.failures]


class TestProvenance:
    """Every claim in the contract cites a source the one ledger declares."""

    def test_every_cited_source_exists_in_the_registry(
        self, contract: TransportContract, declared_sources: set[str]
    ) -> None:
        """There is one source ledger in this repository, and this file is not it.

        A second ledger would drift from the first, and drifting about *which
        document said what* is the failure this whole band exists to prevent.
        """
        cited = {contract.negotiation.source, contract.negotiation.sbe_source}
        cited |= {item.source for item in contract.probes}
        cited |= {item.source for item in contract.statuses}
        cited |= {item.source for item in contract.exchange_codes}
        missing = sorted(cited - declared_sources)
        assert not missing, f"the transport contract cites undeclared sources: {missing}"

    def test_every_status_rule_states_a_reason(self, contract: TransportContract) -> None:
        """A classification with no argument is a number somebody chose."""
        for rule in (*contract.statuses, *contract.exchange_codes):
            assert rule.reason, f"status {rule.code} declares no reason"

    def test_the_three_gateway_refusals_are_declared_unambiguous(
        self, contract: TransportContract
    ) -> None:
        """403, 418 and 429 by number, because marking one ambiguous would be unsafe.

        Phase 043 never retries an ambiguous outcome, so a rate-limit rejection
        recorded as ambiguous would become permanently unretryable — the opposite of
        what "being cautious" would achieve.
        """
        declared = {rule.code: rule.ambiguous_when_mutating for rule in contract.statuses}
        for code in (403, 418, 429):
            assert declared[code] is False


class TestProbes:
    """What the transport is permitted to send, and to whom."""

    def test_every_probe_is_declared_unauthenticated(self, contract: TransportContract) -> None:
        """A probe that needed a credential would not be a probe."""
        for probe in contract.probes:
            assert probe.security == "NONE", f"{probe.operation} is not declared public"

    def test_every_probe_declares_a_weight(self, contract: TransportContract) -> None:
        """A probe that cost more than it appeared to is a bad thing to learn later."""
        for probe in contract.probes:
            assert probe.weight >= 1

    def test_every_probe_path_is_relative_to_the_recorded_prefix(
        self, contract: TransportContract
    ) -> None:
        """Writing the full path here would put the prefix in two places.

        The registry records ``path_prefix = "/api"``, so a probe declaring
        ``/api/v3/ping`` would resolve to ``/api/api/v3/ping``.
        """
        for probe in contract.probes:
            assert not probe.path.startswith("/api/"), f"{probe.operation} repeats the prefix"

    def test_a_family_with_no_declared_probe_gets_none_rather_than_a_guess(
        self, contract: TransportContract
    ) -> None:
        """Nine families have no documented REST surface, so they have no probe."""
        assert contract.probes_for(ProductFamily("options")) == ()
        assert contract.probe(ProductFamily("options"), "options.ping") is None


class TestTheProhibitionsAreReal:
    """Each declared absence, asserted against the source rather than believed."""

    def test_every_prohibition_is_declared_prohibited(self, contract: TransportContract) -> None:
        """Every entry in that table names something the transport does not do.

        A ``true`` would be a contract asserting its own violation, which the type
        refuses at construction — this is the assertion that the committed document
        actually reached that constructor.
        """
        assert not [name for name, value in contract.prohibitions.items() if value]

    def test_no_transport_module_carries_a_retry_construct(self, repo_root: Path) -> None:
        """Phase 043 owns retry, and inherits a transport that cannot be asked to do it."""
        offenders: dict[str, list[str]] = {}
        for path in _sources(repo_root):
            tree = ast.parse(Path(path).read_text(encoding="utf-8"))
            names = {
                node.id if isinstance(node, ast.Name) else node.arg
                for node in ast.walk(tree)
                if isinstance(node, ast.Name | ast.arg)
            }
            found = sorted(names.intersection(RETRY_TOKENS))
            if found:
                offenders[path] = found
        assert not offenders, f"a retry construct appeared: {offenders}"

    def test_the_retry_detector_would_notice_one(self) -> None:
        """Guard the guard, and prove ``Retry-After`` is not caught by it."""
        caught = ast.parse("def send(self, retries: int = 3) -> None: ...\n")
        names = {
            node.id if isinstance(node, ast.Name) else node.arg
            for node in ast.walk(caught)
            if isinstance(node, ast.Name | ast.arg)
        }
        assert names.intersection(RETRY_TOKENS)
        spared = ast.parse('RETRY_AFTER_HEADER = "Retry-After"\n')
        spared_names = {node.id for node in ast.walk(spared) if isinstance(node, ast.Name)}
        assert not spared_names.intersection(RETRY_TOKENS)

    def test_no_module_in_the_package_can_disable_certificate_verification(
        self, repo_root: Path
    ) -> None:
        """The absence check that sits beside ``secure_context``.

        That function can only assert about a context it built; a module
        constructing its own unverified one would never reach it. Checked over the
        **whole package** rather than the transport modules, because the point is
        that no second place can do it either.
        """
        offenders: dict[str, list[str]] = {}
        for path in sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py")):
            used = _live_identifiers(ast.parse(path.read_text(encoding="utf-8")))
            found = sorted(used.intersection(TLS_BYPASS_TOKENS))
            if found:
                offenders[str(path)] = found
        assert not offenders, f"a way to disable TLS verification appeared: {offenders}"

    def test_nothing_in_the_transport_claims_to_have_observed_a_capability(
        self, repo_root: Path
    ) -> None:
        """``EvidenceKind.OBSERVED`` exists and nothing may write it.

        GLOBIN now reaches the venue, which is exactly when this rule stops being
        free — a probe result is evidence about a run and never an edit to the
        registry.
        """
        offenders: dict[str, list[str]] = {}
        for path in _sources(repo_root):
            used = _live_identifiers(ast.parse(Path(path).read_text(encoding="utf-8")))
            if "OBSERVED" in used:
                offenders[path] = ["EvidenceKind.OBSERVED"]
        assert not offenders, f"a module claims observation: {offenders}"

    @pytest.mark.parametrize(
        ("source", "caught"),
        [
            pytest.param("context.verify_mode = ssl.CERT_NONE\n", True, id="an-assignment"),
            pytest.param("from ssl import CERT_NONE\n", False, id="an-import-alone-is-inert"),
            pytest.param('"""CERT_NONE is forbidden."""\n', False, id="a-docstring"),
            pytest.param("# CERT_NONE is forbidden\n", False, id="a-comment"),
            pytest.param('note = "CERT_NONE"\n', False, id="a-string-naming-it"),
        ],
    )
    def test_the_tls_detector_reads_code_and_not_prose(self, source: str, caught: bool) -> None:
        """Guard the guard, in both directions.

        The three false cases are the point. A rule whose *explanation* violates it
        teaches people to write around the checker rather than to obey the rule, and
        the transport's own docstring has to be able to name what it forbids.

        The bare import is deliberately not caught: importing the constant does
        nothing on its own, and the assignment that would use it is what this scans
        for. A module that imported it and never used it would be odd rather than
        dangerous.
        """
        used = _live_identifiers(ast.parse(source))
        assert bool(used.intersection(TLS_BYPASS_TOKENS)) is caught
