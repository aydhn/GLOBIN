# REST Authentication

How GLOBIN signs a request to Binance, why the algorithm is read rather than
chosen, and what it refuses to do.

Phase 034 built a transport that reaches the venue and signs nothing. This is the
layer above it: it decides whether a request *may* be signed, produces the exact
characters the venue will verify, and hands the transport a finished request.

---

## What Phase 035 is not

**It does not hold a credential.** GLOBIN has a secret store (Phase 028), an
interactive collection flow (Phase 029), a DPAPI vault (Phase 031) and now three
signers. It holds no key, `required_credentials()` is still empty, and no start-up
demands one. Every authenticated verb reports a deterministic skip.

**It sends no authenticated request by any default path.** `globin auth probe`
exists, needs the verb *and* `auth.probe_enabled` *and* — against the live
exchange — `auth.allow_production_probe`, and today refuses before all of that
because no credential is configured.

**It places no order, and cannot.** The one operation the probe may send is
`GET /api/v3/account`, spelled as a constant with no parameter that could change
it — the same shape [`run_probe`](../../src/globin/application/rest.py) uses to
hardcode `PUBLIC` and `READ_ONLY`.

**It does not synchronise a clock.** The venue's own processing rule is written in
terms of `serverTime`, which GLOBIN did not have. Phase 036 owns that, and the
seam it plugs into is [`ports/clock.py`](../../src/globin/ports/clock.py), which
already says *"a clock that reports Binance's server time can honestly implement
`Clock`"*.

**It does not retry.** Phase 043 owns retry and inherits one answer rather than
inventing one — see [Retry](#retry-and-the-seam-phase-043-inherits) below.

**It does not fill the permission registry.** Which operations a key is entitled
to perform is Phase 039's, and that is also where `required_credentials()` stops
being empty.

---

## The exact-bytes invariant

The venue's rule, quoted:

> The signature payload of your request is the query string concatenated without
> separator to the HTTP body. Any non-ASCII character must be percent-encoded
> before signing.

And, announced 2025-12-17 and effective 2026-01-15 07:00 UTC:

> When calling endpoints that require signatures, percent-encode payloads before
> computing signatures. Requests that do not follow this order will be rejected
> with `-1022 INVALID_SIGNATURE`.

**GLOBIN required no change for either.** Phase 034 wrote
[`percent_encode`](../../src/globin/domain/rest.py) from RFC 3986 — unreserved set
only, uppercase escapes — for a different reason, and
`QueryParameters.canonical()` renders the string that goes on the wire. So the
string that is signed and the string that is sent are produced by *one method on
one frozen value*.

The consequence is an equality rather than an argument:

```text
canonical(items + signature) == canonical(items) + "&signature=" + encode(sig)
```

The signed span is a literal **prefix** of the transmitted query string.
[`AuthenticatedRequest.wire_matches`](../../src/globin/domain/auth.py) asserts it,
a [property test](../../tests/property/test_auth_properties.py) asserts it over
generated parameters, and an
[integration test](../../tests/integration/test_auth_end_to_end.py) asserts it
against **the raw request line a real server received** — which is the only way to
establish that `http.client` writes the target verbatim rather than normalising a
percent-escape.

### It reproduces the venue's own worked examples

The REST document publishes two HMAC examples with their expected signatures. Both
reproduce exactly, and the second carries a symbol of fullwidth digits:

```console
$ globin auth selftest

  pass  auth.known_answer   both published HMAC vectors reproduce exactly
  pass  auth.wire_equality  the signed span is a prefix of the wire query,
                            Unicode encoded before signing
```

Rendered from GLOBIN's own parameters, the full target is character for character
the URL in the venue's own `curl` example, signature included.

---

## Signer selection is a lookup, never a branch

Phase 033's registry already records `key_types` per endpoint, so *which
algorithms may sign a request to this endpoint* is answered by a committed
document. There is no `if family == "spot"` anywhere, and
[`test_api_reality_discipline.py`](../../tests/architecture/test_api_reality_discipline.py)
still fails if a venue host is spelled in a module.

| Key type | Algorithm | Encoding | Case-sensitive | Status |
|---|---|---|---|---|
| `hmac` | HMAC-SHA256 | hex | no | **deprecated** |
| `rsa` | RSASSA-PKCS1-v1_5 + SHA-256 | base64 | yes | supported |
| `ed25519` | Ed25519 (PureEdDSA) | base64 | yes | supported, **recommended** |

`algorithm_for()` is total over `ApiKeyType` and has **no fallback branch**. A
`return HMAC_SHA256` at the end would be the single most dangerous default
available here: HMAC is the algorithm the venue documents as deprecated, so the
fallback would move a caller onto it using a secret they enrolled for something
else. [ADR-0091](../adr/0091-authentication-is-capability-driven-and-product-scoped.md)
records the rule.

### HMAC is deprecated, and it still works

The venue's [API Key Types](https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/api_key_types.md)
document says plainly: *"**HMAC keys are deprecated.** We recommend to migrate to
asymmetric API keys, such as Ed25519 or RSA."*

Neither `rest-api.md` nor the CHANGELOG says it — the changelog mentions HMAC
twice and both times in the *opposite* direction. This phase's plan recorded "no
HMAC deprecation is announced" on the strength of those two documents and was
corrected by following the link `rest-api.md` itself provides.
`docs/research/phase_035_sources.md` S-04 has the whole of it.

**Deprecated is usable.** `CapabilityRecord.usable` already counts it so, nothing
in the signing path special-cases it, and a contract test signs with it. What the
status changes is what an operator is told, not what GLOBIN does.

---

## The eight gates

Each refuses before the next, cheapest and broadest first, so the message names
the outermost thing that is wrong rather than an inner consequence of it.

| | Gate | Refusal |
|---|---|---|
| 1 | The environment's class accepts a credential | `ENVIRONMENT_FORBIDS_CREDENTIAL` |
| 2 | The environment name is classified at all | `ENVIRONMENT_UNCLASSIFIED` |
| 3 | Phase 034's resolution permitted the request | `ENDPOINT_UNRESOLVED` |
| 4 | The security type needs a credential | `AUTHENTICATION_NOT_REQUIRED` |
| 5 | A credential is configured for this pair | `MISSING_CREDENTIAL` |
| 6 | The endpoint documents this key type | `CREDENTIAL_TYPE_MISMATCH` |
| 7 | A signer for the algorithm exists here | `SIGNER_UNAVAILABLE` |
| 8 | The validity window is acceptable | `INVALID_RECV_WINDOW` |

**Gate 1 runs before the registry.** A request in an environment GLOBIN simulates
is refused with nothing having been looked up — not *we declined to use the
credential*, but *no credential was ever reached for*. See
[`ENVIRONMENT_CLASSES.md`](ENVIRONMENT_CLASSES.md).

**Nothing falls back.** Not to a different algorithm, not to a different
environment, not to a different endpoint.

**Twelve products refuse at gate 3, and that is the honest answer.** Their REST
surface is `unknown` in the registry, and Phase 034 recorded that the derivatives
documentation is client-rendered with no admissible route.
`docs/SOURCE_POLICY.md` forbids both scraping it and accepting a generated summary
in its place, so routing them to an HMAC signer would require knowing they accept
one, and no admissible source says so.

---

## Security types

Four, exactly the four the documentation tabulates: `NONE`, `TRADE`, `USER_DATA`,
`USER_STREAM`. `MARGIN` appears in older material and in no current Spot REST
table.

**There is no API-key-without-signature tier on this surface**, which was a
finding rather than a design choice. Quoted: *"Except for `NONE`, all endpoints
with a security type are considered `SIGNED` requests (i.e. including a
`signature`)."* So `USER_STREAM` is signed like the other two, and GLOBIN has no
branch for a key without a signature.

`RequestSecurityIntent.API_KEY` remains a member of Phase 034's enumeration
because the registry's vocabulary spans more than REST — but no Spot REST endpoint
can produce it, and the registry records `signed` or `none` on all ten REST rows.

---

## Timing

| | |
|---|---|
| `timestamp` | milliseconds **or** microseconds, both documented |
| `recvWindow` | milliseconds only; default `5000`; maximum `60000`; up to **three decimal places** |

`RecvWindow` carries a `Decimal`, and `auth.recv_window_millis` is a **quoted
string** in configuration. `6000.346` — the venue's own example — is not
representable as a binary float, so a TOML float would have changed the value
before any type could refuse it, and a TOML integer could not express it at all.
A `float` is refused outright rather than converted.

**A larger window is never the remedy for a clock.** The ceiling is enforced at
construction, so a configuration carrying more fails before a request exists
rather than being clamped into something nobody wrote.

The venue's processing rule is recorded in the source ledger and **not
implemented**: it names `serverTime`, and estimating one here would be building
Phase 036 early. It is built there now — see [`CLOCK_DISCIPLINE.md`](CLOCK_DISCIPLINE.md).

---

## Secret handling

| Rule | How it is held |
|---|---|
| No module but one may import `cryptography` | [`test_signing_discipline.py`](../../tests/architecture/test_signing_discipline.py), both directions |
| PSS is absent rather than unused | The token appears nowhere in the package, as code |
| The import is inside a factory | So `globin.adapters` imports on a host without the library |
| Material lives for one statement | Resolved immediately before the signer, held by nothing |
| Availability is checked before material is read | So refusing costs no key handling |
| A signature refuses to render itself | `__str__`, `__repr__`, `__format__` all yield `[redacted]`; no `__dict__`; unhashable |
| No refusal carries key material | Messages are built from a fixed table, never from the input |
| The API key travels in a header, never in the payload | And `X-MBX-APIKEY` matches an existing redaction fragment |

### The leak that was found rather than avoided

`_refuse_key_format` originally echoed the first line of the material it was
given. For a well-formed PEM that is armour and harmless. For the input that
actually reaches the error path — an operator pasting the base64 *body* by mistake
— it is forty-eight characters of private key, written into an error message, a
traceback and a log.

The fix is not a longer redaction list. Messages are now composed from a **fixed
table** of recognised armour lines, so no slice of the input can reach one:

```console
a rsa private key does not begin with the PKCS#8 armour header and so is not
PKCS#8, which is the only serialisation the venue supports; it is a PKCS#1 RSA block
```

*(The real message names the header verbatim. It is elided here because a
documentation file has no reason to carry a PEM armour line, and two independent
scanners are right to say so. `signing.py` composes its seven armour strings from
one format and a label — inside functions, because a layer package performs no
call at import and the architecture guard caught the first draft — so neither
scanner needs an allowance for it — which is better than an allowance, since an allowance blinds a
scanner to a whole pattern in a whole file.)*

A [unit test](../../tests/unit/test_signing.py) searches every refusal for any
twelve-character run of the material it was given, excluding only strings the
module publishes itself.

---

## Degradation

`cryptography` is the **seventh absent-safe component** and the first whose
absence changes what GLOBIN *does* rather than what it can *measure*.

```toml
[[component]]
id = "component.library.cryptography"
necessity = "optional"
withdraws = ["auth.signing.rsa", "auth.signing.ed25519"]
```

HMAC still works — it is `hmac` and `hashlib` — so a degraded host can still
authenticate, and what it has lost is the venue's *recommended* key type rather
than authentication itself.

**And it must never quietly use HMAC instead.** This is the trap the absent-safe
pattern invites here and does not fall into. Everywhere else in this repository an
absent library means a measurement is not taken; here the tempting "degradation"
would be a *different algorithm*, with a key the operator enrolled for something
else, on the algorithm the venue calls deprecated. So
`UnavailableAsymmetricSigner` **raises**, and the operator is told which
distribution to install.

The CI `quality` job installs the toolchain with plain `pip` and never builds
`.venv`, so this library is absent on every one of those runs — the absent arm is
exercised continuously rather than only in a test.

---

## Retry, and the seam Phase 043 inherits

This phase builds no retry engine and there is no loop for one to control. What it
leaves behind is an answer rather than a gap:

- `AuthenticatedRequest` is **frozen**. A retry that changed a parameter would
  have to build a new request, which means signing again. There is no path by
  which a mutated request keeps an old signature, because there is no path by
  which a request is mutated.
- `requires_resignature(now)` is a **predicate, not a mechanism**. Nothing calls
  it. A request with no declared window returns `True` unconditionally, which is
  the conservative direction: *re-sign* is always safe where *replay* may not be.
- Phase 034's rule is inherited unchanged: an outcome of `UNKNOWN` is never
  replayed.

---

## Commands

```bash
.venv\Scripts\globin.exe auth classes
```

```bash
.venv\Scripts\globin.exe auth capabilities --family spot --environment testnet
```

```bash
.venv\Scripts\globin.exe auth selftest
```

```bash
.venv\Scripts\globin.exe auth evidence
```

```bash
.venv\Scripts\globin.exe auth probe --family spot --environment testnet
```

**Five verbs and no sixth.** Four read and one reaches the venue; the verb is the
opt-in, matching `rest` and `venue`, so there is no `--network` flag to forget.

`capabilities` and `probe` require `--family` and `--environment` and refuse to
default either. There is no default environment here for the same reason `rest`
has none, and with more force: defaulting it would mean the live exchange could be
reached by typing nothing.

`probe` reports a deterministic **SKIP** when no credential is configured, and a
skip is exit `0` — *nothing was configured* is a true report rather than a fault.

---

## Configuration

| Key | Default | |
|---|---|---|
| `auth.key_type` | *(empty)* | `hmac`, `rsa` or `ed25519`. **No default**, because the obvious one is deprecated |
| `auth.recv_window_millis` | `"5000"` | A **quoted string**; up to three decimal places |
| `auth.timestamp_unit` | `milliseconds` | Or `microseconds` |
| `auth.probe_enabled` | `false` | Whether an authenticated read-only probe may run |
| `auth.allow_production_probe` | `false` | Whether it may run against the live exchange |

**No secret ever arrives through configuration.**
[`SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) forbids it, and the
shape of this section is what makes that easy to keep: every key is about a
policy, and a credential is named by a reference the store resolves.

**Two probe switches rather than one**, and the second is not redundant. An
operator who enabled a testnet probe has not thereby consented to touching the
live exchange, and a single switch would make those the same decision.

---

## Exit codes

**No twenty-sixth exit code. 26 stays free.**

| Code | When |
|---|---|
| `0` | Every check passed, or a probe skipped deterministically |
| `1` | The self-test failed, or a class disagreement was found |
| `3` | A committed document is absent, so nothing was established |
| `14` | Signing could not be authorised — a configuration the operator wrote |
| `15` | A configured credential would not resolve (`SECRETS_UNREADY`) |
| `25` | A key is not entitled to the operation (`CREDENTIAL_NOT_ENTITLED`, Phase 039) |

A refused key type is a configuration fault, which is what `14` already means. An
absent registry established nothing, which is `3`. Nothing here needed a new code.

---

## Evidence

```bash
.venv\Scripts\globin.exe auth evidence
```

Writes `.globin/auth/auth-manifest.json`, carrying the environment classes, the
classification, any disagreement between the document and the package, the
configured policy, which algorithms this host can compute, and every self-test
finding.

**It carries no credential, no key, no signature and no signing payload.** The
findings are check names and verdicts; the classification is public vocabulary;
the policy carries a key *type* and a window. There is nothing here to redact,
which is the property `RestDiagnosticsRecord` already has and for the same reason:
safety by construction beats safety by remembering.
