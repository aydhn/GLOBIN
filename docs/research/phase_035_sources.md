# Phase 035 — Source Ledger

Every external fact the authentication and signing layer encodes, where it was
read, and what it changed about the implementation.

Eight entries. **Two of them changed a decision that had already been taken**, and
one of those was a correction to this phase's own plan: the plan recorded that no
HMAC deprecation is announced, which was true of the changelog and of
`rest-api.md` and false of the document `rest-api.md` links to. The other is a
**defect in the official documentation** found by arithmetic rather than by
reading — every worked Ed25519 example the REST document publishes is an RSA
output, one of them not even valid base64.

Every document below was fetched raw and grepped locally. Nothing here was read
through a summarising intermediary, because the first attempt at this ledger did
exactly that and returned the wrong date for S-03 and the wrong verdict for S-04.

---

## Drift check against Phases 033 and 034

Four of the documents below were already recorded in
[`binance-api-reality.toml`](../engineering/binance-api-reality.toml). Their
digests were recomputed on access and compared:

| Source | Recorded digest | On access |
|---|---|---|
| `spot-rest` | `sha256:49ea6809…427999` | **unchanged** |
| `spot-changelog` | `sha256:e6da6a7b…ef7681` | **unchanged** |
| `spot-testnet` | `sha256:f6ff938f…b60be1` | **unchanged** |
| `spot-demo` | `sha256:6b07adb3…09073d` | **unchanged** |

No source this phase depends on has moved since Phase 033 read it, so the registry
required no drift acknowledgement and none was written.

---

### S-01 — Binance Spot REST API, Request Security

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. Already declared as `spot-rest`.

**Digest at access:** `sha256:49ea6809243fc7fb426e07f2fe662097736c7bb405bd2da5eef637d715427999`

**What it establishes**, quoted:

- The security-type table has **four** rows: `NONE` ("Public market data"),
  `TRADE`, `USER_DATA`, `USER_STREAM`.
- *"Except for `NONE`, all endpoints with a security type are considered `SIGNED`
  requests (i.e. including a `signature`)."*
- *"Secure endpoints require a valid API key to be specified and authenticated."*
  The header is `X-MBX-APIKEY`.
- *"`SIGNED` endpoints require an additional parameter, `signature`, to be sent in
  the `query string` or `request body`."*
- *"The signature payload of your request is the query string concatenated without
  separator to the HTTP body. Any non-ASCII character must be percent-encoded
  before signing."* — stated identically in all three of the HMAC, RSA and Ed25519
  sections.
- Case sensitivity: *"**HMAC:** Signatures generated using HMAC are **not
  case-sensitive**"*; *"**RSA:** Signatures generated using RSA are
  **case-sensitive**"*; *"**Ed25519:** Signatures generated using Ed25519 are also
  **case-sensitive**"*. And for HMAC specifically: *"Note that `secretKey` and the
  payload are **case-sensitive**, while the resulting signature value is
  case-insensitive."*

**Implication for GLOBIN — this one changed the type design.** There is **no
API-key-only tier on Spot REST**. `USER_STREAM` is signed like the other two, so
`SecurityType.requires_signature` is simply *not `NONE`* and there is no branch
for a key-without-signature request.
[`RequestSecurityIntent.API_KEY`](../../src/globin/domain/rest.py) remains a member
of Phase 034's enum because the registry's vocabulary spans more than REST, but no
Spot REST endpoint can produce it — the registry records `auth = "signed"` or
`auth = "none"` on all ten REST rows and `api_key` on none. That is stated rather
than branched on.

The case-sensitivity asymmetry is why `GeneratedSignature` applies **no** case
normalisation. Lower-casing an HMAC signature would be harmless and lower-casing
an RSA or Ed25519 one would silently invalidate every request, so the safe rule is
to normalise nothing and let each signer's own encoding stand.

---

### S-02 — Binance Spot REST API, Timing security

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md
— the same document as S-01, section *Timing security*

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary.

**What it establishes**, quoted:

- *"`SIGNED` requests also require a `timestamp` parameter which should be the
  current timestamp either in milliseconds or microseconds."*
- *"An additional optional parameter, `recvWindow`, specifies for how long the
  request stays valid and **may only be specified in milliseconds**."*
- *"`recvWindow` supports up to three decimal places of precision (e.g., 6000.346)
  so that microseconds may be specified."*
- *"If `recvWindow` is not sent, **it defaults to 5000 milliseconds**."*
- *"Maximum `recvWindow` is 60000 milliseconds."*
- *"**It is recommended to use a small recvWindow of 5000 or less! The max cannot
  go beyond 60,000!**"*
- The processing rule, verbatim:
  `if (timestamp < (serverTime + 1 second) && (serverTime - timestamp) <= recvWindow)`.

**Implication for GLOBIN.** `RecvWindow` carries a `Decimal`, not a `float` and not
an `int`. Three decimal places of a millisecond is a value a binary float cannot
hold exactly, and `docs/VALUE_TYPES_POLICY.md` already forbids a float anywhere
near a quantity the venue compares against a bound. The configuration key is read
as **text** and parsed to `Decimal` for the same reason: a TOML float would lose
the third place before the value ever reached a type that could refuse it.

The processing rule is recorded and **not implemented**. It names `serverTime`,
which GLOBIN does not have — Phase 040 owns clock synchronisation, and a transport
that estimated `serverTime` here would be building it early. What this phase takes
from the rule is the reason the ceiling matters: a large `recvWindow` widens the
window in which a stale request is still accepted, which is why nothing in this
phase lets an operator raise it as a remedy for a clock problem.

---

### S-03 — Binance Spot CHANGELOG, the percent-encoding change

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/CHANGELOG.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. Already declared as `spot-changelog`.

**Digest at access:** `sha256:e6da6a7bb729ec5b1aa6d3c97684bb2a1e4d3a64231b007edea42c6cceef7681`

**What it establishes.** Under the heading **`### 2025-12-17`**, subheading
*Time-sensitive Notice*, quoted in full:

> **The following change to REST API will occur at approximately 2026-01-15 07:00
> UTC:** When calling endpoints that require signatures, percent-encode payloads
> before computing signatures. Requests that do not follow this order will be
> rejected with `-1022 INVALID_SIGNATURE`. Please review and update your signing
> logic accordingly. This has now been enabled on SPOT Testnet

And under **`### 2025-12-18`**: assets `这是测试币` and `456` and symbol
`这是测试币456` were added to Spot Testnet *"for testing endpoints/methods with a
Unicode symbol"*.

**Two dates, and they are different facts.** 2025-12-17 is when the change was
**announced**; 2026-01-15 07:00 UTC is when it took effect in production, and
testnet already had it at announcement. Today is 2026-08-19, so the behaviour is
live everywhere and there is no transitional regime to support.

**Implication for GLOBIN — none, and that is the result.** GLOBIN signs the string
`QueryParameters.canonical()` renders, and that string is already percent-encoded
because it is the string that goes on the wire. The change describes a venue that
now agrees with what Phase 034 built for a different reason. Nothing was added to
comply with it; a test was added to prove the compliance is not accidental.

The Unicode testnet symbols are recorded because they are the venue's own answer to
"what should a Unicode signing test use", and using them keeps the fixture a
documented value rather than one this repository invented.

---

### S-04 — Binance API Key Types FAQ

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/api_key_types.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. **Newly declared** in
[`binance-api-reality.toml`](../engineering/binance-api-reality.toml) as
`spot-api-key-types`; `rest-api.md` links to it by name (*"We support HMAC, RSA,
and Ed25519 keys. For more information, please see API Key types"*), and Phase 033
had not read it.

**Digest at access:** `sha256:7b6c1727a8181fb9dc260a17a3cf666b8df3a15bd15a54cd64d525b5a6bcee1d`

**What it establishes**, quoted:

- The supported list, in the document's own order: *"Ed25519 (recommended) / HMAC /
  RSA"*.
- *"**We recommend to use Ed25519 API keys** as it should provide the best
  performance and security out of all supported key types."*
- *"**HMAC keys are deprecated.** We recommend to migrate to asymmetric API keys,
  such as Ed25519 or RSA."*
- *"We support 2048 and 4096 bit RSA keys."*
- Sample signatures for all three types.

**Implication for GLOBIN — this one corrected a decision already taken.** This
phase's plan recorded that no HMAC deprecation is announced anywhere. That was
true of the changelog, which mentions HMAC twice and in the *opposite* direction
(*"Features that currently require an Ed25519 API key will soon be opened up to
HMAC and RSA keys"*), and true of `rest-api.md`, which never uses the word. It was
false of the document `rest-api.md` points at, and the plan would have recorded
HMAC as `supported` when a primary source states otherwise.

So HMAC is recorded `deprecated` in the auth contract, which
[`SurfaceStatus.DEPRECATED`](../../src/globin/domain/api_reality.py) defines as
*"Documented, still reachable, and announced as going away"* — exactly the claim
the FAQ makes. **It keeps working**, because `CapabilityRecord.usable` already
counts `DEPRECATED` as usable and nothing in this phase special-cases it. A
deprecation is metadata an operator reads, not a refusal.

The three sample signatures were measured rather than admired, and the measurement
is what makes S-05 provable:

| Sample | base64 chars | decoded bytes | correct for its algorithm |
|---|---|---|---|
| Ed25519 | 88 | 64 | yes — RFC 8032 fixes an Ed25519 signature at 64 bytes |
| HMAC | 64 hex | 32 | yes — SHA-256 |
| RSA-2048 | 344 | 256 | yes |

---

### S-05 — Binance Spot REST API, the Ed25519 worked examples

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md
— the same document as S-01, section *SIGNED Endpoint Examples for POST
/api/v3/order → Ed25519 Keys*

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary, and **wrong**.

**What it establishes.** The *normative* text is sound and is what GLOBIN
implements:

- *"**Note: It is highly recommended to use Ed25519 API keys** as it should provide
  the best performance and security out of all supported key types."*
- The same signature-payload rule as HMAC and RSA.
- **Step 2:** *"1. Sign the payload. 2. Encode the output as a base64 string."*
- *"Note that the payload and the resulting `signature` are **case-sensitive**."*
- **Step 3 of encoding:** *"Percent-encode the base64 string."*

The *worked examples* beside that text are not Ed25519 output. Measured:

| Example | base64 chars | decodes to | An Ed25519 signature is |
|---|---|---|---|
| ASCII | 343 | **nothing — 343 is not a multiple of 4** | 64 bytes / 88 chars |
| non-ASCII | 344 | 256 bytes, i.e. RSA-2048 | 64 bytes / 88 chars |

The non-ASCII example is additionally **byte-identical** to the output published in
the *RSA* section immediately above it. The shell command shown is
`openssl dgst -keyform PEM -sha256 -sign ./test-prv-key.pem`, which is an RSA
invocation: Ed25519 is PureEdDSA and takes no separate digest step.

**Implication for GLOBIN — this one changed the test plan.** The Ed25519 signer is
**not** built against a known-answer vector from this document, because there is no
correct one here to build against. Copying these values would have produced a
"signer" that reproduced RSA behaviour under an Ed25519 label and passed its own
test. Instead:

- the **normative text** supplies the contract — sign the payload directly, base64,
  then percent-encode, no case normalisation;
- the **known-answer vectors** come from RFC 8032 (S-07), which is the algorithm's
  defining document and Tier 1 for the algorithm under
  [`SOURCE_POLICY.md`](../SOURCE_POLICY.md);
- a round-trip test verifies each signature against the matching public key, which
  is the property that actually matters and which no fixed vector can give.

The signature-length arithmetic became a test of its own: an Ed25519 signature that
is not 64 bytes fails before anything looks at its value.

---

### S-06 — Binance Spot Testnet general information

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/testnet/general-info.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. Already declared as `spot-testnet`.

**Digest at access:** `sha256:f6ff938f0d8bb8bb6b0496ce3010aaf847c385060da49d271d34b9b8ebb60be1`

**What it establishes**, quoted:

- *"We support RSA keys of any length from 2048 bits up to 4096 bits. We recommend
  **2048 bits keys** as a good balance between security and signature speed."*
- *"When generating the RSA signature, use the **PKCS#1 v1.5** signature scheme.
  This is the default when using OpenSSL. **We currently do not support the PSS
  signature scheme.**"*
- The API key goes *"in the `X-MBX-APIKEY` header of your requests, exactly the
  same way as you would do for HMAC-SHA-256 API Keys."*
- Ed25519 *"provides security comparable to 3072-bit RSA keys"*.
- All three key types are available on testnet.

**Implication for GLOBIN.** The PSS sentence is why
`tests/unit/test_signing.py::test_rsa_signature_is_not_pss` exists as a
**quotation-backed** test rather than a defensive one: the venue states PSS is
unsupported, so a signer that silently used it would be rejected by the venue with
`-1022` and by nothing in this repository. The test verifies a produced signature
against PKCS#1 v1.5 **and** asserts it does not verify under PSS, which is the only
way to tell the two apart from the outside.

`rest-api.md` says *"Only `PKCS#8` keys are supported"* — that is the **key
serialisation format** — while this document says PKCS#1 v1.5 is the **signature
scheme**. The two are different things with confusingly similar names and both are
enforced separately: the loader refuses a key that is not PKCS#8, and the signer
uses PKCS#1 v1.5 padding.

---

### S-07 — RFC 8032, Edwards-Curve Digital Signature Algorithm (EdDSA)

**Canonical location:** https://www.rfc-editor.org/rfc/rfc8032

**Accessed:** 2026-08-19

**Authority:** Tier 1 for the algorithm — the specification that defines it, per
[`SOURCE_POLICY.md`](../SOURCE_POLICY.md)'s rule that upstream documentation is
authoritative for the thing it documents.

**Digest at access:** `sha256:ed63657ff389301282b169b0abde9b5dd2c7e4d524fdfa5da6ff3094fc93c4c3`

**What it establishes:**

- An Ed25519 signature is **64 octets**. §5.1.6 step 6: *"Form the signature of
  the concatenation of R (32 octets) and the little-endian encoding of S (32
  octets…)"*, restated in §7: *"private and public keys are 32 octets; signatures
  are 64 octets."*
- Ed25519 signing is **deterministic**. §5.1.6 step 2 computes the per-message
  nonce as `SHA-512(dom2(F, C) || prefix || PH(M))`, where `prefix` is the second
  half of the private key's hash — so the nonce is a function of the key and the
  message alone, with no randomness, and one key signing one message twice yields
  identical bytes.
- §7.1 publishes test vectors of secret key, public key, message and expected
  signature. TEST 2 and TEST 3 are used here.

**Implication for GLOBIN.** Determinism is asserted as a property rather than
assumed: `test_ed25519_signature_is_deterministic` signs one payload twice and
compares. That test would fail for ECDSA, which is the point — it distinguishes the
scheme GLOBIN uses from one that would appear to work while producing a different
signature on every call, and it is the property the brief asked to be proved.

---

### S-08 — Binance Spot Demo Mode general information

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/demo-mode/general-info.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. Already declared as `spot-demo`.

**Digest at access:** `sha256:6b07adb3cc2ca92828cb74a27c7a2e3a3f7c75de9ba362843ecd1e636409073d`

**What it establishes**, quoted:

- The REST base URL is **`https://demo-api.binance.com/api`**.
- Keys are created *"in the API Key Management page"* at `demo.binance.com`.
- *"Demo Mode always has the same features as the live exchange."*
- *"Realistic market data is not equal to 'real' market data. Do not assume trading
  strategies that work in Demo Mode will work in the live exchange."*

**What it does not establish**, which is the part that mattered: the document names
**no key type at all**. It directs the reader to the Spot API documentation, so the
registry's `key_types = ["hmac", "rsa", "ed25519"]` for the demo endpoint rests on
S-01 rather than on this document. That is defensible and is recorded here rather
than left for a later reader to reconstruct.

**Implication for GLOBIN — this decided one row of the environment class table.**
The demo document says market data is *"realistic"* and *"not equal to 'real'"*,
while [`config/profiles/paper.toml`](../../config/profiles/paper.toml) declares
GLOBIN's own paper environment as *"Simulated execution against real market data"*.
So `market_data_is_real` is **false for demo and true for internal simulation** —
an asymmetry that looks like a mistake until both sources are read, and one the
Phase 033 registry structurally cannot express because internal simulation has no
venue row to put it in.

---

## What was deliberately not consulted

No blog post, forum answer, third-party SDK, or community wrapper informed any
header, parameter, algorithm, encoding or bound in this phase.

Two exclusions are worth naming specifically, because both were available and both
would have been faster:

**The published `binance-connector` clients were not read**, in any language.
Their signing code is the obvious place to check an implementation against, and
[`SOURCE_POLICY.md`](../SOURCE_POLICY.md) prohibits it as a basis: an SDK is one
party's reading of the documentation, and where it disagrees with the venue the
disagreement is invisible until a request is rejected. S-05 is the argument — a
reader who trusted the documentation's own Ed25519 example would have been wrong,
and a reader who trusted an SDK would have had no way to notice.

**The derivatives, margin and portfolio-margin documentation was not consulted**,
because it remains inaccessible for the reason Phase 034 recorded: it is a
client-rendered application with no fetchable text form, and `SOURCE_POLICY.md`
forbids both scraping it and accepting a generated summary in its place. Their REST
surfaces therefore stay `unknown` in the registry and every authenticated request
against them is refused before a credential is read. That is the honest answer, and
it is why this phase implements **no** HMAC-by-default route for those products:
routing them to a signer would require knowing they accept one, and no admissible
source says so.
