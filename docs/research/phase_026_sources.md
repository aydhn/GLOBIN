# Phase 026 — Source Ledger

Every claim Phase 026 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

The phase has two halves. The configuration half rests on almost nothing external —
it is a layout decision plus `tomllib`, which Phase 007 already recorded. The
telemetry half rests on four packages, two provider specifications and two CPython
facilities, and those are what follows.

**Three entries record something measured on this host rather than read.** S-05,
S-07 and S-08 were obtained by resolving and inspecting the installed
distributions, because in each case the published documentation either does not
state the fact or states it less precisely than the code does. **S-07 is the one
worth reading first**: the security posture of the whole listener feature turns on
it, and it is not in the documentation at all.

**One entry records a trap.** S-03 is a dependency that existed until recently and
does not now, and a review written from memory would have declared it.

---

## The packages

### S-01 — `opentelemetry-api` 1.44.0 requires one distribution and caps no Python

- **Canonical location:** https://pypi.org/pypi/opentelemetry-api/1.44.0/json
- **Accessed:** 2026-08-17
- **Authority:** Primary — the index's own metadata for one release.
- **Supports:** `requires_python` is `>=3.10` with **no upper bound**.
  `requires_dist` is `["typing-extensions>=4.0"]` and nothing else.
  `license_expression` is `Apache-2.0`. The wheel is
  `opentelemetry_api-1.44.0-py3-none-any.whl`, uploaded 2026-07-16, not yanked.

- **Implication for GLOBIN:** the absence of an upper bound is what matters. Phase
  018 found the entire `binance-sdk-*` family declares `<3.15`, so an unbounded
  `requires_python` is a fact worth recording rather than assuming — it means the
  pinned 3.14 line and CI's 3.12 leg are both served, and that a later interpreter
  move is not blocked by this package.

### S-02 — `prometheus-client` 0.26.0 has no unconditional dependency

- **Canonical location:** https://pypi.org/pypi/prometheus-client/0.26.0/json
- **Accessed:** 2026-08-17
- **Authority:** Primary — the index's own metadata for one release.
- **Supports:** `requires_python` is `>=3.9`. All three `requires_dist` entries sit
  behind extras (`twisted`, `aiohttp`, `django`), so the installed set is one
  distribution. `license_expression` is `Apache-2.0 AND BSD-2-Clause`. The
  classifier is `Development Status :: 4 - Beta`. The wheel is
  `prometheus_client-0.26.0-py3-none-any.whl`, uploaded 2026-07-24, not yanked.

- **Implication for GLOBIN:** two things. The compound licence had to be written
  into `DEPENDENCY_POLICY.md` **verbatim**, because
  `test_supply_contract.py::test_every_licence_is_permitted_by_the_policy` looks
  for the recorded expression as a literal string rather than for its components —
  so a compound is permitted by being *named*, one at a time. And the beta
  classifier contradicts the pedigree: this is Prometheus's own client under CNCF
  governance, still at `0.x` after a decade, and the review records that rather
  than letting the reputation answer question 3.

### S-03 — `opentelemetry-api` dropped `importlib-metadata` at 1.42.0, and a review written from memory would have been wrong

- **Canonical location:** https://pypi.org/pypi/opentelemetry-api/1.41.0/json and
  https://pypi.org/pypi/opentelemetry-api/1.42.0/json
- **Accessed:** 2026-08-17
- **Authority:** Primary — the index's own metadata for two adjacent releases.
- **Supports:** through 1.41.0, `requires_dist` included
  `importlib-metadata<8.8.0,>=6.0` unconditionally alongside `typing-extensions`.
  At 1.42.0 that entry is gone, and the same release raised `requires_python` from
  `>=3.9` to `>=3.10`.

- **Implication for GLOBIN:** this is the Phase 025 S-05 shape — a fact that was
  true recently enough to be remembered wrongly. The written review answers
  question 1 with *one* distribution, and the only instrument that would have
  caught a stale answer is the `pylock.toml` diff. Recorded so the next reader
  knows the count was checked rather than recalled.

### S-04 — the OTLP HTTP exporter's requirements, and why the variant is named rather than the meta-package

- **Canonical location:** https://pypi.org/pypi/opentelemetry-exporter-otlp-proto-http/1.44.0/json
- **Accessed:** 2026-08-17
- **Authority:** Primary — the index's own metadata for one release.
- **Supports:** `requires_python` `>=3.10`; `requires_dist` names
  `googleapis-common-protos~=1.52`, `opentelemetry-api~=1.15`,
  `opentelemetry-exporter-otlp-proto-common==1.44.0`, `opentelemetry-proto==1.44.0`,
  `opentelemetry-sdk~=1.44.0`, `requests~=2.7` and `typing-extensions>=4.5.0`.
  `license_expression` is `Apache-2.0`. The wheel is `py3-none-any`.

- **Implication for GLOBIN:** `grpcio` appears nowhere in that list, which is the
  whole reason `pyproject.toml` names this variant rather than the
  `opentelemetry-exporter-otlp` meta-package: the meta-package pulls both
  transports, and the gRPC half adds a large compiled distribution whose wheel
  availability is a per-release question on a new interpreter line.

---

## What the resolution actually produced

### S-05 — the transitive set, measured on this interpreter rather than inferred

- **Canonical location:** `pip install --dry-run --ignore-installed --report`, run
  against `.venv\Scripts\python.exe` (CPython 3.14.5, `win_amd64`), pip 26.1.2.
- **Accessed:** 2026-08-17
- **Authority:** Primary — a resolution performed on the target interpreter. This is
  stronger than reading `requires_dist`, because it is what would actually land.
- **Supports:** fifteen distributions resolve from the four declared roots:
  `certifi 2026.7.22`, `charset-normalizer 3.5.1`, `googleapis-common-protos 1.75.1`,
  `idna 3.18`, `opentelemetry-api 1.44.0`,
  `opentelemetry-exporter-otlp-proto-common 1.44.0`,
  `opentelemetry-exporter-otlp-proto-http 1.44.0`, `opentelemetry-proto 1.44.0`,
  `opentelemetry-sdk 1.44.0`, `opentelemetry-semantic-conventions 0.65b0`,
  `prometheus_client 0.26.0`, `protobuf 7.35.1`, `requests 2.34.2`,
  `typing_extensions 4.16.0`, `urllib3 2.7.0`.

  **Exactly two are compiled**, and neither needs a compiler here:
  `charset_normalizer-3.5.1-cp314-cp314-win_amd64.whl` is a native wheel for the
  pinned interpreter, and `protobuf-7.35.1-cp310-abi3-win_amd64.whl` is a
  **stable-ABI** wheel that serves 3.14 through a tag that does not name it.

- **Implication for GLOBIN:** `pylock.toml` goes from eleven distributions to
  twenty-six, and the owner was given that number before the choice was confirmed.
  The `protobuf` tag is also the Phase 018 lesson arriving from the other side: a
  survey grepping for `cp314` would report a gap that does not exist, which is why
  the wheel matcher parses PEP 425 tags rather than matching substrings.

  One arrival is worth naming separately: `opentelemetry-semantic-conventions`
  resolves to **0.65b0**, and the `b` is a beta marker rather than a typo. That is
  precisely the hazard the phase brief warned about — an experimental convention
  becoming a permanent contract — and it is why GLOBIN's names live in its own
  `globin.*` namespace and nothing under `src/globin` imports that package.

---

## The two facts the documentation does not state

### S-06 — an asyncio task copies the current context, and runs its coroutine in the copy

- **Canonical location:** https://docs.python.org/3/library/asyncio-task.html
- **Accessed:** 2026-08-17
- **Authority:** Primary — CPython's own library reference.
- **Supports:** for `asyncio.Task`: *"An optional keyword-only context argument
  allows specifying a custom contextvars.Context for the coro to run in. If no
  context is provided, the Task copies the current context and later runs its
  coroutine in the copied context."* `asyncio.create_task` states the same.

- **Implication for GLOBIN:** this is what makes span nesting work across an
  `await`, and it is also what makes it **testable without an event loop**. Starting
  a loop in this suite fails: on Windows the default is `ProactorEventLoop`, whose
  self-pipe is built from `socket.socketpair()`, whose Windows fallback calls
  `connect()` — which `tests/conftest.py::block_network` turns into a failure, and
  the `network` marker's own declaration forbids it below the external level. Since
  a task's mechanism *is* `copy_context()`, testing against that call exercises the
  identical behaviour with no loop, no socket and no marker.

### S-07 — `prometheus_client.start_http_server` binds every interface by default, and runs on daemon threads

- **Canonical location:** the installed `prometheus_client.exposition` module,
  version 0.26.0, inspected on this host. The published documentation at
  https://prometheus.github.io/client_python/exporting/http/ shows only
  `start_http_server(8000)` and does **not** state the address default at all.
- **Accessed:** 2026-08-17
- **Authority:** Primary — the code that runs, which is more precise here than the
  documentation.
- **Supports:** the signature is
  `start_http_server(port: int, addr: str = '0.0.0.0', registry=..., certfile=None, ...)`.
  `start_wsgi_server` carries the same default. The server thread is created with
  `t.daemon = True`, and `ThreadingWSGIServer` sets `daemon_threads = True` with the
  comment that it prevents a memory leak from `ThreadingMixIn` gathering non-daemon
  threads.

- **Implication for GLOBIN:** two decisions rest entirely on this. The listener
  passes `127.0.0.1` as a **literal** and GLOBIN exposes no address setting, because
  the library's default is every interface and "remember to pass the loopback
  address" is exactly the class of mitigation this repository refuses. And the
  daemon-thread behaviour is a **documented deviation** rather than an inherited
  one: `adapters/watchdog.py` argues GLOBIN's own threads must be non-daemon, and
  this library's are not — so the listener is off by default and its threads are
  the library's rather than GLOBIN's.

  `tests/architecture/test_library_discipline.py` asserts the literal is present,
  the wildcard is absent outside the comment explaining why, and that no *other*
  route to a listener exists — because what has to be prevented is a second call
  site appearing that does not carry the argument.

### S-08 — the installed OpenTelemetry API returns working no-op instruments with no SDK

- **Canonical location:** the installed `opentelemetry.metrics` module, version
  1.44.0, exercised on this host.
- **Accessed:** 2026-08-17
- **Authority:** Primary — the behaviour observed, rather than the specification's
  description of it.
- **Supports:** `opentelemetry.metrics.get_meter("globin")` returns a meter without
  an SDK installed, and `create_counter` and `create_histogram` on it return
  instrument objects whose `add` and `record` accept values and do nothing.

- **Implication for GLOBIN:** this is what makes "no socket in a default bootstrap"
  **structural** rather than configured. GLOBIN publishes through the API; whoever
  embeds GLOBIN installs an SDK and owns the network decision. It also means the
  bridge needs no guard at every call site — the absence of a pipeline is the
  library's no-op rather than GLOBIN's branch.

---

## The two specifications

### S-09 — OpenTelemetry's instrument kinds and their semantics

- **Canonical location:** https://opentelemetry.io/docs/specs/otel/metrics/data-model/
- **Accessed:** 2026-08-17
- **Authority:** Primary — the specification itself.
- **Supports:** the data model distinguishes monotonic sums (counters), non-monotonic
  gauges and explicit-bucket histograms, and defines histogram buckets as
  upper-inclusive under an `le`-style boundary.

- **Implication for GLOBIN:** the three kinds GLOBIN declares map one-to-one, and
  bucket placement is upper-inclusive and non-cumulative so an exporter re-derives
  nothing. `SpanStatus` borrows the specification's three members exactly, for the
  reason `Severity` borrowed `logging`'s numbers: a mapping table between two
  enumerations is a thing that drifts.

  **Deliberately not adopted:** the semantic conventions' attribute names. Those
  carry per-group stability markers, and the phase brief is explicit that an
  experimental convention must not become this repository's permanent contract. The
  mapping is a declared table, so adopting any of them later is an edit to that
  table rather than a change to the domain.

### S-10 — Prometheus metric and label naming

- **Canonical location:** https://prometheus.io/docs/practices/naming/ and
  https://prometheus.io/docs/concepts/data_model/
- **Accessed:** 2026-08-17
- **Authority:** Primary — the project's own guidance and data model.
- **Supports:** metric names match `[a-zA-Z_:][a-zA-Z0-9_:]*`; base units are
  preferred (seconds, bytes); a counter carries a `_total` suffix; labels with
  unbounded value sets are the documented cause of cardinality explosion.

- **Implication for GLOBIN:** the counter suffix and base-unit rules are enforced on
  the descriptor rather than left to convention, so a gauge cannot be named `total`
  and a metric denominated in anything but `count` must carry its unit's suffix. The
  name mapping is **declared beside** the canonical name rather than derived from
  it, because `globin.a.b_c` and `globin.a.b.c` both flatten to `globin_a_b_c` — a
  collision a derived mapping would make silently, and a declared one makes a
  failing test.

---

## Recorded as unread

**The OpenTelemetry semantic-conventions registry, group by group.** GLOBIN adopts
none of its attribute names, so their individual stability markers were not
enumerated. The decision not to depend on them makes the enumeration unnecessary
rather than merely inconvenient — but it was not done, and this says so rather than
leaving an impression that it was.
