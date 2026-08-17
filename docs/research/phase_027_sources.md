# Phase 027 — Source Ledger

Every external behaviour this phase depends on, with the primary source that
established it. The rules this ledger obeys — which sources count as primary, what each
entry must record, and when a claim must be re-verified — are in
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

Two of these entries changed an implementation decision rather than confirming one, and
both are noted where they did.

---

### S-01 — A scrape target selects the highest-weighted offered protocol it supports, and falls back to Prometheus text 0.0.4 rather than refusing

- **Canonical location:** https://prometheus.io/docs/instrumenting/content_negotiation/
- **Accessed:** 2026-08-17
- **Authority:** Primary — the Prometheus project's own specification of the scrape
  protocol negotiation.
- **Supports:** Five protocols are named, sharing three media types:
  `text/plain` (PrometheusText0.0.4 and PrometheusText1.0.0),
  `application/openmetrics-text` (OpenMetricsText0.0.1 and OpenMetricsText1.0.0) and
  `application/vnd.google.protobuf`. Selection is *"the protocol in the Accept header
  with the highest weighting that is supported"*. When none is supported, *"the target
  MAY use a user-configured fallback scrape protocol. If no fallback is specified, the
  target MUST use PrometheusText0.0.4 as a last resort."* The `escaping=<scheme>`
  parameter *"MUST be one of: `allow-utf-8`, `underscores`, `dots`, `values`"* and
  applies to the 1.0.0-and-above text formats.
- **Implication for GLOBIN:** `negotiate()` is **total** — it returns a format for every
  input and has no failure branch, because the protocol has no failure mode here.
  **This changed a decision:** the phase brief asked for a deterministic answer when no
  acceptable format is found, and a 406 was the obvious reading; the specification
  declines to use that status, so emitting one would have made GLOBIN the only target in
  a scrape fleet that does. The two versions GLOBIN does not produce are non-matches
  rather than near-matches, so `text/plain; version=1.0.0` falls through to the last
  resort instead of being answered with 0.0.4 bytes under a 1.0.0 content type.

### S-02 — OpenMetrics 1.0 fixes the content type, requires an EOF terminator, moves the `_total` suffix to the sample, and makes the UNIT line conditional

- **Canonical location:** https://prometheus.io/docs/specs/om/open_metrics_spec/
- **Accessed:** 2026-08-17
- **Authority:** Primary — the published OpenMetrics 1.0 specification as the Prometheus
  project hosts it.
- **Supports:** *"The content type MUST be: `application/openmetrics-text;
  version=1.0.0; charset=utf-8`"*. *"Expositions MUST end with EOF and SHOULD end with
  `EOF\n`"*. *"The MetricPoint's Total Value Sample MetricName MUST have the suffix
  `_total`."* *"If a unit is specified it MUST be provided in a UNIT metadata line. In
  addition, an underscore and the unit MUST be the suffix of the MetricFamily name."*
  *"There MUST NOT be more than one of each type of metadata line for a MetricFamily.
  The ordering SHOULD be TYPE, UNIT, HELP."* Reserved suffixes are listed per type —
  Counter `_total` and `_created`; Histogram `_count`, `_sum`, `_bucket`, `_created`.
- **Implication for GLOBIN:** three concrete consequences and one refusal.
  `render_openmetrics` emits `# EOF\n` **including for an empty registry**, because an
  exposition with no terminator is invalid rather than short — which is also why an
  oversized response is refused instead of truncated. A counter's MetricFamily drops the
  `_total` GLOBIN's registry requires of the *name*, so the family is
  `globin_diagnostics_http_requests` and the sample `..._requests_total`; leaving it on
  both would have produced `_total_total`. Histograms gained cumulative
  `_bucket{le=...}` samples including `le="+Inf"`, which Phase 026's renderer omitted.
  **And the UNIT line is omitted entirely.** The rule is conditional, and GLOBIN's
  durations are integer nanoseconds by ADR-0068: a family named `..._nanoseconds`
  carrying `# UNIT ... s` would be a false claim about its own numbers, and the
  alternatives — renaming or rescaling — would reopen a Phase 026 decision to satisfy an
  optional line.

### S-03 — The exact content type of Prometheus text 0.0.4, and what an absent version parameter means

- **Canonical location:** https://prometheus.io/docs/instrumenting/exposition_formats/
- **Accessed:** 2026-08-17
- **Authority:** Primary — the Prometheus project's own exposition format reference.
- **Supports:** The text format is served as `text/plain` with `version=0.0.4`, and
  *"a missing version value will lead to a fall-back to the most recent text format
  version"*. The OpenMetrics type is `application/openmetrics-text` with
  `version=1.0.0`, with the same rule for an absent version.
- **Implication for GLOBIN:** the two content-type strings are `Final` constants in
  `globin.domain.diagnostics_http` rather than assembled at run time, and each is paired
  with the encoder that produces it — so the header and the bytes cannot disagree. A bare
  `text/plain` is answered with 0.0.4, which is what GLOBIN produces and what the
  protocol's last resort names.

### S-04 — `http.server` is not recommended for production, and `send_response` is what adds a `Server` header and a stderr access line

- **Canonical location:** https://docs.python.org/3.12/library/http.server.html
- **Accessed:** 2026-08-17
- **Authority:** Primary — the standard library documentation for the pinned interpreter
  line.
- **Supports:** *"http.server is not recommended for production. It only implements basic
  security checks."* `send_response()` *"adds a response header to the headers buffer and
  logs the accepted request. The HTTP response line is written to the internal buffer,
  followed by Server and Date headers"*, whose values come from `version_string()` and
  `date_time_string()`. `send_response_only()` *"sends the response header only"* and
  adds neither. `log_message()` *"logs an arbitrary message to sys.stderr"* with *"the
  client ip address and current date and time ... prefixed to every message"*.
  `protocol_version` *"defaults to `'HTTP/1.0'`"*, and `'HTTP/1.1'` *"will permit HTTP
  persistent connections"* but then requires an accurate `Content-Length`.
  `ThreadingHTTPServer` *"uses threads to handle requests by using the ThreadingMixIn"*.
- **Implication for GLOBIN:** four decisions rest on this. The production warning is
  about serving files to untrusted clients, so it is answered by serving none — no static
  content, no directory logic, no CGI, and a five-entry table of exact targets. Every
  response is written through `send_response_only`, which removes the product fingerprint
  and the unstructured stderr access line in one choice rather than two. `HTTP/1.0` is
  kept deliberately, because keep-alive would let an idle connection hold one of four
  pool slots. And `ThreadingMixIn`'s contract is one thread per connection with no
  ceiling, so `process_request` — the hook that mixin overrides — hands the connection to
  a bounded queue drained by a fixed pool instead.

### S-05 — A `do_*` method that does not exist is answered by `send_error`, which writes an HTML page

- **Canonical location:** https://github.com/python/cpython/blob/3.12/Lib/http/server.py
- **Accessed:** 2026-08-17
- **Authority:** Primary — CPython's own implementation for the pinned interpreter line,
  read because the documentation describes `send_error`'s behaviour without saying which
  paths reach it.
- **Supports:** `handle_one_request` resolves `'do_' + self.command` and, when no such
  attribute exists, calls `send_error(HTTPStatus.NOT_IMPLEMENTED, ...)` with the
  requested method interpolated into the message. `send_error` builds a body from
  `error_message_format`, which is an HTML document, and sends it as `text/html`. The
  same method is reached for an unparseable request line, an unsupported HTTP version, an
  over-long request line and too many headers.
- **Implication for GLOBIN:** defining only `do_GET` and `do_HEAD` is **not** sufficient
  to keep HTML off this surface. `send_error` is overridden: an unsupported method is
  routed through `DiagnosticsService` so it is counted, logged with a bounded reason and
  answered `405` with `Allow`, and anything else becomes a bounded `400` with a constant
  body. Neither the `message` nor the `explain` argument is used, because both are built
  from what the client sent. This was found by driving the real server rather than by
  reading — the first end-to-end run answered `POST` with a 482-byte HTML page carrying
  no cache directive, no sniffing refusal and `Content-Type: text/html`.

### S-06 — `str.isdigit` is true for characters `int` refuses; `str.isdecimal` is the narrower test

- **Canonical location:** https://docs.python.org/3.12/library/stdtypes.html#str.isdecimal
- **Accessed:** 2026-08-17
- **Authority:** Primary — the standard library documentation for the pinned interpreter
  line.
- **Supports:** `str.isdigit` is true for characters with the Unicode `Numeric_Type`
  property of `Digit` or `Decimal`, *"which includes ... superscript digits"*;
  `str.isdecimal` is true only for characters *"that can be used to form numbers in base
  10"*, and the documentation notes this is the property that matches what
  `int(str)` accepts.
- **Implication for GLOBIN:** two screens changed. `_bounded` in
  `globin.domain.configuration` paired `isdigit` with `int()`, so a value such as a
  superscript two raised `ValueError` on input it had just declared acceptable — escaping
  the error taxonomy, since `main` catches `GlobinError` and `OSError` and would have
  shown a traceback instead of a sentence naming the setting. The path was unreachable
  while every string value came from a TOML document; Phase 027's environment variables
  are strings and nothing else, which made it live. `quality_of` had the same pair for
  the same reason. Both now use `isdecimal`, and a property test over generated text is
  what found it.

### S-07 — RFC 9110 gives a quality value at most three digits, and defines `q=0` as "not acceptable"

- **Canonical location:** https://www.rfc-editor.org/rfc/rfc9110.html#name-quality-values
- **Accessed:** 2026-08-17
- **Authority:** Primary — the IETF standard for HTTP semantics.
- **Supports:** A quality value is a number between 0 and 1 with at most three digits
  after the decimal point; a sender *"MUST NOT generate more than three digits after the
  decimal point"*. A weight of zero means the associated media range is not acceptable.
- **Implication for GLOBIN:** `quality_of` returns **thousandths as an integer**, so
  `q=0.9` and `q=0.90` compare equal and sort identically on every run — the same refusal
  of floats ADR-0068 makes for telemetry values. An unreadable weight returns zero, which
  reuses the meaning the standard already gives that value rather than inventing a lenient
  default; a mangled header therefore cannot outrank a well-formed one. A fourth digit and
  a value above one are both refused rather than clamped.

### S-08 — Closing a socket that still holds unread received data sends a reset rather than a graceful shutdown

- **Canonical location:** https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-closesocket
- **Accessed:** 2026-08-17
- **Authority:** Primary — the Winsock API documentation for the platform this repository
  runs on, per `docs/engineering/RUNTIME_BASELINE.md`.
- **Supports:** `closesocket` on a socket with data still queued in the receive buffer
  aborts the connection rather than closing it gracefully, and an abort discards data the
  peer has not yet read.
- **Implication for GLOBIN:** the admission-refusal path writes a `503` and then performs
  **one bounded read** of the request it was never going to serve, before closing.
  Without that read the client received a connection reset instead of the deterministic
  refusal the whole path exists to produce — which an integration test observed as
  `ConnectionAbortedError` before the read was added. The read is bounded by a single
  4 KiB `recv` and by the request timeout, because the point is to clear the buffer
  rather than to parse anything.
