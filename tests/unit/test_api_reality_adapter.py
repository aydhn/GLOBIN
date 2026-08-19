"""Reading the registry document, and publishing evidence about it.

The reader narrows every field it takes out of TOML, and each narrowing has a
refusal that the committed registry will never exercise — a document that is
correct never reaches the branch that reports one that is not. Those branches are
what this module holds to account, because a narrowing that silently accepted the
wrong type would produce a snapshot whose fields lie about their own shape.

Two failures are kept apart throughout: an **absent** declaration produces ``None``
and is reported as unmeasured, and a **wrong** one raises. Flattening them would let
a corrupted registry report as merely unread.
"""

from pathlib import Path

import pytest

from globin.adapters.api_reality import (
    DIGEST_KEY,
    MANIFEST_NAME,
    RegistryError,
    TomlApiRealitySource,
    build,
    digest,
    load,
    parse_registry,
    read_registry,
    render,
    summarise,
    write,
)
from globin.domain.api_reality import ApiRealitySnapshot, ProductFamily, SurfaceStatus

MINIMAL = """
schema = 1

[[source]]
id = "doc"
title = "A document"
location = "https://raw.githubusercontent.com/binance/x/master/a.md"
authority = "primary"
regime = "digest"
accessed = "2026-08-19"

[[product]]
family = "spot"
scope = "trading"
title = "Spot"
status = "supported"
evidence = "documented"
source = "doc"

[[environment]]
family = "spot"
environment = "production"
semantics = "The live exchange."
carries_real_capital = true
status = "supported"
evidence = "documented"
source = "doc"
"""


class TestParsing:
    """A document is narrowed field by field, and each narrowing can refuse."""

    def test_a_minimal_registry_becomes_a_snapshot(self) -> None:
        """The base case, so a later refusal means the parser was working."""
        snapshot = parse_registry(MINIMAL)
        found = snapshot.product(ProductFamily("spot"))
        assert found is not None
        assert found.capability.status is SurfaceStatus.SUPPORTED

    def test_unparseable_toml_is_refused(self) -> None:
        """A document that is not TOML is not a registry with problems."""
        with pytest.raises(RegistryError, match="not valid TOML"):
            parse_registry("[[[")

    def test_an_unrecognised_schema_is_refused_rather_than_read(self) -> None:
        """Reading a shape this GLOBIN does not know is guessing at the fields."""
        with pytest.raises(RegistryError, match="announces schema"):
            parse_registry("schema = 7")

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            pytest.param("path_prefix", "7", "must be a string", id="string-field"),
            pytest.param("port", '"9000"', "must be an integer", id="integer-field"),
            pytest.param("tls_required", '"yes"', "must be true or false", id="boolean-field"),
            pytest.param("key_types", '"hmac"', "must be a list of strings", id="list-field"),
        ],
    )
    def test_a_field_of_the_wrong_type_is_refused(
        self, field: str, value: str, message: str
    ) -> None:
        """TOML has types, and a field carrying the wrong one is a defect not a coercion."""
        document = (
            MINIMAL
            + f"""
[[endpoint]]
family = "spot"
environment = "production"
protocol = "rest"
url = "https://api.binance.com/api"
transport = "https"
request_encoding = "json"
response_encoding = "json"
auth = "signed"
{field} = {value}
status = "supported"
evidence = "documented"
source = "doc"
"""
        )
        with pytest.raises(RegistryError, match=message):
            parse_registry(document)

    def test_a_boolean_is_not_accepted_where_an_integer_belongs(self) -> None:
        """``bool`` is an ``int`` subclass, so ``true`` would otherwise read as port 1."""
        document = (
            MINIMAL
            + """
[[endpoint]]
family = "spot"
environment = "production"
protocol = "fix_order_entry"
url = "tcp+tls://fix-oe.binance.com:9000"
transport = "tcp_tls"
request_encoding = "fix_text"
response_encoding = "fix_text"
auth = "signed"
port = true
sni_required = true
status = "supported"
evidence = "documented"
source = "doc"
"""
        )
        with pytest.raises(RegistryError, match="must be an integer"):
            parse_registry(document)

    def test_an_array_of_tables_that_is_not_one_is_refused(self) -> None:
        """A scalar where a table array belongs would otherwise be silently empty."""
        with pytest.raises(RegistryError, match="array of tables"):
            parse_registry("schema = 1\nproduct = 3\n")

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            pytest.param("status", "maybe", id="status"),
            pytest.param("evidence", "hearsay", id="evidence"),
            pytest.param("scope", "someday", id="scope"),
        ],
    )
    def test_an_unrecognised_word_is_refused(self, field: str, value: str) -> None:
        """Every vocabulary is closed, and a word outside it is a document defect.

        Narrowed here rather than letting ``ValueError`` escape, so every registry
        fault arrives in one class and one exit code.
        """
        document = MINIMAL.replace(f'{field} = "supported"', f'{field} = "{value}"')
        document = document.replace(f'{field} = "documented"', f'{field} = "{value}"')
        document = document.replace(f'{field} = "trading"', f'{field} = "{value}"')
        with pytest.raises(RegistryError, match="not one this GLOBIN recognises"):
            parse_registry(document)


class TestReading:
    """Absent and wrong are two different answers."""

    def test_an_absent_file_is_nothing_rather_than_an_error(self, tmp_path: Path) -> None:
        """A caller reports this as unmeasured; nothing was established."""
        assert read_registry(tmp_path / "gone.toml") is None

    def test_a_directory_is_also_nothing(self, tmp_path: Path) -> None:
        """Unreadable for any operating-system reason is the same answer."""
        assert read_registry(tmp_path) is None

    def test_a_present_and_broken_file_raises(self, tmp_path: Path) -> None:
        """A defect in a committed document is not an absence of one."""
        target = tmp_path / "registry.toml"
        target.write_text("schema = 7\n", encoding="utf-8")
        with pytest.raises(RegistryError):
            read_registry(target)

    def test_the_source_satisfies_its_port(self, tmp_path: Path) -> None:
        """The adapter is reached through the protocol, not by its concrete name.

        The conformance itself is asserted by mypy, at
        ``build_api_reality_source`` in the composition root, whose return type is
        the protocol -- so an adapter that drifted from the contract fails the
        typecheck rather than this test. What runs here is that it works.
        """
        target = tmp_path / "registry.toml"
        target.write_text(MINIMAL, encoding="utf-8")
        source = TomlApiRealitySource(path=target)
        found = source.snapshot()
        assert found is not None
        assert found.products

    def test_the_source_reports_nothing_when_there_is_nothing(self, tmp_path: Path) -> None:
        """The protocol's own contract: never a partially populated snapshot."""
        assert TomlApiRealitySource(path=tmp_path / "gone.toml").snapshot() is None


class TestManifest:
    """The evidence verifies itself, and carries no clock."""

    def test_the_digest_covers_everything_except_itself(self) -> None:
        """A digest that included itself could never be computed twice."""
        document = build(run={"a": 1}, findings={"b": 2}, verdict={"c": 3})
        assert document[DIGEST_KEY] == digest(document)

    def test_changing_any_content_changes_the_digest(self) -> None:
        """Otherwise the seal would cover less than the document."""
        first = build(run={"a": 1}, findings={}, verdict={})
        second = build(run={"a": 2}, findings={}, verdict={})
        assert first[DIGEST_KEY] != second[DIGEST_KEY]

    def test_content_edited_after_the_digest_was_taken_is_refused(self) -> None:
        """The point of the digest, asserted rather than assumed."""
        document = build(run={"a": 1}, findings={}, verdict={})
        document["run"] = {"a": 2}
        with pytest.raises(RegistryError, match="edited after"):
            load(render(document))

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            pytest.param("{", "not valid JSON", id="not-json"),
            pytest.param("[]", "not a JSON object", id="not-an-object"),
            pytest.param('{"schema": "other"}', "announces schema", id="another-schema"),
        ],
    )
    def test_a_manifest_that_does_not_verify_is_refused(self, text: str, message: str) -> None:
        """Four refusals the gate can never reach itself; it only reads what it wrote."""
        with pytest.raises(RegistryError, match=message):
            load(text)

    def test_a_manifest_of_the_wrong_version_is_refused(self) -> None:
        """A newer document is refused rather than read and partly understood."""
        document = build(run={}, findings={}, verdict={})
        document["schema_version"] = 99
        with pytest.raises(RegistryError, match="announces version"):
            load(render(document))

    def test_a_written_manifest_reads_back(self, tmp_path: Path) -> None:
        """The round trip, through the filesystem rather than in memory."""
        document = build(run={"a": 1}, findings={}, verdict={})
        target = write(document, directory=tmp_path / "evidence")
        assert target.name == MANIFEST_NAME
        assert load(target.read_text(encoding="utf-8")) == document

    def test_a_manifest_carries_no_clock(self) -> None:
        """No manifest in this repository does.

        One that changed because it was built on a different day could not be
        compared with itself.
        """
        rendered = render(build(run={}, findings={}, verdict={}))
        assert "generated" not in rendered
        assert "timestamp" not in rendered


class TestSummary:
    """What a manifest records about a snapshot, and what it deliberately does not."""

    def test_a_summary_counts_rather_than_copies(self) -> None:
        """A manifest embedding the document it describes would prove nothing.

        It would change whenever the document did, and comparing two of them would
        only establish that the registry had been edited.
        """
        found = summarise(parse_registry(MINIMAL))
        assert found["products"] == 1
        assert "sources" in found
        assert "family" not in found

    def test_a_summary_names_the_sources_no_refresh_can_reach(self) -> None:
        """Drift detection covers less than it appears to, and the limit is published."""
        manual = MINIMAL.replace('regime = "digest"', 'regime = "manual"')
        assert summarise(parse_registry(manual))["unrefreshable_sources"] == ["doc"]

    def test_a_summary_is_stable(self) -> None:
        """Two summaries of one snapshot agree, which is what the digest rests on."""
        snapshot = parse_registry(MINIMAL)
        assert summarise(snapshot) == summarise(snapshot)

    def test_an_empty_snapshot_summarises_to_zeroes(self) -> None:
        """An absent key would read as an absent question rather than an empty answer."""
        found = summarise(ApiRealitySnapshot())
        assert found["products"] == 0
        assert found["unrefreshable_sources"] == []
