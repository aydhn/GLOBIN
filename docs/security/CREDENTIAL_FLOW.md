# Credential Flow

How a credential gets into GLOBIN, what is checked before it is stored, and what
decides whether it may be used. Delivered in Phase 029;
[ADR-0077](../adr/0077-a-credential-is-collected-at-a-console-and-a-permission-is-declared-rather-than-verified.md)
records the reasoning.

**GLOBIN still holds no credentials.** It has somewhere to put one
([`SECRET_STORE.md`](SECRET_STORE.md)) and now a way to be handed one, which is a
different thing again. Nothing in this document connects to an exchange.

---

## The commands

Seven verbs, and no eighth. `SECRET_STORE_CONTRACT.md` section 5 permits exactly
these, and a contract test compares the command tuple against that list — so an
eighth cannot arrive without the contract changing first.

**The seventh arrived in Phase 031 and the order is what matters**: section 5 was
amended in the same commit that added `doctor`, not afterwards. A command surface
that grew first and was described later would be a contract following the code.
`doctor` is not `health` with a wider remit — `health` answers whether *a* backend
can be reached, and `doctor` answers which of the several mechanisms this host has
and what each will do. It reads nothing an operator stored and emits no value.

```bash
.venv\Scripts\globin.exe secrets set --environment paper --kind api_key --name venue_key
```

```bash
.venv\Scripts\globin.exe secrets rotate --environment paper --kind api_key --name venue_key
```

```bash
.venv\Scripts\globin.exe secrets verify --environment paper --kind api_key --name venue_key --json
```

```bash
.venv\Scripts\globin.exe secrets list --json
```

```bash
.venv\Scripts\globin.exe secrets delete --environment paper --kind api_key --name venue_key
```

```bash
.venv\Scripts\globin.exe secrets health --json
```

```bash
.venv\Scripts\globin.exe secrets doctor
```

Since Phase 031 there are three mechanisms rather than one, and `--provider` says
which holds the credential being addressed — `credential_manager`,
`dpapi_vault` or `environment`. Omitted, the credential manager is used, which is
what every earlier invocation got and what it still gets.

```bash
.venv\Scripts\globin.exe secrets verify --environment paper --kind private_key --name venue_signing_key --provider dpapi_vault
```

### Enrolling a key that cannot be typed

A PEM private key is multi-line by definition, so the interactive rules refuse one
whatever its size — this document used to say, correctly, that "a real PEM key
cannot be collected here at all". The vault exists for exactly that material, so
Phase 031 added the route that makes it reachable.

```bash
.venv\Scripts\globin.exe secrets set --environment paper --kind private_key --name venue_signing_key --provider dpapi_vault --from-file C:\keys\venue.pem
```

`--from-file` carries a **path, never material**. Section 5 forbids an option that
would place a *value* on a command line; a filename is ordinary data, and the file
is opened by this process rather than by the shell, so nothing reaches the process
table or shell history.

Three refusals apply, and one of them is about you rather than about the file:

- **A path inside a GLOBIN checkout is refused.** A private key in a working tree
  is one `git add -A` from being permanent, and rule 1 of
  [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md) is absolute about that. Refusing
  the source is the only point at which GLOBIN can act on it.
- **Line breaks are permitted and nothing else is.** A control character other
  than a line break means the file is not what you thought it was.
- **A trailing newline is tolerated and removed.** Every editor writes one and a
  PEM file conventionally ends with one; leading whitespace is still refused,
  because it is not conventional and it changes the key.

**Deleting the source file afterwards is yours to do.** GLOBIN does not delete it,
does not move it, and does not report where it was — a path names a machine and
often a person. Nothing here should be read as GLOBIN having tidied up after you.

**A mechanism name is not material**, which is why section 5 permits the option on
the same reading that permits `--environment` and `--kind`. And a write against a
mechanism that never accepts one — the environment hand-off — is refused **before
the operator is prompted**, so the material never exists rather than existing and
being discarded.

`--json` is **refused** for `set` and `rotate`, as it already is for
`bootstrap evidence` and `diagnostics bundle`. A command whose primary act is an
interactive prompt has no document for standard output, and offering one invites
somebody to script a prompt.

`--environment` is **never defaulted from `--profile`**. A profile names a
configuration *document*; an environment names a deployment target, and what an
environment guarantees is Phase 035's question.

---

## What happens when you type a credential

Three refusals happen before any material exists.

**A pipe is refused, and `getpass` is never called.** Collection is interactive
only. Accepting a pipe would make a shell one-liner work, which places material in
shell history and in the writing process's command line — both prohibited by
[`SECURITY_BASELINE.md`](SECURITY_BASELINE.md) section 2. The exit code is `15`.

**A terminal that cannot hide what you type aborts before you type it.**
`getpass`'s fallback emits `GetPassWarning` *before* it prints its notice and
*before* it reads; GLOBIN turns that warning into an error, so the abort happens
while nothing has been typed. The value never exists, rather than existing and
being discarded.

**The material is asked for twice, always.** There is no flag that turns the
confirmation off, because a security control a caller can weaken is not a control.
The two entries are compared with `hmac.compare_digest`, inherited from
`SecretValue.__eq__` rather than written again.

If the second entry differs — or is itself malformed — the answer is `mismatch`
and nothing more. The second entry's shape is never disclosed.

### What is checked about the material

| Refused | Why |
|---|---|
| Empty | There is nothing to store |
| Leading or trailing whitespace | **Refused, not stripped.** A paste from a browser routinely carries a newline, and silently removing it produces a credential wrong in a way nothing downstream can see |
| Control characters | A paste accident or a terminal artefact — and, once Phase 038 signs a request with it, a request-splitting hazard |
| Over 2560 bytes | The measured platform ceiling. Over it, Windows answers with an **undocumented** `RPC_X_BAD_STUB_DATA` that names neither the size nor the limit |
| A PEM key over the ceiling | Reported by name, so the message says what it is rather than leaving the platform fault to be decoded |

**There is no minimum length**, and that is deliberate: any number would be
invented. What a real key looks like is a fact about a key type, and choosing one
is Phase 038's.

**A PEM key cannot be collected here at all.** A real PEM document is multi-line,
so it trips the control-character rule whatever its size. That is a genuine limit
of a single-line console prompt, and a phase needing armoured key material must
add a different route.

**No reported problem carries any part of what you typed.** A length is
publishable; an offset or a substring is not.

---

## Permission verification, and what it cannot be

`ROADMAP.md` row 029 asks for "permission verification before use". GLOBIN reaches
no venue — transport is Phase 038, the exchange's permission model Phase 039 — so
this cannot mean asking the issuer. What it means is:

> GLOBIN refuses to resolve a credential for an operation whose demanded grants
> are not a subset of the grants declared for it, and **never claims the
> converse**.

Containment is decidable here. The truth of the declaration is not.

### There is no state meaning "confirmed"

| State | Meaning |
|---|---|
| `declared` | The operator wrote down what this key carries, and the demand fits inside it. **Nothing has checked the writing.** |
| `undeclared` | Nothing is on record, so nothing may be assumed |
| `insufficient` | A declaration exists and does not cover what is demanded |
| `withheld` | GLOBIN refuses this permission class outright |

Four members, and **none of them means the venue agrees**. ADR-0045 makes a
platform capability a recorded state rather than a pass; here the rule is enforced
by the absence of a name — nobody can write `if state is CONFIRMED` and proceed,
because there is nothing to write. Phase 039 is where an answer that has been
checked becomes possible, and it will add the member along with the ability to
earn it.

### One refusal outranks every declaration

`SECURITY_BASELINE.md` section 4 withholds any permission that lets funds leave
the account. That is a branch, not a paragraph: a demanded `transfer` is `withheld`
**whatever the declaration says**, and it is checked *before* the declaration is
consulted so that no edit could make it satisfiable by declaring the grant.

Exit code **25**, `CREDENTIAL_NOT_ENTITLED`, and deliberately not `15`. A launcher
meeting `15` must go and store a credential; one meeting `25` must go and change a
key's permissions at the venue.

### Nothing reaches the store on a refusal

`require_permitted` computes the verdict first and returns **without touching the
store** when it refuses. There is no branch in which material is resolved and then
discarded, and a unit test asserts the store recorded zero calls.

---

## What a start-up requires today: nothing

`globin.domain.entitlements.required_credentials()` returns an empty tuple, so
`bootstrap check` passes both `secrets.required` and `secrets.entitlement`
vacuously and says so in the summary.

**The emptiness is a derivation rather than a literal**, and that is this phase's
deliverable. The composition root feeds the registry into the store's declared
references and into the entitlement probe, so the phase that has a real
requirement adds one entry and start-up begins demanding it with no plumbing in
between. Phase 038 brings the first authenticated surface.

Declaring one now would make `bootstrap check` refuse on every clean host,
including the one CI builds, and the only way to satisfy it would be to
manufacture a credential to meet a requirement nothing has established.

---

## Where the declaration lives

Grant declarations are kept in the user-local runtime state area — deliberately
**not** `.globin/`, which is evidence about this repository and is read by CI.

That file cannot carry a secret, and the proof is structural rather than
procedural: a `GrantDeclaration` has two fields, a reference and a set of bounded
enum members. There is no field a value could occupy, no branch that could write
one, and `SecretValue` is unhashable with no encoder, so it could not become a key
or be serialised even by accident.

A document this version does not recognise is read as *nothing declared* rather
than raised on — the refusing direction, since with no declaration `verify`
answers `undeclared` and use is refused.

---

## Troubleshooting

| Symptom | What it means |
|---|---|
| `not_interactive`, exit 15 | Standard input is not a terminal. Run it at a console; a pipe is refused by design |
| `echo_unavailable` | The terminal cannot hide input, so nothing was read. Use a console that can |
| `mismatch` | The two entries differed. Nothing was stored |
| `refused_format` | The material broke a rule above. The problems are named; no part of what you typed is shown |
| `backend_unavailable` | The credential store could not be reached. `globin secrets health` reports it directly |
| Exit 25 at `bootstrap check` | A required credential is not permitted to do what GLOBIN asks. Declare what the key carries, or narrow the operation |

---

## What this does not cover

| Question | Owner |
|---|---|
| Which key type is used against which exchange surface | Phase 038 |
| Whether a venue agrees a key carries the permissions declared for it | Phase 039 |
| What an environment is, and how production and testnet differ | Phase 035 |
| Accepting armoured key material that does not fit a single-line prompt | Unowned; see the note above |
