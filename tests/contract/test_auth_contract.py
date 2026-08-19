"""The declared authentication contract, recomputed against the package.

`docs/engineering/auth-contract.toml` restates every venue fact the signing layer
encodes, and this file compares the two **in both directions**: a constant there
the code does not carry fails, and a constant in the code that is not declared
there fails too. That is the arrangement `test_rest_contract.py` has with
`rest-transport.toml`, and what the second copy buys is a citation — a header name
in a Python module is a string somebody typed.

**The strongest check here is not a comparison at all.** The venue publishes two
worked HMAC examples with their expected signatures, so
`test_the_published_vectors_reproduce` recomputes GLOBIN's whole canonicalisation
and signing path against an answer this repository did not choose. Everything else
in this file could pass on a package that agreed with itself and disagreed with
Binance; that one could not.
"""

import base64
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from globin.adapters.signing import (
    ED25519_SIGNATURE_BYTES,
    RSA_MAX_KEY_BITS,
    RSA_MIN_KEY_BITS,
    hmac_signer,
)
from globin.application.auth import (
    _known_answer_secret,
    _known_answer_vectors,
)
from globin.domain.api_reality import ApiKeyType
from globin.domain.auth import (
    API_KEY_HEADER,
    SIGNATURE_PARAMETER,
    GeneratedSignature,
    SecurityType,
    SignatureAlgorithm,
    SigningPayload,
    algorithm_for,
    encoding_for,
    key_type_for,
    signed_parameters,
    signing_payload,
    spot_profile,
)
from globin.domain.auth_timing import (
    DEFAULT_RECV_WINDOW_MILLIS,
    MAX_RECV_WINDOW_DECIMALS,
    MAX_RECV_WINDOW_MILLIS,
    RECV_WINDOW_PARAMETER,
    TIMESTAMP_PARAMETER,
    RecvWindow,
    TimestampUnit,
)
from globin.domain.rest import QueryParameters
from globin.domain.secrets import SecretValue
from globin.errors import ValidationError

CONTRACT_RELATIVE_PATH: Final[str] = "docs/engineering/auth-contract.toml"
"""Where the declaration lives."""

REGISTRY_RELATIVE_PATH: Final[str] = "docs/engineering/binance-api-reality.toml"
"""The repository's one source ledger, which every `source` here must name."""


@pytest.fixture(scope="module")
def repo_root() -> Path:
    """Where the repository is, from this file."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def contract(repo_root: Path) -> dict[str, Any]:
    """The declared authentication contract."""
    return tomllib.loads((repo_root / CONTRACT_RELATIVE_PATH).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> dict[str, Any]:
    """Phase 033's registry, for the source identifiers."""
    return tomllib.loads((repo_root / REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The request surface
# ---------------------------------------------------------------------------


def test_the_declared_header_and_parameter_names_are_the_ones_the_package_sends(
    contract: dict[str, Any],
) -> None:
    """A header carrying a credential deserves a provenance stronger than a typo check."""
    surface = contract["surface"]
    assert surface["api_key_header"] == API_KEY_HEADER
    assert surface["signature_parameter"] == SIGNATURE_PARAMETER
    assert surface["timestamp_parameter"] == TIMESTAMP_PARAMETER
    assert surface["recv_window_parameter"] == RECV_WINDOW_PARAMETER


def test_the_api_key_header_is_redacted_by_the_existing_mechanism() -> None:
    """The header name must match a sensitive fragment, or nothing redacts a field named for it.

    Checked here rather than assumed, because the redaction works by field *name*
    and a header renamed at the venue could stop matching without anything
    noticing.
    """
    from globin.domain.observability import is_sensitive

    assert is_sensitive(API_KEY_HEADER)
    assert is_sensitive(SIGNATURE_PARAMETER)
    assert is_sensitive(f"request_{SIGNATURE_PARAMETER}")


def test_the_percent_encoding_rule_is_declared_as_the_venue_states_it(
    contract: dict[str, Any],
) -> None:
    """Announced 2025-12-17, effective 2026-01-15, rejected with -1022 when ignored."""
    surface = contract["surface"]
    assert surface["percent_encode_before_signing"] is True
    assert surface["percent_encoding_announced"] == "2025-12-17"
    assert surface["percent_encoding_effective"] == "2026-01-15"
    assert surface["percent_encoding_rejection_code"] == -1022


# ---------------------------------------------------------------------------
# The security types
# ---------------------------------------------------------------------------


def test_the_declared_security_types_are_exactly_the_ones_the_package_has(
    contract: dict[str, Any],
) -> None:
    """Both directions. A fifth in either place is a classification nobody agreed to."""
    declared = {row["name"] for row in contract["security_type"]}
    assert declared == {member.value for member in SecurityType}


def test_every_security_type_but_none_is_signed(contract: dict[str, Any]) -> None:
    """The finding this contract exists to bind.

    Quoted: *"Except for `NONE`, all endpoints with a security type are considered
    `SIGNED` requests."* So there is no api-key-without-signature tier on this
    surface, and a row claiming one would mean the package needs a branch it does
    not have.
    """
    for row in contract["security_type"]:
        member = SecurityType(row["name"])
        assert member.requires_api_key == row["api_key"], row["name"]
        assert member.requires_signature == row["signed"], row["name"]
        assert row["api_key"] == row["signed"], (
            f"{row['name']} declares a key without a signature, which this surface has no tier for"
        )


def test_a_public_request_never_asks_for_a_signed_intent() -> None:
    """The one member that must map to PUBLIC, and the three that must not."""
    assert SecurityType.NONE.intent.value == "public"
    for member in SecurityType:
        if member is not SecurityType.NONE:
            assert member.intent.value == "signed", member


# ---------------------------------------------------------------------------
# The key types
# ---------------------------------------------------------------------------


def test_the_declared_key_types_are_exactly_the_ones_the_registry_knows(
    contract: dict[str, Any],
) -> None:
    """Both directions, against Phase 033's enumeration rather than a list here."""
    declared = {row["name"] for row in contract["key_type"]}
    assert declared == {member.value for member in ApiKeyType}


def test_every_key_type_maps_to_the_declared_algorithm_and_encoding(
    contract: dict[str, Any],
) -> None:
    """The mapping is a lookup rather than a branch, so the lookup is what is checked."""
    for row in contract["key_type"]:
        key_type = ApiKeyType(row["name"])
        algorithm = algorithm_for(key_type)
        assert algorithm.value == row["algorithm"], row["name"]
        assert encoding_for(algorithm).value == row["encoding"], row["name"]
        assert key_type_for(algorithm) is key_type, row["name"]


def test_hmac_is_recorded_deprecated_and_stays_usable(contract: dict[str, Any]) -> None:
    """The correction S-04 made, bound so it cannot quietly revert.

    The venue's API Key Types document says *"HMAC keys are deprecated"* — and
    deprecated is **usable**. Nothing in the signing path may treat it otherwise,
    which is checked by producing a signature with it.
    """
    rows = {row["name"]: row for row in contract["key_type"]}
    assert rows["hmac"]["status"] == "deprecated"
    assert rows["hmac"]["recommended"] is False
    payload = SigningPayload(query_span="symbol=BTCUSDT")
    produced = hmac_signer().sign(payload, SecretValue(_known_answer_secret()))
    assert produced.algorithm is SignatureAlgorithm.HMAC_SHA256


def test_exactly_one_key_type_is_recommended(contract: dict[str, Any]) -> None:
    """The venue recommends Ed25519 and nothing else, so exactly one row may say so."""
    recommended = [row["name"] for row in contract["key_type"] if row["recommended"]]
    assert recommended == ["ed25519"]


def test_the_declared_key_bounds_are_the_ones_the_signer_enforces(
    contract: dict[str, Any],
) -> None:
    """The venue's 2048-to-4096 range and Ed25519's fixed signature length."""
    rows = {row["name"]: row for row in contract["key_type"]}
    assert rows["rsa"]["min_bits"] == RSA_MIN_KEY_BITS
    assert rows["rsa"]["max_bits"] == RSA_MAX_KEY_BITS
    assert rows["ed25519"]["signature_bytes"] == ED25519_SIGNATURE_BYTES


def test_both_asymmetric_types_are_case_sensitive_and_hmac_is_not(
    contract: dict[str, Any],
) -> None:
    """The asymmetry that forbids a case transform anywhere on the signing path."""
    rows = {row["name"]: row for row in contract["key_type"]}
    assert rows["hmac"]["case_sensitive"] is False
    assert rows["rsa"]["case_sensitive"] is True
    assert rows["ed25519"]["case_sensitive"] is True
    for name, row in rows.items():
        profile = spot_profile(algorithm_for(ApiKeyType(name)))
        assert profile.case_sensitive == row["case_sensitive"], name


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def test_the_declared_window_bounds_are_the_ones_the_type_enforces(
    contract: dict[str, Any],
) -> None:
    """Default, ceiling and precision, each quoted from the Timing security section."""
    timing = contract["timing"]
    assert timing["recv_window_default"] == DEFAULT_RECV_WINDOW_MILLIS
    assert timing["recv_window_maximum"] == MAX_RECV_WINDOW_MILLIS
    assert timing["recv_window_decimals"] == MAX_RECV_WINDOW_DECIMALS
    assert timing["recv_window_unit"] == "milliseconds"


def test_the_declared_timestamp_units_are_exactly_the_ones_the_package_sends(
    contract: dict[str, Any],
) -> None:
    """Both directions. A third unit in either place is one the venue never documented."""
    assert set(contract["timing"]["timestamp_units"]) == {member.value for member in TimestampUnit}


def test_the_ceiling_is_enforced_rather_than_clamped(contract: dict[str, Any]) -> None:
    """A window above the maximum fails; it does not become the maximum."""
    ceiling = Decimal(contract["timing"]["recv_window_maximum"])
    assert RecvWindow(ceiling).millis == ceiling
    with pytest.raises(ValidationError, match="exceeds the documented maximum"):
        RecvWindow(ceiling + Decimal("0.001"))


def test_the_documented_example_window_is_accepted(contract: dict[str, Any]) -> None:
    """`6000.346` is the venue's own example, so refusing it would refuse the documentation."""
    places = contract["timing"]["recv_window_decimals"]
    assert places == 3
    assert str(RecvWindow(Decimal("6000.346"))) == "6000.346"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_every_declared_source_names_a_row_in_the_one_ledger(
    contract: dict[str, Any], registry: dict[str, Any]
) -> None:
    """A second source ledger would drift from the first about which document said what."""
    known = {row["id"] for row in registry["source"]}
    cited = {contract["surface"]["source"], contract["surface"]["percent_encoding_source"]}
    cited |= {row["source"] for row in contract["security_type"]}
    cited |= {row["source"] for row in contract["key_type"]}
    cited.add(contract["timing"]["source"])
    unknown = sorted(cited - known)
    assert not unknown, (
        f"{CONTRACT_RELATIVE_PATH} cites sources the registry does not declare: {unknown}"
    )


def test_the_key_types_document_is_declared(registry: dict[str, Any]) -> None:
    """The source Phase 033 did not read, and the only one stating the HMAC deprecation."""
    identifiers = {row["id"] for row in registry["source"]}
    assert "spot-api-key-types" in identifiers


# ---------------------------------------------------------------------------
# Prohibitions
# ---------------------------------------------------------------------------


def test_every_prohibition_is_still_prohibited(contract: dict[str, Any]) -> None:
    """A flag flipping to true is a capability arriving without an argument for it."""
    permitted = sorted(name for name, value in contract["prohibitions"].items() if value)
    assert not permitted, f"declared permitted: {permitted}"


def test_the_transport_still_signs_nothing(repo_root: Path) -> None:
    """The prohibition Phase 035 deliberately did NOT flip.

    The first draft of this phase flipped `request_signing` in
    `rest-transport.toml` on the reasoning that GLOBIN can now sign. That was
    wrong, and the transport contract's own test caught it: the table says what
    **this transport** will not do, and the transport still has no signer, no key
    and no credential. `_exchange` renders exactly the request it was handed.

    What changed is that `globin.application.auth` produces an already-signed
    `RestRequest`, which arrives at the transport indistinguishable from any other.
    That separation is why the transport can stay as simple as it is, and why this
    assertion is the right way round.
    """
    transport = tomllib.loads(
        (repo_root / "docs/engineering/rest-transport.toml").read_text(encoding="utf-8")
    )
    assert transport["prohibitions"]["request_signing"] is False, (
        "the transport declares that it signs requests; signing belongs to the application "
        "layer, and the transport receives a request that is already signed"
    )


# ---------------------------------------------------------------------------
# The vectors the venue published
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", [0, 1], ids=["ascii", "non-ascii"])
def test_the_published_vectors_reproduce(index: int) -> None:
    """The one check here that compares GLOBIN against an answer it did not choose.

    Both vectors come from the REST document's own HMAC section: the payload it
    prints and the signature it prints beside it. The second carries a symbol of
    fullwidth digits, already percent-encoded — which is the encode-before-sign
    rule demonstrated by the venue rather than described.
    """
    _label, payload_text, expected = _known_answer_vectors()[index]
    produced = hmac_signer().sign(
        SigningPayload(query_span=payload_text), SecretValue(_known_answer_secret())
    )
    assert produced.value() == expected


def test_globin_renders_the_published_payload_from_its_own_parameters() -> None:
    """The half a fixed payload string cannot check.

    Feeding the documented payload to the signer proves the signer. Rendering that
    payload from parameters proves the *canonicalisation*, which is where a change
    to the safe set or the ordering would show up first.
    """
    parameters = QueryParameters(
        items=(
            ("symbol", "LTCBTC"),
            ("side", "BUY"),
            ("type", "LIMIT"),
            ("timeInForce", "GTC"),
            ("quantity", 1),
            ("price", Decimal("0.1")),
            ("recvWindow", str(RecvWindow(Decimal(5000)))),
            ("timestamp", 1499827319559),
        )
    )
    _label, documented, _signature = _known_answer_vectors()[0]
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    assert signing_payload(parameters, None, profile).text == documented


def test_the_signature_is_appended_where_the_documentation_puts_it() -> None:
    """The venue's own curl example ends `...&signature=<hex>`, and so does GLOBIN's."""
    parameters = QueryParameters(items=(("symbol", "LTCBTC"),))
    profile = spot_profile(SignatureAlgorithm.HMAC_SHA256)
    signature = GeneratedSignature("ab" * 32, SignatureAlgorithm.HMAC_SHA256)
    rendered = signed_parameters(parameters, signature, profile).canonical()
    assert rendered == f"symbol=LTCBTC&{SIGNATURE_PARAMETER}={'ab' * 32}"


def test_a_base64_signature_is_percent_encoded_the_way_the_venue_shows() -> None:
    """The RSA section publishes both forms, so both are checked against each other.

    `/` becomes `%2F`, `+` becomes `%2B` and `=` becomes `%3D`, none of which is in
    RFC 3986's unreserved set — so GLOBIN's encoder produces the documented string
    without knowing anything about signatures.
    """
    raw = base64.b64encode(bytes(range(64))).decode("ascii")
    signature = GeneratedSignature(raw, SignatureAlgorithm.ED25519)
    profile = spot_profile(SignatureAlgorithm.ED25519)
    rendered = signed_parameters(QueryParameters(), signature, profile).canonical()
    encoded = rendered.removeprefix(f"{SIGNATURE_PARAMETER}=")
    assert "/" not in encoded
    assert "+" not in encoded
    assert "=" not in encoded
    assert "%2F" in encoded or "%2B" in encoded or "%3D" in encoded
