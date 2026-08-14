# Purpose

<!--
GLOBIN develops on `master` only (ADR-0005). This template is the repository's
change-description standard; its presence does not introduce a branching model.
Use it for any review or inspection of a change, whether or not a pull request
is opened.

Full criteria: `docs/engineering/DEFINITION_OF_DONE.md`.
-->

What this change delivers, in one or two sentences.

**Phase:** <NNN of 320>

## Scope

What is in scope:

What is deliberately **not** in scope, and which phase owns it:

## Behaviour change

- [ ] No behaviour change (documentation, tests or configuration only)
- [ ] Behaviour changed — described below

If behaviour changed, state what a caller would observe differently:

## Tests

Which tests cover this change, and what they would catch:

- [ ] Tests were written alongside the behaviour, not afterwards
- [ ] Tests assert invariants, not formatted output
- [ ] A bug fix includes a regression test that fails without the fix
- [ ] Nothing was skipped, weakened or deleted to make the suite pass

## Documentation

- [ ] Documentation matches the implementation
- [ ] Public interface changes are documented
- [ ] A decision with lasting consequence has an ADR (`docs/adr/TEMPLATE.md`)
- [ ] External behaviour relied upon is recorded in `docs/research/phase_NNN_sources.md`
- [ ] Nothing is described in the present tense that does not yet exist

## Risks

What could this break, and how would that show up:

Which parts are least certain:

## Dependencies

- [ ] No new runtime dependency
- [ ] A dependency was added, justified below against ADR-0003 (zero-budget),
      with `tests/contract/test_packaging_contract.py` updated accordingly

Justification:

## Backward compatibility

- [ ] No persisted format, public interface or configuration key changed
- [ ] Something changed — migration path described below

## Secrets and artefacts

- [ ] The full diff was read, not just the file list
- [ ] No credentials, API keys, tokens, private keys, `.env` files or personal
      data — including in test fixtures
- [ ] No generated output, caches, coverage data, models, logs or datasets
- [ ] Every changed file was changed intentionally

## Verification

Commands actually run, with their results. Do not tick a box for a command you
did not execute.

```
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

- [ ] `ruff check`
- [ ] `ruff format --check`
- [ ] `mypy`
- [ ] `pytest` with branch coverage, meeting the threshold
- [ ] `pre-commit run --all-files`
- [ ] `git diff --check` reports nothing

A new test is in the directory for its level, and a new check was added to
`tools/quality/commands.py` rather than to a caller:

- [ ] Not applicable, or done

Output or summary:

## Definition of Done

- [ ] Every applicable item in `docs/engineering/DEFINITION_OF_DONE.md` holds
- [ ] Anything left incomplete is stated explicitly, with the reason
