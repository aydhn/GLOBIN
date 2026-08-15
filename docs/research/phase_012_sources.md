# Phase 012 — Research Source Ledger

Phase 012 relies on external behaviour in two places, and this ledger records
what was read before either was depended on.

The first is **JSON**, whose interchange format decides what a persisted GLOBIN
record may contain and what Python's own library will do with it that the format
does not permit.

The second is **GitHub Actions**: the artifact digest an upload publishes, the
retention bounds a workflow may request, the results a job can report, and how a
required status check treats a job that never ran. Every one of those is a
platform behaviour the aggregate gate's correctness rests on, and until this
phase none of them appeared in any ledger.

**Ledger conventions.** One entry per claim relied on, not per page read. Each
records where the claim is authoritative, when it was consulted, how far it may
be trusted, the exact statement it supports, and what GLOBIN did as a result.
Official upstream documentation is primary for its own product
([`docs/SOURCE_POLICY.md`](../SOURCE_POLICY.md)). An entry is appended, never
rewritten: if a claim turns out to be wrong, a later phase's ledger records the
correction.

---

## Serialization

### S-01 — JSON permits no literal for NaN or infinity

- **Canonical location:** RFC 8259, *The JavaScript Object Notation (JSON) Data Interchange Format*, section 6 ("Numbers"), `https://www.rfc-editor.org/rfc/rfc8259`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the format's defining specification.
- **Supports:** A JSON number is a sequence of digits with optional fraction and
  exponent. The grammar admits no spelling of NaN, Infinity or -Infinity.
- **Implication for GLOBIN:** `encode_decimal` refuses a non-finite `Decimal`
  rather than writing one, and the codec refuses the bare words in both
  directions. A record containing one would be readable by Python and by very
  little else, which is the opposite of what persistence is for.

### S-02 — Python's `json` accepts and emits those literals by default

- **Canonical location:** Python 3.14 standard library documentation, `json` — `https://docs.python.org/3/library/json.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the implementation's own documentation.
- **Supports:** `json.dumps` serialises `NaN`, `Infinity` and `-Infinity` unless
  `allow_nan=False`, which raises `ValueError` instead; `json.loads` accepts the
  same three by default, and `parse_constant` is called for each. The
  documentation describes this as an extension to the specification.
- **Implication for GLOBIN:** `allow_nan=False` closes the writing half and a
  `parse_constant` that raises closes the reading half. `parse_float` is given
  the same treatment, because an exact magnitude is stored as text and a
  fractional JSON number in a GLOBIN record means somebody bypassed the encoder.

### S-03 — `json.dumps` coerces a non-string key rather than refusing it

- **Canonical location:** Python 3.14 standard library documentation, `json`, "Basic Usage" and the `skipkeys` parameter — `https://docs.python.org/3/library/json.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Keys of type `int`, `float`, `bool` and `None` are converted to
  strings during serialisation. `skipkeys` controls whether *other* key types
  raise `TypeError` or are skipped; it does not affect the conversion of these.
- **Implication for GLOBIN:** The codec walks a document and refuses a
  non-string key before rendering. Left alone, `{1: "a"}` is written as
  `{"1": "a"}` and read back as a different document — a silent narrowing that
  `ENGINEERING_CONTRACT.md` invariant 22 forbids and that no round-trip test
  using string keys would ever notice.

### S-04 — `str(Decimal)` preserves the exponent, and `Decimal(str)` restores it

- **Canonical location:** Python 3.14 standard library documentation, `decimal` — `https://docs.python.org/3/library/decimal.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** The decimal module preserves the significance of trailing zeros:
  a `Decimal` carries its coefficient and exponent, and converting to and from
  its string form is exact. `normalize` is the operation that removes trailing
  zeros, and it is not applied implicitly.
- **Implication for GLOBIN:** Magnitudes are stored as `str(value)`. That is what
  makes `Increment`'s trailing zeros survive storage — the module documents them
  as the venue's own statement of its precision — and the property test compares
  with `compare_total` rather than `==` so that a lost exponent fails.

---

## GitHub Actions

### S-05 — `upload-artifact` publishes the artifact's SHA-256 as an output

- **Canonical location:** `actions/upload-artifact` — `https://github.com/actions/upload-artifact`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the action's own repository, at the major version this
  workflow pins (v7).
- **Supports:** The action declares three outputs: `artifact-id`, `artifact-url`
  and `artifact-digest`, the last documented as "SHA-256 digest of an Artifact".
- **Implication for GLOBIN:** The evidence job exposes `artifact-digest` as a job
  output and the aggregate records it. It is necessarily produced *after* the
  upload, which is why it cannot live inside the bundle and why file-level
  checksums and the bundle digest are two separate layers (ADR-0042).

### S-06 — `retention-days` accepts 1 to 90, and a repository setting can cap it

- **Canonical location:** `actions/upload-artifact` — `https://github.com/actions/upload-artifact`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `retention-days` takes an integer from 1 to 90 inclusive.
  Omitting it uses the repository's configured default. `if-no-files-found`
  accepts `warn` (the default), `error` or `ignore`.
- **Implication for GLOBIN:** Both evidence artifacts declare
  `retention-days: 30` and `if-no-files-found: error` explicitly rather than
  inheriting a setting nobody remembers. `QUALITY_GATES.md` states the thirty
  days as a request rather than a guarantee, because a repository or organisation
  setting can cap it lower.

### S-07 — `download-artifact` needs no extra permission within one run

- **Canonical location:** `actions/download-artifact` — `https://github.com/actions/download-artifact`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** A `github-token` input is documented as "required when
  downloading artifacts from a different repository or from a different workflow
  run". Nothing additional is required for an artifact produced by the current
  run.
- **Implication for GLOBIN:** The aggregate job downloads the evidence bundle
  produced earlier in the same run, so the workflow's `permissions: contents: read`
  is unchanged. Widening the token would have been a real cost for no benefit,
  and ADR-0020 makes least privilege a decision rather than a default.

### S-08 — A job reports one of four results, and `needs` carries it

- **Canonical location:** GitHub Actions documentation, contexts and expressions — `https://docs.github.com/en/actions/reference/workflows-and-actions/contexts`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `needs.<job_id>.result` is the result of a dependency job, and
  its value is one of `success`, `failure`, `cancelled` or `skipped`.
  `toJSON(needs)` renders the whole context.
- **Implication for GLOBIN:** `tools/quality/workflow/plan.py` maps exactly those
  four and reads anything else as unmeasured. The context is passed to the gate
  through an environment variable rather than an argument, because it is a JSON
  document and a `run:` line on a Windows runner is not a safe place for one.

### S-09 — A job whose dependency failed is skipped unless a condition says otherwise

- **Canonical location:** GitHub Actions documentation, expressions and job status check functions — `https://docs.github.com/en/actions/reference/workflows-and-actions/expressions`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** A job with `needs` does not run when a job it needs fails, unless
  it uses a conditional that causes it to run anyway. `always()` returns true even
  when the workflow was cancelled; `cancelled()` returns true when the workflow
  was cancelled, so `!cancelled()` runs after a failure but not after a
  cancellation.
- **Implication for GLOBIN:** The aggregate job uses `if: ${{ !cancelled() }}`. It
  must run precisely when something upstream failed — that is the case it exists
  to report — and it must not run on every superseded run, because
  `cancel-in-progress: true` means each push cancels the run before it.

### S-10 — A skipped required check does not block a merge the way a failing one does

- **Canonical location:** GitHub documentation, "About protected branches" — required status checks — `https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Required status checks are evaluated on the checks reported for a
  commit. A check that reports a skipped conclusion is not treated as a failing
  check, so a workflow whose jobs were skipped can leave a required check
  satisfied rather than blocking.
- **Implication for GLOBIN:** The aggregate does not trust the check view. It
  verifies that every declared required job actually reported success, and that
  the evidence the run published records every gate the evidence run is supposed
  to produce. Both are fail-closed: an absent job and an absent gate each produce
  exit `3`, which is never a pass. This is the hole ADR-0042 exists to close.

### S-11 — `GITHUB_STEP_SUMMARY` names a file a step appends Markdown to

- **Canonical location:** GitHub Actions documentation, workflow commands — job summaries — `https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `GITHUB_STEP_SUMMARY` holds a path to a file unique to the step;
  content written to it is rendered as Markdown on the run's summary page.
- **Implication for GLOBIN:** Both the evidence gate and the aggregate gate append
  to it when it is set and do nothing when it is not, so the local and CI paths
  are one code path rather than two. It was relied on from Phase 010 and had not
  been recorded until now; this entry closes that gap rather than describing
  anything new.
