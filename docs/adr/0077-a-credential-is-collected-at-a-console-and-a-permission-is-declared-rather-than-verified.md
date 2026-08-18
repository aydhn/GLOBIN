# ADR-0077 — A credential is collected at a console, and a permission is declared rather than verified

## Status

Accepted — Phase 029.

**Date:** 2026-08-18

## Context

`ROADMAP.md` row 029 asks for "interactive credential collection, format validation and
permission verification before use". Phase 028 built the store; nothing yet put anything
into it, and nothing decided whether a credential may be used for a given operation.

The third of those three is the hard one. GLOBIN reaches no venue: transport arrives in
Phase 038 and the exchange's own permission model in Phase 039. So "permission
verification" cannot mean asking the issuer.

## Decision

### 1. Collection is interactive only, and three refusals happen before material exists

A non-interactive standard input is refused **before `getpass` is called at all**.
`SECRET_STORE_CONTRACT.md` section 5 permits "interactive entry only"; accepting a pipe
would make a shell one-liner work, which places material in shell history and in the
writing process's command line — both prohibited by `SECURITY_BASELINE.md` section 2.

A platform that cannot suppress echo aborts collection, as section 5 requires. The
implementation reads `getpass`'s own source: `fallback_getpass` calls `warnings.warn`
**before** it prints its notice and **before** it reads. Converting that warning to an
error therefore aborts while the operator has typed nothing — **the value never exists**,
rather than existing and being discarded. That is stronger than the contract asks for.

The confirmation is unconditional. `SecretEntry.collect` takes a prompt and nothing else;
there is no `confirm` flag, because a security control a caller can switch off is not a
control. Equality routes through `SecretValue.__eq__`, which is already
`hmac.compare_digest`, so no new comparison is written.

### 2. Format validation is structural, and no exchange format is invented

`entry_problems` enforces only what is knowable without a venue: non-empty, no surrounding
whitespace, no control characters, within the measured 2560-byte store ceiling, and a
PEM-armoured body over that ceiling reported by name. **There is no minimum length**, because
any number would be invented — what a real key looks like is a fact about a key type, and
choosing one is Phase 038's.

Whitespace is **refused rather than stripped**. Stripping is a transformation nobody asked
for, and it would make a credential whose true value carries leading whitespace both
unstorable and unreportable.

A measured consequence worth recording: a real PEM document is multi-line, so it trips the
control-character rule as well as the size rule. **Armoured key material cannot be collected
at a single-line console prompt at all**, whatever its size. A phase that needs to accept one
must add a route that is not this.

### 3. Permission verification is containment, and there is no confirmed state

The local guarantee is exactly one sentence:

> GLOBIN refuses to resolve a credential for an operation whose demanded grants are not a
> subset of the grants declared for it, and never claims the converse.

`VerificationState` has four members — `DECLARED`, `UNDECLARED`, `INSUFFICIENT`,
`WITHHELD` — and **none of them means confirmed**. ADR-0045 makes a platform capability a
recorded state rather than a pass; this takes the same rule one step further, because
ADR-0045 keeps a passing member for a capability that genuinely can be probed and here
nothing can. The rule is enforced by the *absence of a name*: no one can write `if state is
CONFIRMED` and proceed, because there is nothing to write.

`SECURITY_BASELINE.md` section 4 becomes a branch rather than a paragraph.
`withheld_grants()` returns `(Grant.TRANSFER,)`, and a demanded transfer yields `WITHHELD`
**whatever the declaration says**. It is checked *first*, before the declaration is
consulted, so that no edit could make it satisfiable by declaring the grant.

`require_permitted` computes the verdict and **returns without touching the store** when it
refuses. There is no branch in which material is resolved and then discarded; a unit test
asserts the store recorded zero calls.

### 4. Grants are separate types, not a field on a reference

`SecretReference` is ordered and is what `store_key` folds into a platform key. A `grants`
field would make two references with the same store key compare unequal, breaking the
inventory and the rotation procedure at once. So `CredentialRequirement` (what a use site
demands) and `GrantDeclaration` (what an operator states) name a reference rather than
extending it.

### 5. `required` stays empty, and the emptiness becomes a derivation

`required_credentials()` returns nothing, because GLOBIN reaches no venue and therefore
genuinely needs no credential to start. Declaring one would make `bootstrap check` refuse on
every clean host including CI's, satisfiable only by manufacturing a credential to meet a
requirement nothing established.

What changed is that the emptiness is now *derived*: the composition root feeds the registry
into `StoreBackedSecrets.required` and into the entitlement probe, so Phase 038 adds one
entry and start-up begins demanding it with no plumbing in between. **That wiring is the
deliverable**, not a non-empty tuple.

### 6. The module-name rule narrows from five words to four

ADR-0073 forbade `credential` as a module name "because credential handling is still absent
and still Phase 029's", and handed the decision here by name. This is the phase that builds
credential handling, so keeping the word forbidden would make the tree lie about itself —
the identical argument that admitted `secret` at Phase 028.

`password`, `token`, `keyring` and `apikey` stay forbidden. **No module in this phase is
named `credential*`**: permission is granted so the rule stops being a trap, not so a file
gets renamed.

### 7. `getpass` joins the I/O-capable list

`docs/architecture/dependency-rules.toml` did not name it, so nothing stopped
`globin.domain` importing a module that reads standard input and on POSIX opens `/dev/tty`.
It is listed now, in the phase that first had a reason to call it.

## Consequences

Exit code **25**, `CREDENTIAL_NOT_ENTITLED`, and it is deliberately not 15. A launcher
meeting 15 must go and store a credential; one meeting 25 must go and change a key's
permissions at the venue. Different remedies, different codes.

The command group is exactly `SECRET_STORE_CONTRACT.md` section 5's list — set, verify,
list, delete, rotate, health — with a contract test comparing the tuple against it, so a
seventh verb cannot arrive without the contract changing first. `--json` is refused for
`set` and `rotate`: a command whose primary act is a prompt has no document for standard
output, and offering one invites scripting it.

`--environment` is never defaulted from `--profile`. A profile names a *document*; an
environment names a deployment target, and what an environment guarantees is Phase 035's.

## Risks and Trade-offs

**The Windows happy path is not unit-testable.** `win_getpass` begins `if sys.stdin is not
sys.__stdin__: return fallback_getpass(...)`, and pytest always replaces `sys.stdin`. Only
the refusals can be exercised under the suite, which is why the echo-suppressed read is one
line behind a seam.

**`win_getpass` ignores the stream it is handed**, writing its prompt with `msvcrt.putwch`.
The prompt therefore reaches the console rather than the injected stream on Windows. It
never reaches standard output, so the `--json` contract holds, but the injection is not the
guarantee it looks like on that platform.

**A declaration is unverified, and the type says so but a reader may not.**
`VerificationState.DECLARED` is documented as "the operator stated this; nothing has checked
it". The mitigation is the absent member; the residual risk is somebody reading `DECLARED`
as approval. Phase 039 is where an answer that has been checked becomes possible.

## Alternatives Considered

**A capability token minted locally.** Rejected: a token attests only that GLOBIN minted it.
It would add a type, a lifetime and a revocation question and answer none of them with
evidence — ADR-0045's "reporting them as passing because they could not be checked", in a
cryptographic costume.

**Grants on `SecretReference`.** Rejected for the key-collision reason in decision 4.

**Stripping whitespace rather than refusing it.** Rejected: it makes a credential whose true
value has whitespace unstorable and hides the correction from the operator.

**A retry loop on mismatch.** Rejected: a loop means the value is typed up to N times, each
one more chance for a terminal to have echo on, and it invites a `max_attempts` setting that
would want to live in configuration.

**A `[credentials]` configuration section.** Rejected: `CONFIGURATION_LAYOUT.md` forbids "no
credential of any kind, **and no reference to one**" in `config/`, and a
retype-confirmation toggle a committed file could switch off is not a control.

## References

- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — the rule this takes one step further
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — the secret-handling rules
- [ADR-0074](0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) — the store this fills
- [ADR-0076](0076-phase-029-widens-to-deliver-the-dependency-attestation.md) — the widening record
- [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md) — sections 5 and 6, which this satisfies
- [`../security/CREDENTIAL_FLOW.md`](../security/CREDENTIAL_FLOW.md) — how to use it
- [`../research/phase_029_sources.md`](../research/phase_029_sources.md) — the `getpass` behaviour, measured

## Supersedes

Nothing.

## Superseded By

Nothing.
