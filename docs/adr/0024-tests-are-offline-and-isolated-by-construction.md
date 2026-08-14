# ADR-0024 — Tests are offline and process-isolated by construction, not by convention

## Status

Accepted — Phase 005.

**Date:** 2026-08-14

## Context

[`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) has stated since Phase 004 that
no test at any level existing today may touch the network, and that running one
test alone must give the same result as running it in the middle of the suite.
Both were rules a contributor had to remember. Neither was enforced.

The rules matter more than most, because breaking them does not produce a failing
test. A test that reaches a real service passes on the machine that wrote it and
fails somewhere else — in CI, behind a proxy, on an aeroplane, or against a rate
limit. Once Phases 033-048 add credentials, the same mistake sends
authenticated traffic to a venue from a test run. A test that leaks an
environment variable or changes the working directory produces a failure in a
*different* test, one that did nothing wrong, and the suite passes or fails
depending on selection and order.

The repository's own position on this is unambiguous: *"a validator whose
negative case is never exercised is indistinguishable from one that cannot
fail"*. A rule with no negative case at all is weaker still.

## Decision

**1. Two autouse fixtures in `tests/conftest.py`, and no others.** Every autouse
fixture is paid for by the whole suite, so the bar is that it must be impossible
to place anywhere narrower. Both clear it: a guarantee that holds for most of the
suite is not a guarantee.

**2. `block_network` refuses outbound connections.** It replaces
`socket.socket.connect`, `socket.socket.connect_ex` and
`socket.create_connection` for the duration of each test. Tests marked `external`
or `network` opt out, so the guard has a documented door rather than acquiring an
undocumented one later under deadline.

**3. The refusal is a `pytest.fail`, not an `OSError`.** A realistic connection
error is exactly what retry and backoff code is written to swallow. The moment
such code exists — Phases 033-048 — an `OSError`-based guard would be absorbed by
the code under test, and the suite would go on reporting itself offline while
doing nothing of the kind. `Failed` derives from `BaseException`, so no
`except Exception` reaches it.

**4. Name resolution is not blocked.** Nothing can act on a resolved address
without then connecting, so blocking the connection is sufficient, and blocking
DNS as well would replace a specific message with a vaguer one.

**5. `isolate_process_state` restores the environment and working directory, and
fails the test that moved them.** Both jobs are necessary and they are different:
restoring alone keeps the suite green while the leak stays, and failing alone
names the culprit and then lets the damage reach every test afterwards. Doing
both names the culprit while the leak is on screen and stops it spreading.

**6. The drift detection is a pure function in `tests/support.py`, not logic
inside the fixture.** A checker that runs in teardown is the easiest place in a
suite for a silent failure to hide, so it is separated out and given its own
tests — including the case where the working directory no longer exists, which
makes `Path.cwd()` raise.

**7. `block_network` must not use `monkeypatch`.** This is the non-obvious part
and the reason it is recorded rather than left as a comment. pytest hoists an
autouse fixture's dependencies to the front of the fixture closure, so requesting
`monkeypatch` there makes it the first fixture set up and therefore the last torn
down — after `isolate_process_state` has already inspected the environment. Every
test calling `monkeypatch.setenv` would then be reported as leaking a variable
`monkeypatch` was about to remove. This was found by writing the guard the
obvious way and watching it fail.

**8. Each guard ships with its failing case and, where it has one, its opt-out
exercised.** `tests/contract/test_isolation_contract.py` attempts a connection
and asserts refusal, asserts the patch is installed during an ordinary test,
asserts a `network`-marked test keeps the real socket, and drives the drift
detector through added, removed, altered, moved and deleted-directory cases.

## Consequences

- Two fixtures now run for every test in the suite. Both are a dictionary
  comparison and three attribute swaps; the measured cost is not visible against
  a suite that runs in under nine seconds.
- A test that genuinely needs the network cannot be written without a marker, and
  the marker is registered, so `--strict-markers` means it cannot be typed
  wrongly either.
- The `external` marker's registered description — "skipped by default" — became
  true in this phase. It had been false since Phase 004: nothing deselected it,
  and `addopts` carried no `-m` filter. The exclusion is composed into each
  expression in the command table, because a command-line `-m unit` would
  override an `addopts` `-m` and the exclusion would vanish from exactly the
  selective runs.
- Contributors must use `monkeypatch.setenv` and `monkeypatch.chdir` rather than
  changing state directly. That was already the advice; it is now the only thing
  that works.
- The guard patches this interpreter only. A test spawning a subprocess that
  reaches the network is unaffected, and nothing detects it.

## Alternatives Considered

**Adopt `pytest-socket`.** A maintained plugin doing roughly this. Rejected: it
is a seventh development dependency for fifteen lines of standard library, it
raises its own `SocketBlockedError` deriving from `Exception` — which reintroduces
the swallowing problem decision 3 exists to avoid — and its opt-out is a marker
GLOBIN would have to register anyway.

**Block at a lower level**, patching `socket.socket.__init__` so a socket cannot
be created at all. Rejected as too broad. Creating a socket is not reaching the
network, some standard library code constructs sockets it never connects, and the
failure would arrive at a confusing place.

**Fail the run rather than the test.** Rejected. Failing the individual test names
the culprit and lets the rest of the suite report, which is more information, not
less.

**Detect leaks without repairing them.** Rejected. It names the culprit correctly
and then lets the next twenty tests fail for reasons that have nothing to do with
them, which is the cascade that makes order-dependence hard to diagnose.

**Repair leaks without failing.** Rejected for the opposite reason: the suite
stays green, the leak stays in the code, and the fixture quietly does the test's
cleanup forever.

## Risks and Trade-offs

The characteristic failure mode is a guard that is technically installed and
practically bypassed. Three routes exist today: a subprocess, a library that
reaches the network through something other than these three entry points (an
extension module holding its own socket, for instance), and a future contributor
adding `external` to a test to make it pass rather than because it belongs at the
external level. None is detectable by this design.

The observable signal is a test whose behaviour differs between a developer's
machine and CI while both report the suite as offline — or an `external` marker
appearing on a test that has no external system to talk to, which is why the
marker's meaning is stated in the registry rather than left to inference.

A second risk is specific to decision 7. The `monkeypatch` interaction is a
property of pytest's fixture ordering, not of this repository, and a future
pytest could change it. The failure would be loud rather than silent — every test
using `monkeypatch.setenv` would error in teardown — which is the better
direction, but the fix would not be obvious to someone who has not read this
record. That is why it is a numbered decision rather than a comment.

## References

- [ADR-0017](0017-test-taxonomy-as-directories.md) — the marker mechanism the
  opt-out relies on.
- [ADR-0019](0019-single-quality-entrypoint.md) — why the `external` exclusion
  belongs in the command table.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the scope
  under which these guards were delivered.
- [`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) — the offline and
  determinism rules these fixtures enforce, and the "guard every checker with its
  failing case" principle.
- [`../research/phase_005_sources.md`](../research/phase_005_sources.md) — the
  pytest fixture and marker documentation consulted.

## Supersedes

None.

## Superseded By

None.
