# Degraded operation

What GLOBIN may run without, what it refuses to start without, and how it says
which capabilities it lost. Phase 031's titled scope.

This is about **behaviour**, not about a tree. Whether the committed lock could be
installed from local bytes with no network is
[`DEPENDENCY_MATERIALIZATION.md`](DEPENDENCY_MATERIALIZATION.md)'s and was answered
by Phase 029; whether a device is present is
[`GPU_CAPABILITY.md`](GPU_CAPABILITY.md)'s and was answered by Phase 023. What was
left is what a *running* GLOBIN does when something it reaches for is not there.

---

## 1. The gap this closed

Six factories under `src/globin/adapters/` each choose between a working
implementation and a recording stand-in, so that importing the package on a host
with none of the libraries costs nothing:

| Component | Factory |
|---|---|
| `psutil` | `health.system_process_probe` |
| `opentelemetry` | `telemetry_otel.opentelemetry_bridge` |
| `prometheus_client` | `telemetry_prometheus.prometheus_publisher` |
| `kernel32` | `environment.windows_system_api` |
| `advapi32` | `secrets.windows_credential_store` |
| `crypt32` | `secret_vault.secret_vault` |

**Which arm each one took was thrown away.** It survived nowhere except an untyped
dictionary built inside one command, covering two of the six. So GLOBIN could be
running with telemetry export silently unavailable and say nothing about it.

---

## 2. The three tiers

Every component declares one, in
[`degradation-contract.toml`](degradation-contract.toml).

| Necessity | Absent means |
|---|---|
| `required` | The process **refuses to start** |
| `optional` | The process starts, the posture is `degraded`, and the report names what stopped working |
| `opportunistic` | The process starts and the posture stays `ready` |

**`required` has a high bar, and it is deliberately hard to reach:** a component
qualifies only when its absence makes a declared GLOBIN capability both
unperformable **and** unreportable. Every stand-in in the table above still
publishes a truthful record saying what it could not measure, so none of them
blocks today.

**`opportunistic` is not laziness — it is an inherited rule.** Phase 030 established
that a capability the registry *predicted* absent must not make a host amber. The CI
`quality` job installs neither `psutil` nor either telemetry library on any run;
under the obvious rule the posture would be amber for ever, and a signal that is
always amber is a signal nobody reads.

**The observable signal that the tiers were drawn wrongly** is every row declaring
`opportunistic`, at which point `optional` means nothing and should go. Today three
rows are `optional` and one is `required`, so the split is real.

---

## 3. What each absence costs

| Component | Necessity | What is lost |
|---|---|---|
| `psutil` | opportunistic | Process counters unmeasured; the health snapshot still says why |
| `opentelemetry` | optional | `telemetry.export.otlp` |
| `prometheus_client` | optional | `telemetry.export.prometheus` |
| `kernel32` | optional | `environment.native_architecture`, `secrets.vault` |
| `advapi32` | required | `secrets.store` |
| `crypt32` | optional | `secrets.vault` |
| GPU | opportunistic | Nothing |
| Network egress | opportunistic | Nothing |

### `advapi32` is required and currently not applicable, and the pair is the point

Declaring it required outright would make GLOBIN refuse to start on a host where it
presently works, for a capability nothing yet uses — which is building ahead.
Declaring it optional would leave the `required` tier as a member nothing could
produce, which is vocabulary rather than a capability.

So it is declared `required` and **observed** `not_applicable` while
`required_references()` is empty: the question does not arise. The moment Phase 038
registers a reference, the same declaration begins refusing a start. Nothing has to
remember to change a flag — the survey derives it from the registry.

---

## 4. Five answers, not two

Reusing [`ENVIRONMENT_CAPABILITY.md`](ENVIRONMENT_CAPABILITY.md)'s vocabulary rather
than inventing a parallel one.

| Status | Meaning |
|---|---|
| `supported` | It is here |
| `unsupported` | It was looked for and is not here |
| `degraded` | It is here and worse than intended |
| `unknown` | It could **not be measured** |
| `not_applicable` | The question **does not arise** |

The last two are different and the difference is load-bearing. `unknown` never
blocks — a component that could not be measured has not been shown to be absent,
which is ADR-0045's rule. `not_applicable` never degrades, and is what carries the
network, the device and `advapi32` today.

`kernel32` is where `degraded` earns its place: a library that loads **without**
`IsWow64Process2` is not absent, it just cannot answer the native-architecture
question. Nothing reported that distinction before Phase 031.

---

## 5. The network is declared, not probed

GLOBIN makes no outbound call, and that is a **tested property** rather than an
aspiration: an autouse fixture refuses every outbound socket, exactly one module
may name `socket` and cannot spell an address, and the materialization gate reaches
no network *because it imports nothing that could*.

A reachability probe would therefore be two bad things at once. It would be a
mechanism with no caller — the thing ADR-0080 refuses, "a loop with no process to
run in, whose only exercise is its own test" — and it would **remove a guarantee**
the architecture tests currently prove, by adding an outbound connect to a package
that has none.

So the row is declared, observed `not_applicable` with reason "not yet reached", and
the future is written down rather than built:

- When GLOBIN acquires a caller, egress becomes `optional` for market data and
  `required` for order placement.
- **Phase 045** (*REST Transport Layer*) is the first phase with a caller and owns
  measuring it.
- **Phase 297** (*Preflight Verification Gate*) owns refusing a live start on it.

Deliberately absent, and named so nobody adds them for completeness: any socket,
DNS or ICMP probe; captive-portal detection; timeout and retry policy (Phase 043);
per-venue reachability (Phase 036); server-time drift (Phase 040).

---

## 6. How it reports

**One registered check**, `runtime.degradation`, in
[`PREFLIGHT_SUITE.md`](PREFLIGHT_SUITE.md)'s registry at position sixteen — before
the two secrets checks, because *is there a credential store on this machine at
all* is the precondition for *did each reference resolve*. An operator on a host
with no store is told to fix the machine rather than to fix a credential.

Its exit code is **24, `ENVIRONMENT_INCOMPATIBLE`**, reused rather than taking a new
number. That code already means "this host satisfies the runtime contract and lacks
a required capability", which is exactly a refused posture — and `readiness_for` is
total over `ExitCode`, so a new code whose only honest readiness mapping is an
existing reason would be a distinction the readiness surface cannot express. **Code
26 stays free.**

Its durability is `PERISHABLE`: a library can be installed into a running
environment and a device can appear.

The report reaches `globin doctor`, `globin bootstrap check`, `globin bootstrap
preflight` and `bootstrap-manifest.json` through machinery that already existed.
Its headline is `withdrawn` — the union of what every unhappy component lost, as a
bounded sorted list. That is the sentence *GLOBIN started; these named capabilities
are not available*, in a form a machine can read.

**A forgiven absence still appears in the document.** `unmeasured` lists every
component that could not be measured, including the opportunistic ones whose
absence did not move the posture. Forgiving something in the verdict must never mean
hiding it in the record.

---

## 7. What this does not cover

| Question | Where |
|---|---|
| Whether the lock could be installed offline | [`DEPENDENCY_MATERIALIZATION.md`](DEPENDENCY_MATERIALIZATION.md), Phase 029 |
| Whether a GPU is present | [`GPU_CAPABILITY.md`](GPU_CAPABILITY.md), Phase 023 |
| Whether using a GPU pays | [`GPU_BENEFIT.md`](GPU_BENEFIT.md), Phase 024 |
| Whether this host meets the runtime contract | [`ENVIRONMENT_CAPABILITY.md`](ENVIRONMENT_CAPABILITY.md), Phase 028 |
| Whether the network is reachable, measured | Phase 045 |
| Refusing a live start on connectivity | Phase 297 |
| Re-taking a perishable answer on a schedule | Declared by Phase 030; nothing executes it, because no process runs long enough |

---

## Related

- [ADR-0082](../adr/0082-phase-031-widens-to-deliver-the-user-scoped-secret-vault.md) — the amendment that carried this phase
- [ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — why not-knowing is cheap enough to prefer
- [`degradation-contract.toml`](degradation-contract.toml) — the declaration itself
