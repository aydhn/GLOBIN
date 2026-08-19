"""The transport contract reader and the evidence writer, driven through their refusals.

Every narrowing here has a **failing** branch that a correct committed document
never reaches — which makes it the branch that would silently accept the wrong type
if it broke. A reader that took a string where an integer belongs would produce a
contract that parsed and meant something else.

The manifest's refusals are the same shape: the writer can never reach them itself,
because it only ever reads a document it has just written.
"""

import json
from pathlib import Path

import pytest

from globin.adapters.rest import (
    CONTRACT_PATH,
    MANIFEST_NAME,
    TransportContractError,
    build,
    digest,
    load,
    parse_contract,
    read_contract,
    render,
    write,
)
from globin.domain.api_reality import ProductFamily, SurfaceCapability
from globin.domain.rest import HttpMethod
from globin.domain.rest_contract import (
    NegotiationDeclaration,
    ProbeDescriptor,
    StatusRule,
    TransportContract,
)
from globin.errors import ValidationError

MINIMAL = """
schema = 1
[target]
venue = "test"
phase = 34
observed_on = "2026-08-19"
[negotiation]
accept_header = "Accept"
media_type_json = "application/json"
media_type_sbe = "application/sbe"
sbe_schema_header = "X-MBX-SBE"
sbe_schema_format = "<ID>:<VERSION>"
time_unit_header = "X-MBX-TIME-UNIT"
time_unit_microsecond = "MICROSECOND"
retry_after_header = "Retry-After"
used_weight_prefix = "X-MBX-USED-WEIGHT-"
order_count_prefix = "X-MBX-ORDER-COUNT-"
sbe_source = "s"
source = "s"
[limits]
max_response_bytes = 1
[prohibitions]
automatic_retry = false
"""


def _negotiation(**overrides: str) -> NegotiationDeclaration:
    """A declaration that agrees with the package unless a test disagrees with it."""
    fields = {
        "accept_header": "Accept",
        "media_type_json": "application/json",
        "media_type_sbe": "application/sbe",
        "sbe_schema_header": "X-MBX-SBE",
        "sbe_schema_format": "<ID>:<VERSION>",
        "time_unit_header": "X-MBX-TIME-UNIT",
        "time_unit_microsecond": "MICROSECOND",
        "retry_after_header": "Retry-After",
        "used_weight_prefix": "X-MBX-USED-WEIGHT-",
        "order_count_prefix": "X-MBX-ORDER-COUNT-",
        "source": "s",
        "sbe_source": "s",
    }
    fields.update(overrides)
    return NegotiationDeclaration(**fields)


def _probe(**overrides: object) -> ProbeDescriptor:
    """One probe descriptor."""
    fields: dict[str, object] = {
        "family": ProductFamily("spot"),
        "operation": "spot.ping",
        "method": HttpMethod.GET,
        "path": "/v3/ping",
        "capability": SurfaceCapability.MARKET_DATA,
        "weight": 1,
        "security": "NONE",
        "notes": "test",
        "source": "s",
    }
    fields.update(overrides)
    return ProbeDescriptor(**fields)  # type: ignore[arg-type]


class TestTheContractReaderRefusals:
    """Every branch a correct document never reaches."""

    def test_the_minimal_document_parses(self) -> None:
        """So the refusals below are not the only thing proved."""
        contract = parse_contract(MINIMAL)
        assert contract.phase == 34
        assert contract.negotiation.disagreements() == ()

    def test_malformed_toml_is_refused(self) -> None:
        """``TOMLDecodeError`` is a ``ValueError``; Phase 030 found that the hard way."""
        with pytest.raises(TransportContractError, match="not valid TOML"):
            parse_contract("not [ toml")

    @pytest.mark.parametrize("table", ["target", "negotiation", "limits", "prohibitions"])
    def test_a_missing_table_is_refused(self, table: str) -> None:
        """Each of the four is required, and each says which one is missing."""
        document = "\n".join(
            line for line in MINIMAL.splitlines() if not line.startswith(f"[{table}]")
        )
        with pytest.raises(TransportContractError, match=table):
            parse_contract(document)

    def test_a_string_field_carrying_a_number_is_refused(self) -> None:
        """The branch that would silently produce a contract meaning something else."""
        document = MINIMAL.replace('accept_header = "Accept"', "accept_header = 7")
        with pytest.raises(TransportContractError, match="not a string"):
            parse_contract(document)

    def test_an_integer_field_carrying_a_string_is_refused(self) -> None:
        """Same shape, other direction."""
        document = MINIMAL.replace("phase = 34", 'phase = "thirty-four"')
        with pytest.raises(TransportContractError, match="not an integer"):
            parse_contract(document)

    def test_a_boolean_where_an_integer_belongs_is_refused(self) -> None:
        """``bool`` is an ``int`` subclass, so ``true`` would otherwise read as ``1``."""
        document = MINIMAL.replace("phase = 34", "phase = true")
        with pytest.raises(TransportContractError, match="not an integer"):
            parse_contract(document)

    def test_an_array_key_holding_a_scalar_is_refused(self) -> None:
        """A single table where an array belongs is a document nobody meant to write."""
        # Prepended, not appended: a key written after the last table would
        # belong to that table rather than to the document, and the test
        # would prove nothing.
        document = 'probe = "not-an-array"' + MINIMAL
        with pytest.raises(TransportContractError, match="not an array of tables"):
            parse_contract(document)

    def test_an_array_entry_that_is_not_a_table_is_refused(self) -> None:
        """The inner half of the same check."""
        document = "probe = [1, 2]" + MINIMAL
        with pytest.raises(TransportContractError, match="not a table"):
            parse_contract(document)

    def test_an_unknown_enumeration_value_is_refused(self) -> None:
        """A method the transport cannot send is refused where it is declared."""
        document = (
            MINIMAL + '\n[[probe]]\nfamily = "spot"\noperation = "spot.ping"\nmethod = "PATCH"\n'
            'path = "/v3/ping"\ncapability = "market_data"\nweight = 1\nsecurity = "NONE"\n'
            'notes = "x"\nsource = "s"\n'
        )
        with pytest.raises(TransportContractError, match="not a permitted value"):
            parse_contract(document)

    def test_a_status_rule_with_no_boolean_verdict_is_refused(self) -> None:
        """The field the whole outcome model is recomputed from cannot be absent."""
        document = MINIMAL + '\n[[status]]\ncode = 500\nmeaning = "x"\nreason = "y"\nsource = "s"\n'
        with pytest.raises(TransportContractError, match="ambiguous_when_mutating"):
            parse_contract(document)

    def test_an_exchange_code_rule_may_name_itself_rather_than_a_meaning(self) -> None:
        """The two rule shapes differ by one field name, and both are accepted."""
        document = (
            MINIMAL + '\n[[exchange_code]]\ncode = -1007\nname = "TIMEOUT"\n'
            'ambiguous_when_mutating = true\nreason = "y"\nsource = "s"\n'
        )
        contract = parse_contract(document)
        assert contract.ambiguous_exchange_codes() == frozenset({-1007})

    def test_an_absent_document_reads_as_nothing(self, tmp_path: Path) -> None:
        """Unmeasured rather than empty, which a caller reports as such."""
        assert read_contract(tmp_path / "absent.toml") is None

    def test_the_committed_document_reads(self, repo_root: Path) -> None:
        """The one that ships."""
        assert read_contract(repo_root / CONTRACT_PATH) is not None


class TestTheContractValueTypes:
    """What a parsed contract refuses to be."""

    def test_a_repeated_probe_operation_is_refused(self) -> None:
        """Two descriptors for one operation is a lookup nobody can predict."""
        with pytest.raises(ValidationError, match="more than once"):
            TransportContract(
                negotiation=_negotiation(),
                probes=(_probe(), _probe()),
                statuses=(),
                exchange_codes=(),
                limits={},
                prohibitions={},
                phase=34,
                observed_on="2026-08-19",
            )

    def test_a_repeated_status_code_is_refused(self) -> None:
        """Same reason, other table."""
        rule = StatusRule(
            code=500, meaning="x", ambiguous_when_mutating=True, reason="y", source="s"
        )
        with pytest.raises(ValidationError, match="more than once"):
            TransportContract(
                negotiation=_negotiation(),
                probes=(),
                statuses=(rule, rule),
                exchange_codes=(),
                limits={},
                prohibitions={},
                phase=34,
                observed_on="2026-08-19",
            )

    def test_a_prohibition_declared_true_is_refused(self) -> None:
        """Every entry in that table names something the transport does *not* do.

        A ``true`` would be a contract asserting its own violation, so the type
        refuses to hold one.
        """
        with pytest.raises(ValidationError, match="declares automatic_retry as permitted"):
            TransportContract(
                negotiation=_negotiation(),
                probes=(),
                statuses=(),
                exchange_codes=(),
                limits={},
                prohibitions={"automatic_retry": True},
                phase=34,
                observed_on="2026-08-19",
            )

    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            pytest.param({"operation": ""}, "names no operation", id="no-operation"),
            pytest.param({"path": "v3/ping"}, "not rooted", id="an-unrooted-path"),
            pytest.param({"weight": 0}, "weight of 0", id="a-weightless-probe"),
        ],
    )
    def test_a_probe_that_could_not_be_sent_is_refused(
        self, overrides: dict[str, object], match: str
    ) -> None:
        """A path that is not rooted joins wrongly; a weight of zero is not a cost."""
        with pytest.raises(ValidationError, match=match):
            _probe(**overrides)

    def test_a_probe_lookup_returns_nothing_rather_than_guessing(self) -> None:
        """Nine families have no declared probe, and none gets an invented path."""
        contract = TransportContract(
            negotiation=_negotiation(),
            probes=(_probe(),),
            statuses=(),
            exchange_codes=(),
            limits={},
            prohibitions={},
            phase=34,
            observed_on="2026-08-19",
        )
        assert contract.probe(ProductFamily("options"), "options.ping") is None
        assert contract.probes_for(ProductFamily("options")) == ()
        assert contract.probe(ProductFamily("spot"), "spot.ping") is not None

    @pytest.mark.parametrize(
        "field",
        [
            "accept_header",
            "media_type_json",
            "media_type_sbe",
            "sbe_schema_header",
            "time_unit_header",
            "time_unit_microsecond",
            "retry_after_header",
            "used_weight_prefix",
            "order_count_prefix",
        ],
    )
    def test_every_declared_constant_is_actually_compared(self, field: str) -> None:
        """Guard the guard, one field at a time.

        A comparison that silently stopped covering a field would read as a passing
        contract for ever. Each is broken individually so no single one can be the
        one nobody checks.
        """
        assert _negotiation(**{field: "WRONG"}).disagreements() != ()

    def test_the_record_is_json_safe(self) -> None:
        """It goes into the manifest, so every leaf must survive `json.dumps`."""
        contract = TransportContract(
            negotiation=_negotiation(),
            probes=(_probe(),),
            statuses=(
                StatusRule(
                    code=500, meaning="x", ambiguous_when_mutating=True, reason="y", source="s"
                ),
            ),
            exchange_codes=(),
            limits={"a": 1},
            prohibitions={"b": False},
            phase=34,
            observed_on="2026-08-19",
        )
        assert json.loads(json.dumps(contract.as_record()))["phase"] == 34


class TestTheManifest:
    """Five refusals the writer can never reach itself."""

    def _document(self) -> dict[str, object]:
        return build(run={"a": 1}, findings={"b": 2}, verdict={"c": 3})

    def test_a_manifest_carries_its_own_digest(self) -> None:
        """Set last, over everything except itself."""
        document = self._document()
        assert document["digest"] == digest(document)

    def test_rendering_is_canonical_and_stable(self) -> None:
        """Sorted keys, no incidental whitespace, one trailing newline."""
        document = self._document()
        assert render(document) == render(document)
        assert render(document).endswith("}\n")

    def test_a_manifest_round_trips(self, tmp_path: Path) -> None:
        """What is written reads back as what was built."""
        written = write(self._document(), directory=tmp_path)
        assert written.name == MANIFEST_NAME
        assert load(written.read_text(encoding="utf-8"))["phase"] == 34

    def test_the_directory_is_created_if_absent(self, tmp_path: Path) -> None:
        """A fresh clone has no `.globin/rest/` yet."""
        written = write(self._document(), directory=tmp_path / "deep" / "nested")
        assert written.is_file()

    def test_a_manifest_that_is_not_json_is_refused(self) -> None:
        """A truncated write must not read as an empty manifest."""
        with pytest.raises(TransportContractError, match="not valid JSON"):
            load("not json")

    def test_a_manifest_that_is_not_an_object_is_refused(self) -> None:
        """Valid JSON that is not a manifest is still not a manifest."""
        with pytest.raises(TransportContractError, match="not an object"):
            load("[1, 2, 3]")

    def test_a_manifest_with_no_digest_is_refused(self) -> None:
        """Without one there is nothing to check the content against."""
        with pytest.raises(TransportContractError, match="carries no digest"):
            load('{"phase": 34}')

    def test_a_manifest_edited_after_publication_is_refused(self) -> None:
        """The whole reason the digest is written at all."""
        text = render(self._document())
        with pytest.raises(TransportContractError, match="edited"):
            load(text.replace('"phase":34', '"phase":99'))
