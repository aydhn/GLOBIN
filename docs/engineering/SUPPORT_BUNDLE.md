# Support Bundle

The archive an operator sends somewhere when GLOBIN has misbehaved, and everything
that is deliberately not in it.

```bash
.venv\Scripts\globin.exe diagnostics bundle
```

That one sentence at the top contains the whole threat model: the file leaves the
machine, it leaves because something is already wrong, and the person sending it
is not going to audit the contents first. Every decision below follows from those
three facts.

---

## Allowlist, never denylist

A collector that zipped the runtime tree and excluded known-bad names would be one
unanticipated file away from shipping it. `ArtifactKind` enumerates what may be
included, `bundle_candidates` in the composition root is the table naming every
file, and anything without a kind is excluded with a recorded reason.

**There is no directory walk anywhere.** That is what makes the guarantee
checkable: a reviewer reads the table and knows the whole set, rather than
reasoning about what a filter might have let through. The rotated logs are the one
group not written out name by name, and they are still bounded — by the rotation
policy's own backup count — and every member name is built through
`safe_member_name` rather than taken from a directory listing.

| Kind | What it is |
|---|---|
| `snapshot` | The canonical runtime health snapshot |
| `manifest` | The bundle's own index |
| `report` | The human-readable generation report, including what was left out |
| `log` | The live runtime log, redacted line by line |
| `rotated_log` | A rotated predecessor, under the same treatment |
| `fault` | The `faulthandler` text file, path-sanitised |
| `lifecycle` | The Phase 022 lifecycle record |
| `diagnostics` | The Phase 023 subsystem's record of itself |
| `bootstrap` | The Phase 021 manifest, which explains why the process started |

---

## What never goes in

Refused rather than redacted, because a field that is never collected cannot leak
through a redactor that missed it:

- `.env` files, and any configuration document
- credential store exports, secret plaintext, private keys
- the process environment
- the command line
- the user name, the home directory, or any absolute path under it
- the hostname
- market data, ledgers, model artefacts, databases
- raw memory dumps, heap dumps, or Python object representations
- `.git`, `.venv`, caches, or any part of the repository source tree

`PlatformSummary` reads `platform.release()` rather than `platform.uname()`
precisely because the wider call carries the node name. A filesystem is identified
by its bare drive designator and never by the directory beneath it, which names a
user profile and therefore names somebody.

---

## Redaction, and the limit of it

Log excerpts are NDJSON, so each line is parsed, passed through
`globin.domain.observability.redact` — Phase 023's redactor and no other — and
re-rendered. Building a second redactor here would mean two lists of sensitive
field names, and two lists drift: the one that is not the one somebody edits
becomes the one that leaks.

**A line that cannot be parsed is dropped, not passed through.** This is the single
place in the bundle that prefers losing a diagnostic to risking a credential: an
unparseable line cannot be redacted by field name, so including it would mean
shipping bytes nothing had inspected.

**Redaction matches field names, and that limit is stated rather than implied.** A
credential inside a free-text message, or inside an exception string a dependency
produced, survives — exactly as
[`RUNTIME_DIAGNOSTICS.md`](RUNTIME_DIAGNOSTICS.md) already says of the live log.
`faults.txt` is native traceback text and is included with paths sanitised, not
with its contents parsed.

---

## Limits

Every bound is a typed setting in the `diagnostics` section of
[`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md).

| Setting | Default | Bounds |
|---|---|---|
| `bundle_total_input_bytes` | 64 MiB | How much may be read from disk in total |
| `bundle_archive_bytes` | 32 MiB | How large the finished archive may be |
| `bundle_member_bytes` | 8 MiB | One member, before truncation |
| `bundle_log_bytes` | 16 MiB | Log text across every log member |
| `bundle_member_count` | 64 | How many members |

**The budget is spent in a deliberate order.** The snapshot and the state documents
come first because they are small and always useful; logs come last because they
are the only thing that can be large. A collector reading logs first could spend
the whole budget on them and exclude the snapshot, producing a bundle that says a
great deal about what happened and nothing about the machine it happened on.

A truncated member carries a notice **in its content** as well as a flag in the
manifest, because the person reading the file inside the archive is not
necessarily the person who read the manifest, and a log that simply stops looks
like a process that simply stopped.

The archive size is checked after the archive exists rather than by adding up the
inputs. Compression means the sum of the inputs is not the size of the output, and
a limit on the finished file is what an operator actually cares about — it is the
thing they have to send.

---

## Determinism, claimed narrowly

Two runs **at different times** produce different archives, because a log grows and
a measurement moves. Promising otherwise would be a guarantee nobody could keep,
and this document does not make it.

What is guaranteed for the same logical inputs, and verified by test:

- the member list and its lexicographic order
- the member names
- the canonical JSON bytes of the snapshot and the manifest
- ZIP metadata: every member is stamped `1980-01-01T00:00:00`, the earliest date
  the format can represent, with fixed external attributes
- one compression method and one level, both named rather than left to the
  interpreter's default

Real modification times are discarded deliberately: they are the largest source of
nondeterminism in an archive, they vary with when a file happened to be touched
rather than with its content, and on this host they would additionally record when
an operator was at their machine.

---

## The manifest, and why it cannot describe itself

Every member carries a logical path, an artefact kind, a byte size, a SHA-256
digest of exactly the stored bytes, a redaction flag, a truncation flag and a
source label. Excluded candidates carry a reason code and **no path** — the whole
point of excluding something is that it could not be shown to be safe, and naming
it would publish the one string the exclusion was protecting.

The manifest describes every member **except itself**. A manifest carrying its own
digest would describe a file that changes the moment the description is written,
which has no fixed point. It is therefore built over the collected members and the
report, written last, and the validator is told its name so it can check the
archive holds exactly the described set plus that one file.

---

## Validation happens before publication, and reopens the file

A manifest generated from the same in-memory objects that produced the archive
establishes only that the code agrees with itself. The validator reopens the
finished file through `zipfile`, recomputes every digest from the stored bytes, and
compares the member set **in both directions** — a manifest missing a member that
is present is as wrong as one naming a member that is not, and the first is the
shape a leak has.

Six questions: is the archive readable, is any member corrupt, does it hold its own
manifest, does the described set match, does every digest recompute, and is the
size within its limit.

**Publication is atomic.** The archive is built under a `.partial` name in the
destination's own directory — beside it, because `os.replace` is only atomic within
one filesystem — validated, hashed, and only then moved. An incomplete or refused
bundle never appears under the name an operator would look for, and the partial
file is removed on every failure path.

---

## Where it lands

`%LOCALAPPDATA%\GLOBIN\cache\support\globin-support.zip`.

`cache` rather than `state`, and no sixth
[`RUNTIME_FILESYSTEM.md`](RUNTIME_FILESYSTEM.md) area is added. A bundle is a
bounded, reproducible artefact an operator may delete without breaking anything,
whereas `state` holds the small documents a run publishes atomically about itself.

---

## Path safety

Every member name is refused unless it is a normalised, relative, POSIX-style path.
Six refusals, each with a real failure behind it:

| Refused | Because |
|---|---|
| Empty, or over 120 characters | Neither extracts reliably |
| A backslash | The ZIP format specifies forward slashes; a backslash is a literal character in a member name |
| Absolute, by leading slash or drive letter | An extractor honouring it writes outside the chosen directory |
| A `..` segment | The same traversal by a different spelling, and the one that survives naive normalisation |
| A reserved device stem (`con`, `nul`, `lpt1`…) | Cannot be created on Windows at all, and `con.txt` is reserved as surely as `con` |
| A control character, or a trailing dot or space | Windows silently strips the last two, so the manifest name and the on-disk name would differ — and the manifest is what the digests are checked against |

Two members differing only in case are refused as well. Windows compares filenames
case-insensitively, so an archive containing both `logs/Globin.log` and
`logs/globin.log` extracts to one file on the machine most likely to be reading it,
and the manifest would then describe a member that is not there.

---

## Verifying a bundle you received

```bash
python -c "import zipfile,json,hashlib; z=zipfile.ZipFile('globin-support.zip'); m=json.loads(z.read('manifest.json')); print(all('sha256:'+hashlib.sha256(z.read(e['member'])).hexdigest()==e['digest'] for e in m['entries']))"
```
