# Phase 034 — Source Ledger

Every external fact the REST transport encodes, where it was read, and what it
changed about the implementation.

Five entries, and three of them **changed the code**. That ratio is the argument
for reading the documentation rather than remembering it: two of the three
corrections would have produced a transport that appeared to work and was wrong in
a way no offline test could have caught.

---

### S-01 — Binance Spot REST API

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. The party that defines the behaviour, documenting
its own behaviour. Already declared in
[`binance-api-reality.toml`](../engineering/binance-api-reality.toml) as
`spot-rest`.

**Digest at access:** `sha256:49ea6809243fc7fb426e07f2fe662097736c7bb405bd2da5eef637d715427999`
— **character for character what Phase 033 recorded**, so the registry had not
drifted between the two phases.

**What it establishes:**

- HTTP status meanings, quoted: 403 is *"used when a WAF (Web Application Firewall)
  rule has been violated"*; 409 *"used when a cancelReplace order partially
  succeeds"*; 429 *"used when breaking a request rate limit"*; 418 *"used when an IP
  has been auto-banned for continuing to send requests after receiving `429`
  codes"*.
- The 5XX rule, quoted in full because the whole outcome model rests on it: *"used
  for internal errors; the issue is on Binance's side. It is important to **NOT**
  treat this as a failure operation; the execution status is **UNKNOWN**."*
- Error `-1007 TIMEOUT`: *"Timeout waiting for response from backend server. Send
  status unknown; execution status unknown."* — and *"This does not always mean
  that the request failed in the Matching Engine."*
- The rate-limit header names, with the interval inside the name:
  `X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)` and
  `X-MBX-ORDER-COUNT-(intervalNum)(intervalLetter)`.
- Response timestamps are *"in milliseconds by default"*.
- `GET /api/v3/ping` (weight 1), `GET /api/v3/time` (weight 1) and
  `GET /api/v3/exchangeInfo` (weight 20), all security `NONE`. Every path begins
  `/api/v3`.

**Implication for GLOBIN:** `AMBIGUOUS_STATUSES` and `AMBIGUOUS_EXCHANGE_CODES` are
transcriptions of the two quoted passages rather than judgements. 403, 418 and 429
are recorded **unambiguous** because the venue places all three before any matching
engine — and recording them ambiguous would have made a rate-limit rejection
permanently unretryable at Phase 043, since nothing retries `UNKNOWN`. The header
prefixes became `RateLimitReport`'s two *mappings* rather than fields, because the
interval is part of the name and GLOBIN cannot know which intervals the venue
publishes. The three probe paths are declared relative to the registry's recorded
`path_prefix`, so `/v3/ping` joins to `/api/v3/ping` and the prefix lives in one
place.

---

### S-02 — Binance Spot SBE FAQ

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/sbe_faq.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. **Added to the registry by this phase** as
`spot-sbe-faq`; Phase 033 had declared the SBE *stream* document and not this one,
which covers the REST half.

**Digest at access:** `sha256:41ae3db05139e03720ccaa8784ec251091af5887857946ea005b38142f708036`

**What it establishes:**

- The REST SBE request headers: `"Accept: application/sbe"`, and `X-MBX-SBE`
  carrying `"<ID>:<VERSION>"` — the example given is `"1:0"`.
- The behaviour when the schema is unsupported, in two cases. With only
  `application/sbe` offered: *"the response will be an SBE-encoded error."* With
  both `application/sbe` and `application/json` offered: *"the response will fall
  back to JSON."*
- The `Content-Type` of a successful SBE response is **not specified**.

**Implication for GLOBIN — this one changed a design decision.** The fallback is a
*silent downgrade*: GLOBIN would receive a JSON body while its own record said SBE,
which is the optimistic acceptance of an unavailable capability the phase brief
lists as a failure condition. So GLOBIN offers **one** media type when it asks for
SBE, deleting the branch rather than handling it. A JSON content type arriving in
answer to an SBE request is therefore treated as `UNEXPECTED_CONTENT_TYPE` rather
than as a convenience — something negotiated behind GLOBIN's back. Separately, the
`<ID>:<VERSION>` format turned out to be character for character what Phase 033's
`SchemaVersion.label` already rendered from the lifecycle files, so no second
renderer was written.

---

### S-03 — Binance Spot REST API, timestamp unit section

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md

**Accessed:** 2026-08-19

**Authority:** Tier 1 — primary. The same document as S-01, re-read against one
specific question, and recorded separately because the *absence* it establishes is
what mattered.

**What it establishes:** the document's only mention of the header is *"To receive
the information in microseconds, please add the header
`X-MBX-TIME-UNIT:MICROSECOND` or `X-MBX-TIME-UNIT:microsecond`."* **`MILLISECOND`
is never listed as an accepted value.** Millisecond is described as the default
behaviour rather than as a header option.

**Implication for GLOBIN — this one changed the code.** The first draft carried a
`TIME_UNIT_MILLISECOND = "MILLISECOND"` constant, which
[`SOURCE_POLICY.md`](../SOURCE_POLICY.md) forbids as an invented parameter value.
`TimeUnitPreference.MILLISECONDS` now sends **no header at all** — asking for the
documented default is the same act as not asking — and the preference survives only
in the record of what GLOBIN wanted. The absence is asserted by
`tests/unit/test_rest.py` so a future edit cannot reintroduce the spelling.

---

### S-04 — RFC 3986, Uniform Resource Identifier: Generic Syntax

**Canonical location:** https://www.rfc-editor.org/rfc/rfc3986

**Accessed:** 2026-08-19

**Authority:** Tier 1 for the syntax it defines — the specification that defines
percent-encoding, cited by the venue's own signing documentation by reference.

**What it establishes:** the *unreserved* set is `ALPHA / DIGIT / "-" / "." / "_" /
"~"`; producers should normalise percent-encodings to **uppercase** hexadecimal;
and `/`, `:`, `@`, `+`, `&`, `=` are reserved.

**Implication for GLOBIN:** `UNRESERVED` is that set exactly and nothing more, which
is **narrower than `urllib.parse.quote`'s default** — it leaves `/` alone, correct
for a path and wrong for a value, where an unescaped slash turns one parameter into
two. Uppercase escaping is load-bearing rather than tidy: a signature computed over
`%2f` does not match one computed over `%2F`, so Phase 038 depends on it. The
encoder is hand-written because
[`dependency-rules.toml`](../architecture/dependency-rules.toml) declares `urllib`
I/O-capable and a domain module may not import one — which turned out to be the
better shape, since the safe set is now a stated constant this repository owns
rather than a standard-library default that may be widened.

---

### S-05 — Python standard library, `http.client` and `ssl`

**Canonical location:** https://docs.python.org/3/library/http.client.html

**Accessed:** 2026-08-19

**Authority:** Tier 1 for library behaviour — the project's own documentation, per
[`SOURCE_POLICY.md`](../SOURCE_POLICY.md).

**What it establishes:**

- `HTTPConnection.request()` connects lazily if the connection is not already open.
- `HTTPResponse.will_close` reports whether the connection survives the response.
- `ssl.create_default_context()` returns a context with `check_hostname` true and
  `verify_mode` `CERT_REQUIRED`.
- `socket.gaierror`, `ssl.SSLError`, `TimeoutError`, `ConnectionRefusedError` and
  `ConnectionResetError` are all subclasses of `OSError`.

**Implication for GLOBIN — this one changed the code.** Because `request()`
connects lazily, a DNS failure and a half-written request would arrive as one
exception, leaving GLOBIN unable to say whether any bytes left the process — which
is exactly the distinction `SendState` exists to draw. The transport therefore calls
`connect()` as its own step, so a failure before it is provably `NOT_SENT` and a
failure after it is conservatively `SENT`. The shared `OSError` ancestry is why the
failure mapping is ordered specific-before-general: a general clause reached first
would swallow every named case. And `secure_context()` **asserts** what
`create_default_context` documents rather than trusting it, because that is the one
property whose silent loss would be invisible in every test that passes.

---

## What was deliberately not consulted

No blog post, forum answer, third-party SDK, or community wrapper informed any
endpoint, header, status meaning or parameter value in this phase.
[`SOURCE_POLICY.md`](../SOURCE_POLICY.md) prohibits them as a basis for
implementation, and the three corrections above are the argument for the rule: each
was a case where a plausible assumption would have compiled, passed review, and
been wrong against the real venue.
