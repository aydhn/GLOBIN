# Phase 003 — Research Source Ledger

Every external claim made by Phase 3 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 3 is an architecture phase, so the sources divide into three groups: the
notation used to describe the system, the practice governing decision records,
and the standard library facilities the enforcement is built from. No Binance
source appears, because Phase 3 implements no exchange behaviour.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Where a fact could not be verified from a primary source in this phase, the
  entry says so explicitly and names the phase that must verify it.
- All accesses were performed on the date recorded in each entry.

---

## Architecture notation

### S-01 — C4 model: the four levels of abstraction

- **Canonical location:** https://c4model.com/
- **Accessed:** 2026-08-14
- **Authority:** Primary — the model's own site, published by its author.
- **Supports:** C4 describes software using four hierarchical levels of
  abstraction: software system, container, component, and code. The diagrams are
  a hierarchy, each zooming one level further into the level above.
- **Implication for GLOBIN:** Phase 3 documents the top two levels only, in
  [`../architecture/SYSTEM_CONTEXT.md`](../architecture/SYSTEM_CONTEXT.md) and
  [`../architecture/CONTAINER.md`](../architecture/CONTAINER.md). The component
  level is deliberately not drawn: GLOBIN's components are its five layers, and
  a diagram of them would restate
  [`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml)
  in a form no test can check. The code level is the source itself.

### S-02 — C4 model: what a container is

- **Canonical location:** https://c4model.com/abstractions/container
- **Accessed:** 2026-08-14
- **Authority:** Primary — the model's own site.
- **Supports:** A container is an application or a data store — something that
  must be running, or must exist, for the system to work. It is a runtime
  boundary around executing code or stored data. The page states plainly that
  this is not a Docker container, and notes that the popularity of
  containerisation has made the term confusing. Its examples include server-side
  and desktop applications, console and batch applications, database schemas,
  blob stores, file systems and shell scripts.
- **Implication for GLOBIN:** the container view names one container today — the
  single Python process — plus the repository working tree, which qualifies
  because the architecture review genuinely reads a file from it. Storage
  engines, model registries and the Telegram interface are listed separately as
  planned, with their owning phases, so a reader cannot mistake a plan for a
  capability.

### S-03 — C4 model: the system context diagram

- **Canonical location:** https://c4model.com/diagrams/system-context
- **Accessed:** 2026-08-14
- **Authority:** Primary — the model's own site.
- **Supports:** The scope of a system context diagram is a single software
  system. Its primary element is that system; its supporting elements are the
  people who use it and the external systems it interacts with, which typically
  fall outside the team's ownership. The intended audience is everybody,
  technical and non-technical, inside and outside the team. Detail is explicitly
  not the point at this level. The page also shows a diagram key, and recommends
  the diagram for all teams.
- **Implication for GLOBIN:** the system context view draws one GLOBIN box, the
  operator, and the external systems — Binance Global, its non-production
  environments, Telegram, the Windows host, local storage and the time sources.
  Binance is drawn outside the boundary rather than as an internal module, which
  is the distinction that makes the adapter layer necessary. Each diagram is
  followed by prose, so the diagram is never the only carrier of a required fact.

---

## Architecture decision records

### S-04 — Microsoft Azure Well-Architected Framework: maintaining an ADR

- **Canonical location:** https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record
- **Accessed:** 2026-08-14
- **Authority:** Primary — Microsoft documenting its own prescriptive guidance.
- **Supports:** An ADR should cover only choices that affect the system's
  structure or key quality attributes, or that are difficult to reverse. The
  record set is an append-only log: accepted records are not edited, and a
  changed decision becomes a new record that supersedes the original, with the
  two linked, so the history of the thinking survives. A record should carry a
  problem statement with context, the options considered, the decision outcome
  including its trade-offs, and a status such as Proposed, Accepted or
  Superseded. The guidance also warns against hiding consequences, against
  omitting rationale, and against letting a record become a design guide.
- **Implication for GLOBIN:** the repository's existing rules already matched
  most of this. Phase 3 adds the parts that were missing: explicit `Supersedes`
  and `Superseded By` fields so the link between records is machine-checkable,
  and a `Risks and Trade-offs` section distinct from `Consequences`. The
  warning against hiding consequences is why
  [`../adr/TEMPLATE.md`](../adr/TEMPLATE.md) asks what becomes harder, not only
  what improves.

### S-05 — AWS Prescriptive Guidance: the architectural decision record process

- **Canonical location:** https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/adr-process.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — AWS documenting its own prescriptive guidance.
- **Supports:** ADRs have states and follow a lifecycle. A record starts as
  Proposed. Review ends in one of three outcomes: it stays Proposed pending
  rework, it becomes Rejected — with the reason recorded, specifically to
  prevent the same debate recurring — or it becomes Accepted. Records are
  treated as immutable once accepted **or rejected**; changing a decision
  requires a new record, after which the old one moves to Superseded.
  Architecturally significant decisions include structure, non-functional
  requirements, dependencies, interfaces, and construction techniques such as
  libraries, frameworks and tools. The guide also expects ADRs to be referenced
  during code and architecture review.
- **Implication for GLOBIN:** `Rejected` was missing from the repository's status
  vocabulary and is added, along with the rule that a rejected record is
  immutable too. The categories of significance justify each of Phase 3's own
  records: ADR-0013 is structure, ADR-0014 is dependencies and interfaces, and
  ADR-0015 is construction technique. The expectation that ADRs are consulted
  during review is why
  [`../architecture/README.md`](../architecture/README.md) links to them from the
  document a contributor reads first.

---

## Python packaging and standard library

### S-06 — Python Packaging User Guide: `src` layout versus flat layout

- **Canonical location:** https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
- **Accessed:** 2026-08-14
- **Authority:** Primary — PyPA, the body publishing the packaging
  specifications.
- **Supports:** The decisive difference is import shadowing. Python places the
  current working directory early on the import path, so an import package
  sitting in the project root will be used in preference to the installed
  copy. The `src` layout removes that possibility by keeping importable code out
  of the root directory. It also means the project must be installed to be run,
  and it prevents an editable install from exposing files that were never meant
  to be importable.
- **Implication for GLOBIN:** the existing `src` layout is retained unchanged,
  and the five new layer packages are created **inside** `src/globin/` rather
  than beside it. The repository still runs its suite via `pythonpath = ["src"]`
  with no install step, so the shadowing hazard this source describes is avoided
  by layout rather than by installation. Verifying behaviour against a genuinely
  installed distribution remains unverified in this phase and belongs to
  Phases 017-032, which own environment and packaging work.

### S-07 — Python documentation: `typing.Protocol`

- **Canonical location:** https://docs.python.org/3/library/typing.html#typing.Protocol
- **Accessed:** 2026-08-14
- **Authority:** Primary — the Python project documenting its own library.
- **Supports:** `Protocol` implements structural subtyping, also called static
  duck typing, introduced by PEP 544. A class satisfies a protocol by having the
  required methods and attributes; it does not need to inherit from it. Runtime
  `isinstance` checks against a protocol require the `@runtime_checkable`
  decorator and inspect only the presence of attributes, ignoring signatures.
  Available since Python 3.8.
- **Implication for GLOBIN:** ports are declared as `Protocol` classes. Because
  an implementation need not inherit from the port, an adapter does not import
  the contract it satisfies, so the dependency still points inward in the file
  that implements it, and a test fake needs no base class.
  `@runtime_checkable` is deliberately **not** used: it would check only that
  attribute names exist, which is weaker than the static check `mypy --strict`
  already performs, and would invite the mistaken belief that the port is
  validated at runtime.

### S-08 — Python documentation: the `ast` module

- **Canonical location:** https://docs.python.org/3/library/ast.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the Python project documenting its own library.
- **Supports:** `ast.parse` produces an abstract syntax tree from source.
  `ast.walk` recursively yields every descendant node, including the starting
  node, in no specified order. An `Import` node carries `names`, a list of alias
  nodes. An `ImportFrom` node carries `module`, the name without leading dots;
  `names`, the imported aliases; and `level`, an integer where 0 means an
  absolute import and any higher value is the depth of a relative one.
- **Implication for GLOBIN:** the import graph is derived by parsing rather than
  by importing, because importing would execute the modules and the phase's own
  rule is that importing executes nothing. Walking the whole tree means an
  import nested inside a function, or inside an `if TYPE_CHECKING:` block, is
  counted like any other — both are genuine dependencies, and excluding either
  would leave a documented way to hide a violation. A non-zero `level` raises,
  since relative imports are banned repository-wide by lint configuration.

### S-09 — Python documentation: `tomllib`

- **Canonical location:** https://docs.python.org/3/library/tomllib.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the Python project documenting its own library.
- **Supports:** `tomllib` parses TOML 1.0.0 and has been in the standard library
  since Python 3.11. It does not support writing. `tomllib.load` takes a
  readable **binary** file object and returns a dictionary; `tomllib.loads`
  takes a string.
- **Implication for GLOBIN:** the machine-readable architecture contract is TOML,
  parsed with `tomllib`, so it costs no runtime dependency — which matters
  because the empty dependency list is an asserted invariant (ADR-0003) and the
  development extra is pinned by test to exactly four tools. The file is opened
  in binary mode, as the interface requires. That `tomllib` cannot write is not a
  constraint here: the contract is edited by hand, and a tool that rewrote it
  would defeat the point of the change being visible in a diff.

---

## Documentation tooling

### S-10 — GitHub Docs: creating diagrams in Markdown

- **Canonical location:** https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams
- **Accessed:** 2026-08-14
- **Authority:** Primary — the platform vendor documenting its own behaviour.
- **Supports:** GitHub renders Mermaid diagrams written inside a fenced code
  block tagged with the `mermaid` language identifier. Rendering works in issues,
  discussions, pull requests, wikis and Markdown files. The documented caveat is
  that a third-party Mermaid plugin may produce errors, and that the syntax
  supported depends on the Mermaid version GitHub currently ships.
- **Implication for GLOBIN:** architecture diagrams are Mermaid in fenced blocks
  rather than committed image files, so they are diffable, reviewable as text,
  and cannot drift from a binary nobody can edit. Because the supported Mermaid
  version is outside GLOBIN's control, only long-established diagram syntax is
  used, and every diagram is accompanied by prose stating the same facts — a
  diagram that fails to render must never take a required fact with it. The
  repository's existing checks cooperate with this: fenced blocks are stripped
  before documents are scanned for prose, so diagram source is not mistaken for
  a claim.
