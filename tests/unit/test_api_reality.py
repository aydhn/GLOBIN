"""The registry's own rules, asserted one refusal at a time.

Every test here builds a record and checks that a document which could be acted on
wrongly cannot be constructed at all. The distinction the phase exists for --
`UNKNOWN` against `UNSUPPORTED` -- is asserted in :func:`test_unknown_is_not_usable`
and in the diff's risk table, because it is the one that decays quietest if nobody
holds it.
"""

import pytest

from globin.domain.api_reality import (
    MAX_FINDINGS,
    MAX_PRODUCTS,
    ApiKeyType,
    ApiRealityDiff,
    ApiRealitySnapshot,
    AuthMechanism,
    CapabilityRecord,
    DriftClass,
    DriftFinding,
    DriftRisk,
    EncodingKind,
    EndpointRecord,
    EnvironmentName,
    EnvironmentRecord,
    EvidenceKind,
    KeyPermission,
    ProductFamily,
    ProductProfile,
    ProductScope,
    ProtocolKind,
    SchemaFamilyName,
    SchemaLifecycleState,
    SchemaVersion,
    SourceAuthority,
    SourceObservation,
    SourceRegime,
    SurfaceCapability,
    SurfaceRecord,
    SurfaceStatus,
    TransportKind,
    diff,
)
from globin.errors import ValidationError

SPOT = ProductFamily("spot")
LIVE = EnvironmentName("production")
PAPER = EnvironmentName("testnet")


def source(identifier: str = "doc", **overrides: object) -> SourceObservation:
    """One valid source, with fields replaced.

    Args:
        identifier: What to call it.
        **overrides: Fields to change.

    Returns:
        The observation.
    """
    fields: dict[str, object] = {
        "identifier": identifier,
        "title": "A document",
        "location": "https://raw.githubusercontent.com/binance/x/master/a.md",
        "authority": SourceAuthority.PRIMARY,
        "accessed": "2026-08-19",
        "regime": SourceRegime.DIGEST,
    }
    fields.update(overrides)
    return SourceObservation(**fields)  # type: ignore[arg-type]


def claim(status: SurfaceStatus = SurfaceStatus.SUPPORTED, **overrides: object) -> CapabilityRecord:
    """One valid capability claim, with fields replaced.

    Args:
        status: Which status.
        **overrides: Fields to change.

    Returns:
        The record.
    """
    fields: dict[str, object] = {
        "status": status,
        "evidence": EvidenceKind.DOCUMENTED,
        "source": "doc",
    }
    fields.update(overrides)
    return CapabilityRecord(**fields)  # type: ignore[arg-type]


def environment(
    name: EnvironmentName = LIVE, *, capital: bool = True, marker: str = ""
) -> EnvironmentRecord:
    """One valid environment record.

    Args:
        name: Which environment.
        capital: Whether real money is there.
        marker: What its hosts are spelled with.

    Returns:
        The record.
    """
    return EnvironmentRecord(
        family=SPOT,
        environment=name,
        semantics="What this environment guarantees.",
        capability=claim(),
        carries_real_capital=capital,
        host_marker=marker,
    )


def endpoint(**overrides: object) -> EndpointRecord:
    """One valid REST endpoint, with fields replaced.

    Args:
        **overrides: Fields to change.

    Returns:
        The record.
    """
    fields: dict[str, object] = {
        "family": SPOT,
        "environment": LIVE,
        "protocol": ProtocolKind.REST,
        "url": "https://api.binance.com/api",
        "transport": TransportKind.HTTPS,
        "request_encoding": EncodingKind.JSON,
        "response_encoding": EncodingKind.JSON,
        "auth": AuthMechanism.SIGNED,
        "capability": claim(),
    }
    fields.update(overrides)
    return EndpointRecord(**fields)  # type: ignore[arg-type]


def snapshot(**overrides: object) -> ApiRealitySnapshot:
    """One valid snapshot carrying a single live environment.

    Args:
        **overrides: Collections to change.

    Returns:
        The snapshot.
    """
    fields: dict[str, object] = {
        "sources": (source(),),
        "environments": (environment(),),
    }
    fields.update(overrides)
    return ApiRealitySnapshot(**fields)  # type: ignore[arg-type]


class TestValueTypes:
    """The four venue-named values are shapes, and carry no list of known members."""

    @pytest.mark.parametrize("slug", ["spot", "usds_m_futures", "a2"])
    def test_a_well_formed_slug_is_a_family(self, slug: str) -> None:
        """Any well-formed slug is a family, including one nobody has heard of.

        The registry must be able to record a product the venue adds tomorrow, which
        is the whole reason this is not an enumeration.
        """
        assert ProductFamily(slug).slug == slug

    @pytest.mark.parametrize("slug", ["", "a", "Spot", "usds-m", "spot futures", "x" * 49])
    def test_a_malformed_slug_is_refused(self, slug: str) -> None:
        """Case, hyphens, spaces and both length bounds are refused."""
        with pytest.raises(ValidationError):
            ProductFamily(slug)

    def test_a_permission_is_uppercase(self) -> None:
        """Permissions are spelled as the venue spells them, and lowercase is refused."""
        assert KeyPermission("FIX_API").spelling == "FIX_API"
        with pytest.raises(ValidationError):
            KeyPermission("fix_api")


class TestSourceObservation:
    """A claim about a venue with no source is not a claim."""

    def test_a_location_must_be_https(self) -> None:
        """An unencrypted or non-web location is refused."""
        with pytest.raises(ValidationError, match="must be https"):
            source(location="http://example.invalid/a.md")

    def test_a_malformed_access_date_is_refused(self) -> None:
        """The access date is what makes staleness visible, so its shape is checked."""
        with pytest.raises(ValidationError, match="ISO YYYY-MM-DD"):
            source(accessed="19-08-2026")

    def test_a_manual_source_cannot_carry_a_digest(self) -> None:
        """A source with no fetchable text form cannot honestly have been hashed."""
        with pytest.raises(ValidationError, match="cannot have been hashed"):
            source(regime=SourceRegime.MANUAL, digest="sha256:" + "a" * 64)

    def test_a_manual_source_is_not_refreshable(self) -> None:
        """Refreshability is a property of the source, not a choice."""
        assert not source(regime=SourceRegime.MANUAL).refreshable
        assert source(regime=SourceRegime.DIGEST).refreshable

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("md5:" + "a" * 64, id="wrong-algorithm"),
            pytest.param("sha256:" + "a" * 63, id="too-short"),
            pytest.param("sha256:" + "A" * 64, id="uppercase"),
            pytest.param("sha256:" + "z" * 64, id="not-hexadecimal"),
        ],
    )
    def test_a_malformed_digest_is_refused(self, value: str) -> None:
        """A digest that is not a lowercase sha256 hex string cannot be recorded."""
        with pytest.raises(ValidationError, match="digest"):
            source(digest=value)


class TestCapabilityRecord:
    """Six status words, and RESTRICTED must say what restricts it."""

    def test_restricted_must_name_its_condition(self) -> None:
        """A RESTRICTED with no condition is a second spelling of UNKNOWN."""
        with pytest.raises(ValidationError, match="must name the condition"):
            claim(SurfaceStatus.RESTRICTED)

    def test_only_restricted_may_carry_a_condition(self) -> None:
        """A condition on any other status means the status is wrong."""
        with pytest.raises(ValidationError, match="only RESTRICTED"):
            claim(SurfaceStatus.SUPPORTED, condition="an Ed25519 key")

    def test_unknown_is_not_usable(self) -> None:
        """UNKNOWN is not usable, and it is not UNSUPPORTED either.

        This is the distinction the whole phase exists for. Both refuse use; one
        means the documents say no and the other means they do not say. A registry
        that let `unknown` imply absence would let a later phase infer support from
        silence, which is the failure ADR-0086 names as characteristic.
        """
        assert not claim(SurfaceStatus.UNKNOWN).usable
        assert not claim(SurfaceStatus.UNSUPPORTED).usable
        assert claim(SurfaceStatus.UNKNOWN).status is not claim(SurfaceStatus.UNSUPPORTED).status

    def test_deprecated_is_still_usable_and_announced_is_not(self) -> None:
        """Going away is usable today; not yet arrived is not."""
        assert claim(SurfaceStatus.DEPRECATED).usable
        assert not claim(SurfaceStatus.ANNOUNCED).usable


class TestEndpointRecord:
    """An endpoint carries everything that decides whether it may be used."""

    def test_an_unencrypted_scheme_is_refused(self) -> None:
        """Every documented endpoint is encrypted, and the type will not hold otherwise."""
        with pytest.raises(ValidationError, match="scheme outside"):
            endpoint(url="ws://stream.binance.com")

    def test_a_fix_endpoint_must_require_tls_and_sni(self) -> None:
        """Omitting SNI produces *a* certificate rather than none, so it is required."""
        with pytest.raises(ValidationError, match="TLS and SNI"):
            endpoint(
                url="tcp+tls://fix-oe.binance.com:9000",
                transport=TransportKind.TCP_TLS,
                protocol=ProtocolKind.FIX_ORDER_ENTRY,
                request_encoding=EncodingKind.FIX_TEXT,
                response_encoding=EncodingKind.FIX_TEXT,
                port=9000,
                sni_required=False,
            )

    def test_a_fix_endpoint_must_record_its_port(self) -> None:
        """Three FIX ports share a host and differ only in encoding."""
        with pytest.raises(ValidationError, match="must record the port"):
            endpoint(
                url="tcp+tls://fix-oe.binance.com:9000",
                transport=TransportKind.TCP_TLS,
                protocol=ProtocolKind.FIX_ORDER_ENTRY,
                request_encoding=EncodingKind.FIX_TEXT,
                response_encoding=EncodingKind.FIX_TEXT,
                sni_required=True,
            )

    def test_the_two_encodings_are_independent(self) -> None:
        """One documented port takes FIX text and answers in FIX SBE.

        A single encoding per endpoint cannot describe it, which is why there are
        two fields. Measured rather than assumed: `docs/research/phase_033_sources.md`
        S-05.
        """
        hybrid = endpoint(
            url="tcp+tls://fix-oe.binance.com:9001",
            transport=TransportKind.TCP_TLS,
            protocol=ProtocolKind.FIX_ORDER_ENTRY,
            request_encoding=EncodingKind.FIX_TEXT,
            response_encoding=EncodingKind.FIX_SBE,
            port=9001,
            sni_required=True,
        )
        assert hybrid.request_encoding is not hybrid.response_encoding

    def test_a_trading_surface_cannot_be_unauthenticated(self) -> None:
        """An unauthenticated trading endpoint is not a thing the venue documents."""
        with pytest.raises(ValidationError, match="claims trading"):
            endpoint(auth=AuthMechanism.NONE, capabilities=(SurfaceCapability.TRADING,))

    def test_an_unknown_mechanism_also_refuses_trading(self) -> None:
        """Not knowing the requirement is not the same as there being none."""
        with pytest.raises(ValidationError, match="claims trading"):
            endpoint(auth=AuthMechanism.UNKNOWN, capabilities=(SurfaceCapability.TRADING,))

    def test_key_types_need_a_mechanism_to_belong_to(self) -> None:
        """A public endpoint declaring key types is describing something else."""
        with pytest.raises(ValidationError, match="needs no authentication"):
            endpoint(auth=AuthMechanism.NONE, key_types=(ApiKeyType.HMAC,))

    def test_the_port_is_part_of_the_identity(self) -> None:
        """Two FIX ports on one host are two endpoints, not one."""
        first = endpoint(
            url="tcp+tls://fix-oe.binance.com:9001",
            transport=TransportKind.TCP_TLS,
            protocol=ProtocolKind.FIX_ORDER_ENTRY,
            request_encoding=EncodingKind.FIX_TEXT,
            response_encoding=EncodingKind.FIX_SBE,
            port=9001,
            sni_required=True,
        )
        second = endpoint(
            url="tcp+tls://fix-oe.binance.com:9001",
            transport=TransportKind.TCP_TLS,
            protocol=ProtocolKind.FIX_ORDER_ENTRY,
            request_encoding=EncodingKind.FIX_SBE,
            response_encoding=EncodingKind.FIX_SBE,
            port=9002,
            sni_required=True,
        )
        assert first.identity != second.identity


class TestEnvironmentRecord:
    """An environment declares its guarantees and how its hosts are spelled."""

    def test_semantics_are_required(self) -> None:
        """An environment whose guarantees are unstated is the ADR-0006 assumption."""
        with pytest.raises(ValidationError, match="semantics"):
            EnvironmentRecord(
                family=SPOT,
                environment=LIVE,
                semantics="",
                capability=claim(),
                carries_real_capital=True,
            )

    def test_a_live_environment_declares_no_marker(self) -> None:
        """The live environment is the unmarked one."""
        with pytest.raises(ValidationError, match="the live environment is the unmarked one"):
            environment(capital=True, marker="demo")

    def test_a_paper_environment_must_declare_one(self) -> None:
        """Without a marker, an endpoint filed here cannot be told from a live one."""
        with pytest.raises(ValidationError, match="declares no host marker"):
            environment(PAPER, capital=False, marker="")


class TestSchemaVersion:
    """A lifecycle entry may not contradict its own state."""

    def test_a_retired_version_records_when(self) -> None:
        """Retirement with no date is a claim nobody could check."""
        with pytest.raises(ValidationError, match="records no retirement date"):
            SchemaVersion(
                family=SchemaFamilyName("spot_sbe"),
                environment=LIVE,
                schema_id=3,
                version=1,
                state=SchemaLifecycleState.RETIRED,
                released="2025-08-19",
                source="doc",
            )

    def test_the_latest_version_carries_no_end_date(self) -> None:
        """A current schema with a deprecation date is two claims at once."""
        with pytest.raises(ValidationError, match="carries a deprecation"):
            SchemaVersion(
                family=SchemaFamilyName("spot_sbe"),
                environment=LIVE,
                schema_id=3,
                version=5,
                state=SchemaLifecycleState.LATEST,
                released="2026-07-07",
                source="doc",
                deprecated="2026-07-07",
            )

    def test_the_label_is_the_venues_own_spelling(self) -> None:
        """The changelog writes `3:5`, so the registry does too."""
        entry = SchemaVersion(
            family=SchemaFamilyName("spot_sbe"),
            environment=LIVE,
            schema_id=3,
            version=5,
            state=SchemaLifecycleState.LATEST,
            released="2026-07-07",
            source="doc",
        )
        assert entry.label == "3:5"


class TestSnapshot:
    """The snapshot refuses a registry that contradicts itself."""

    def test_a_repeated_identity_is_refused(self) -> None:
        """Two rows with one identity make every lookup ambiguous."""
        with pytest.raises(ValidationError, match="declared more than once"):
            snapshot(
                products=(
                    ProductProfile(
                        family=SPOT, scope=ProductScope.TRADING, title="A", capability=claim()
                    ),
                    ProductProfile(
                        family=SPOT, scope=ProductScope.TRADING, title="B", capability=claim()
                    ),
                )
            )

    def test_a_citation_must_name_a_declared_source(self) -> None:
        """Provenance that points nowhere is worse than none, because it reads as some."""
        with pytest.raises(ValidationError, match="not declared"):
            snapshot(
                products=(
                    ProductProfile(
                        family=SPOT,
                        scope=ProductScope.TRADING,
                        title="A",
                        capability=claim(source="absent"),
                    ),
                )
            )

    def test_two_current_schemas_are_refused(self) -> None:
        """At most one version per family and environment may be the latest."""
        entries = tuple(
            SchemaVersion(
                family=SchemaFamilyName("spot_sbe"),
                environment=LIVE,
                schema_id=3,
                version=version,
                state=SchemaLifecycleState.LATEST,
                released="2026-07-07",
                source="doc",
            )
            for version in (4, 5)
        )
        with pytest.raises(ValidationError, match="as the latest schema"):
            snapshot(schemas=entries)

    def test_an_endpoint_for_an_unsupported_surface_is_refused(self) -> None:
        """A surface documented as absent cannot have an address."""
        with pytest.raises(ValidationError, match="recorded as unsupported"):
            snapshot(
                surfaces=(
                    SurfaceRecord(
                        family=SPOT,
                        protocol=ProtocolKind.REST,
                        capability=claim(SurfaceStatus.UNSUPPORTED),
                    ),
                ),
                endpoints=(endpoint(),),
            )

    def test_a_paper_host_filed_as_live_is_refused(self) -> None:
        """The failure ADR-0006 calls the dangerous one, refused structurally."""
        with pytest.raises(ValidationError, match="spelled like"):
            snapshot(
                environments=(environment(), environment(PAPER, capital=False, marker="testnet")),
                endpoints=(endpoint(url="https://testnet.binance.vision/api"),),
            )

    def test_a_live_host_filed_as_paper_is_refused(self) -> None:
        """And the reverse, which is the one that loses money."""
        with pytest.raises(ValidationError, match="does not contain"):
            snapshot(
                environments=(environment(PAPER, capital=False, marker="testnet"),),
                endpoints=(endpoint(environment=PAPER, url="https://api.binance.com/api"),),
            )

    def test_an_endpoint_in_an_undeclared_environment_is_refused(self) -> None:
        """An endpoint whose environment nobody described cannot be judged."""
        with pytest.raises(ValidationError, match="does not declare"):
            snapshot(endpoints=(endpoint(environment=PAPER),))

    def test_an_absent_entry_is_not_an_unknown_one(self) -> None:
        """`None` and a recorded UNKNOWN are different answers.

        ADR-0087's seventh decision. Both refuse; one means the registry was never
        told and the other means the documents do not say, and a caller that cannot
        tell them apart cannot report which.
        """
        recorded = snapshot(
            products=(
                ProductProfile(
                    family=ProductFamily("options"),
                    scope=ProductScope.TRADING,
                    title="Options",
                    capability=claim(SurfaceStatus.UNKNOWN),
                ),
            )
        )
        assert recorded.product(ProductFamily("wallet")) is None
        found = recorded.product(ProductFamily("options"))
        assert found is not None
        assert found.capability.status is SurfaceStatus.UNKNOWN

    def test_status_counts_include_the_zeroes(self) -> None:
        """An absent key would read as an absent question."""
        assert set(snapshot().status_counts()) == {item.value for item in SurfaceStatus}


class TestDiff:
    """Two snapshots, compared without a network and without a clock."""

    def test_a_snapshot_does_not_differ_from_itself(self) -> None:
        """Reflexivity, which is what makes an empty diff mean something."""
        assert diff(snapshot(), snapshot()).empty

    def test_a_lost_endpoint_is_breaking(self) -> None:
        """Something GLOBIN could rely on stopped being available."""
        before = snapshot(endpoints=(endpoint(),))
        found = diff(before, snapshot())
        assert [item.drift for item in found.findings] == [DriftClass.ENDPOINT_REMOVED]
        assert found.findings[0].risk is DriftRisk.BREAKING

    def test_a_changed_key_rule_is_security_relevant(self) -> None:
        """A changed key rule is checked against what GLOBIN holds before anything else."""
        before = snapshot(endpoints=(endpoint(key_types=(ApiKeyType.HMAC,)),))
        after = snapshot(endpoints=(endpoint(key_types=(ApiKeyType.ED25519,)),))
        found = diff(before, after)
        assert found.findings[0].drift is DriftClass.KEY_TYPE_CHANGED
        assert found.findings[0].risk is DriftRisk.SECURITY_RELEVANT

    def test_a_changed_mechanism_is_security_relevant(self) -> None:
        """Authentication moving is its own class, not a generic endpoint change."""
        before = snapshot(endpoints=(endpoint(auth=AuthMechanism.API_KEY),))
        after = snapshot(endpoints=(endpoint(auth=AuthMechanism.SIGNED),))
        found = diff(before, after)
        assert found.at_risk(DriftRisk.SECURITY_RELEVANT)[0].drift is DriftClass.AUTH_CHANGED

    def test_unknown_becoming_supported_is_informational(self) -> None:
        """Gaining a capability breaks nothing."""
        before = snapshot(
            surfaces=(
                SurfaceRecord(
                    family=SPOT, protocol=ProtocolKind.REST, capability=claim(SurfaceStatus.UNKNOWN)
                ),
            )
        )
        after = snapshot(
            surfaces=(SurfaceRecord(family=SPOT, protocol=ProtocolKind.REST, capability=claim()),)
        )
        found = diff(before, after)
        assert found.findings[0].risk is DriftRisk.INFORMATIONAL
        assert not found.demands_attention

    def test_supported_becoming_unknown_is_breaking(self) -> None:
        """Losing knowledge about something relied on is not informational.

        The entry most likely to be argued with, and the argument is that a registry
        which treated a capability becoming undescribable as news would decay quietly.
        """
        before = snapshot(
            surfaces=(SurfaceRecord(family=SPOT, protocol=ProtocolKind.REST, capability=claim()),)
        )
        after = snapshot(
            surfaces=(
                SurfaceRecord(
                    family=SPOT, protocol=ProtocolKind.REST, capability=claim(SurfaceStatus.UNKNOWN)
                ),
            )
        )
        assert diff(before, after).findings[0].risk is DriftRisk.BREAKING

    def test_supported_becoming_deprecated_needs_review(self) -> None:
        """A deprecation is a deadline, not a closed door."""
        before = snapshot(
            surfaces=(SurfaceRecord(family=SPOT, protocol=ProtocolKind.REST, capability=claim()),)
        )
        after = snapshot(
            surfaces=(
                SurfaceRecord(
                    family=SPOT,
                    protocol=ProtocolKind.REST,
                    capability=claim(SurfaceStatus.DEPRECATED),
                ),
            )
        )
        assert diff(before, after).findings[0].risk is DriftRisk.REVIEW_REQUIRED

    def test_a_changed_source_digest_needs_review_and_no_more(self) -> None:
        """Nothing here knows what changed inside the document.

        That is the whole reason the digest regime exists, so the risk stops at
        review-required rather than guessing at a severity.
        """
        after = snapshot(sources=(source(digest="sha256:" + "b" * 64),))
        found = diff(snapshot(), after)
        assert found.findings[0].drift is DriftClass.SOURCE_CHANGED
        assert found.findings[0].risk is DriftRisk.REVIEW_REQUIRED

    def test_a_retired_schema_is_breaking_and_a_deprecated_one_is_not(self) -> None:
        """Six months of support is the difference between a deadline and a wall."""

        def entry(state: SchemaLifecycleState, **extra: str) -> SchemaVersion:
            return SchemaVersion(
                family=SchemaFamilyName("spot_sbe"),
                environment=LIVE,
                schema_id=3,
                version=1,
                state=state,
                released="2025-08-19",
                source="doc",
                **extra,
            )

        started = snapshot(schemas=(entry(SchemaLifecycleState.LATEST),))
        deprecated = snapshot(
            schemas=(entry(SchemaLifecycleState.DEPRECATED, deprecated="2025-12-18"),)
        )
        retired = snapshot(
            schemas=(
                entry(
                    SchemaLifecycleState.RETIRED,
                    deprecated="2025-12-18",
                    retired="2026-06-29",
                ),
            )
        )
        assert diff(started, deprecated).findings[0].risk is DriftRisk.REVIEW_REQUIRED
        assert diff(deprecated, retired).findings[0].risk is DriftRisk.BREAKING

    def test_a_finding_needs_something_to_act_on(self) -> None:
        """A finding with no subject or summary is noise."""
        with pytest.raises(ValidationError):
            DriftFinding(
                drift=DriftClass.SOURCE_ADDED,
                risk=DriftRisk.INFORMATIONAL,
                subject="",
                summary="something",
            )

    def test_an_empty_diff_demands_nothing(self) -> None:
        """The base case, asserted so the property is not merely implied."""
        assert ApiRealityDiff().empty
        assert not ApiRealityDiff().demands_attention


class TestDiffCoverage:
    """Every drift class the comparison can produce, made to produce it.

    A classifier is only worth its table if each branch has been seen to fire.
    These are the additions and removals the transition tests above cannot reach,
    because those hold the shape fixed and move one status.
    """

    def test_a_new_source_is_informational_and_a_lost_one_needs_review(self) -> None:
        """A source appearing is news; one vanishing is a claim losing its footing."""
        richer = snapshot(sources=(source(), source("second")))
        assert diff(snapshot(), richer).findings[0].drift is DriftClass.SOURCE_ADDED
        lost = diff(richer, snapshot())
        assert lost.findings[0].drift is DriftClass.SOURCE_REMOVED
        assert lost.findings[0].risk is DriftRisk.REVIEW_REQUIRED

    def test_a_product_appearing_and_vanishing_are_different_risks(self) -> None:
        """Gaining a family breaks nothing; losing one breaks whatever used it."""
        listed = snapshot(
            products=(
                ProductProfile(
                    family=SPOT, scope=ProductScope.TRADING, title="Spot", capability=claim()
                ),
            )
        )
        assert diff(snapshot(), listed).findings[0].risk is DriftRisk.INFORMATIONAL
        gone = diff(listed, snapshot())
        assert gone.findings[0].drift is DriftClass.PRODUCT_REMOVED
        assert gone.findings[0].risk is DriftRisk.BREAKING

    def test_a_surface_appearing_and_vanishing_are_classified(self) -> None:
        """A protocol a product stops exposing is a capability GLOBIN loses."""
        listed = snapshot(
            surfaces=(SurfaceRecord(family=SPOT, protocol=ProtocolKind.REST, capability=claim()),)
        )
        assert diff(snapshot(), listed).findings[0].drift is DriftClass.SURFACE_ADDED
        assert diff(listed, snapshot()).findings[0].drift is DriftClass.SURFACE_REMOVED

    def test_an_environment_appearing_and_vanishing_are_classified(self) -> None:
        """An environment a product stops offering cannot be routed to."""
        both = snapshot(
            environments=(environment(), environment(PAPER, capital=False, marker="testnet"))
        )
        assert diff(snapshot(), both).findings[0].drift is DriftClass.ENVIRONMENT_ADDED
        assert diff(both, snapshot()).findings[0].drift is DriftClass.ENVIRONMENT_REMOVED

    def test_a_new_schema_version_is_informational(self) -> None:
        """A published schema is news until it displaces something."""
        listed = snapshot(
            schemas=(
                SchemaVersion(
                    family=SchemaFamilyName("spot_sbe"),
                    environment=LIVE,
                    schema_id=3,
                    version=5,
                    state=SchemaLifecycleState.LATEST,
                    released="2026-07-07",
                    source="doc",
                ),
            )
        )
        found = diff(snapshot(), listed)
        assert found.findings[0].drift is DriftClass.SCHEMA_ADDED
        assert found.findings[0].risk is DriftRisk.INFORMATIONAL

    def test_a_changed_encoding_needs_review(self) -> None:
        """How a surface must be spoken to changed, which is not a status move."""
        before = snapshot(endpoints=(endpoint(),))
        after = snapshot(endpoints=(endpoint(response_encoding=EncodingKind.SBE),))
        found = diff(before, after)
        assert found.findings[0].drift is DriftClass.ENDPOINT_CHANGED
        assert found.findings[0].risk is DriftRisk.REVIEW_REQUIRED

    def test_an_endpoint_with_no_keys_summarises_as_none(self) -> None:
        """The empty case of the key summary, which a public endpoint reaches."""
        before = snapshot(endpoints=(endpoint(auth=AuthMechanism.NONE),))
        after = snapshot(endpoints=(endpoint(auth=AuthMechanism.API_KEY),))
        assert diff(before, after).findings[0].drift is DriftClass.AUTH_CHANGED

    def test_findings_can_be_selected_by_risk(self) -> None:
        """A reader triaging a diff asks for one level at a time."""
        before = snapshot(endpoints=(endpoint(key_types=(ApiKeyType.HMAC,)),))
        found = diff(before, snapshot())
        assert found.at_risk(DriftRisk.BREAKING)
        assert not found.at_risk(DriftRisk.SECURITY_RELEVANT)
        assert found.demands_attention


class TestBounds:
    """Every published collection is bounded, so a malformed document cannot grow one."""

    def test_a_snapshot_refuses_more_products_than_its_bound(self) -> None:
        """An unbounded document is one whose size depends on nothing anybody watches."""
        many = tuple(
            ProductProfile(
                family=ProductFamily(f"family_{index:03d}"),
                scope=ProductScope.TRADING,
                title="A product",
                capability=claim(),
            )
            for index in range(MAX_PRODUCTS + 1)
        )
        with pytest.raises(ValidationError, match="the limit is"):
            snapshot(products=many)

    def test_a_diff_refuses_more_findings_than_its_bound(self) -> None:
        """Two unrelated snapshots would otherwise be bounded by their product."""
        one = DriftFinding(
            drift=DriftClass.SOURCE_ADDED,
            risk=DriftRisk.INFORMATIONAL,
            subject="source/a",
            summary="a source appeared",
        )
        with pytest.raises(ValidationError, match="the limit is"):
            ApiRealityDiff(findings=(one,) * (MAX_FINDINGS + 1))
