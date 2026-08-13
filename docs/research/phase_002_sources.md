# Phase 002 — Research Source Ledger

Every external claim made by Phase 2 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 2 is a governance phase, so this ledger is deliberately short. It records
only facts about tooling and platform conventions that Phase 2 actually relies
on. Padding a ledger to reach a count would make it decorative rather than
auditable — see [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Where a fact could not be verified from a primary source in this phase, the
  entry says so explicitly and names the phase that must verify it.
- All accesses were performed on the date recorded in each entry.

---

## GitHub repository conventions

### S-01 — GitHub Docs: creating a pull request template

- **Canonical location:** https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/creating-a-pull-request-template-for-your-repository
- **Accessed:** 2026-08-14
- **Authority:** Primary — the platform vendor documenting its own behaviour.
- **Supports:** A single pull request template is recognised at the repository
  root as `pull_request_template.md`, in `docs/`, or in `.github/`. Multiple
  templates live in a `PULL_REQUEST_TEMPLATE/` directory and are selected with a
  `template` query parameter.
- **Implication for GLOBIN:** `.github/pull_request_template.md` is a documented
  path, so Phase 2 uses it rather than guessing. GLOBIN has one change process
  and therefore one template; the multi-template directory form is not used.

### S-02 — GitHub Docs: configuring issue templates for your repository

- **Canonical location:** https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository
- **Accessed:** 2026-08-14
- **Authority:** Primary — the platform vendor documenting its own behaviour.
- **Supports:** Issue templates live in `.github/ISSUE_TEMPLATE`. Both Markdown
  templates with YAML frontmatter and YAML issue forms are supported. An
  optional `config.yml` in the same directory controls `blank_issues_enabled`
  and `contact_links`, and takes effect once merged into the default branch.
- **Implication for GLOBIN:** `.github/ISSUE_TEMPLATE/` is the correct location.
  Phase 2 adds no `config.yml`: disabling blank issues is a repository policy
  decision the owner has not made, and inventing it here would exceed the phase.

### S-03 — GitHub Docs: issue template frontmatter keys

- **Canonical location:** https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms
- **Accessed:** 2026-08-14
- **Authority:** Primary — the platform vendor documenting its own behaviour.
- **Supports:** Markdown issue templates accept the frontmatter keys `name`,
  `about`, `title`, `labels` and `assignees`, and reside in the same
  `.github/ISSUE_TEMPLATE` folder as YAML issue forms.
- **Implication for GLOBIN:** Phase 2 uses only `name` and `about`. `labels` and
  `assignees` would reference repository configuration that does not exist, and
  `title` would presume a naming convention no phase has established.

---

## Python tooling

### S-04 — Python Packaging User Guide: writing `pyproject.toml`

- **Canonical location:** https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- **Accessed:** 2026-08-14
- **Authority:** Primary — PyPA, the body that publishes the packaging
  specifications.
- **Supports:** `[build-system]` declares the build backend and its build-time
  requirements; `[project]` is the standardised metadata table; `[tool]` holds
  tool-specific subtables whose contents each tool defines. Fields listed in
  `dynamic` are computed by the build backend rather than stated statically.
- **Implication for GLOBIN:** The existing `pyproject.toml` already matches this
  separation — hatchling under `[build-system]`, metadata with
  `dynamic = ["version"]` under `[project]`, and pytest, ruff, mypy and coverage
  configuration under `[tool]`. Phase 2 confirms the layout and changes nothing,
  which is why it remains the single machine-readable configuration source.

### S-05 — pytest: good integration practices

- **Canonical location:** https://docs.pytest.org/en/stable/explanation/goodpractices.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** pytest recommends the `src` layout, and recommends the
  `importlib` import mode for new projects because it does not modify
  `sys.path`. Under the default `prepend` mode, test module names must be unique
  across the project.
- **Implication for GLOBIN:** The `src` layout recommendation is already
  satisfied. The `importlib` recommendation is **not** adopted in Phase 2, and
  the reason is verified rather than assumed: running
  `python -m pytest --import-mode=importlib` on this repository at the above
  access date fails collection with
  `ModuleNotFoundError: No module named 'conftest'`, because
  `tests/test_roadmap_contract.py` imports the shared `RoadmapRow` type with
  `from conftest import RoadmapRow`. Migrating the import mode therefore
  requires redesigning how shared test types are published. That is test
  architecture work and belongs to **Phase 004**, which owns fixture and test
  structure conventions. Recorded here so the decision is deliberate and the
  later phase inherits the evidence rather than rediscovering it.

---

## Version control hygiene

### S-06 — Git documentation: `gitattributes`

- **Canonical location:** https://git-scm.com/docs/gitattributes
- **Accessed:** 2026-08-14
- **Authority:** Primary — the Git project documenting its own behaviour.
- **Supports:** The `text` attribute controls end-of-line conversion. `text=auto`
  makes Git detect whether a file is text and normalise it to LF in the index.
  The `eol` attribute selects the working-tree ending and only applies when
  `text` is set. An explicit `text` attribute takes precedence over the
  `core.autocrlf` configuration variable, which is consulted only when `text` is
  unspecified. `binary` is a macro attribute equivalent to `-diff -merge -text`.
- **Implication for GLOBIN:** The `.gitattributes` written in Phase 1 is correct
  as it stands: `* text=auto eol=lf` normalises the repository to LF regardless
  of the machine's `core.autocrlf=true`, per-type `eol=crlf` rules keep Windows
  scripts usable, and `binary` on data and model extensions prevents damaging
  normalisation. Phase 2 changes nothing, which also avoids the mass
  renormalisation diff that editing these rules would produce.
