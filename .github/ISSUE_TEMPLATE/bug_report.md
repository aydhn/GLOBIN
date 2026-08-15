---
name: Bug report
about: Report incorrect behaviour in GLOBIN
---

<!--
STOP IF THIS IS A SECURITY ISSUE. Do not describe a vulnerability, an exploit or
a credential here. This issue is public the moment it is opened, and a public
repository is indexed, cloned and forked continuously — nothing published here
can be withdrawn by deleting it. Report it privately instead:

  https://github.com/aydhn/GLOBIN/security/advisories/new

`SECURITY.md` says what counts as a vulnerability, what to include, and what
happens next.

Redact every credential, API key, token, account identifier and balance before
pasting logs. Anything pasted here is permanent.

GLOBIN does not trade and has no exchange connection at its current phase — see
`README.md`. A report about trading behaviour is most likely a report about
documentation describing a phase that is not implemented.
-->

## Expected behaviour

What should have happened, and what makes you expect that — a document, a test,
or a stated contract:

## Actual behaviour

What happened instead:

## Reproduction

Exact steps, starting from a clean working tree:

1.
2.
3.

Command that demonstrates it:

```
```

## Environment

- Python version (`python --version`):
- Operating system:
- Commit (`git rev-parse --short HEAD`):
- Working tree clean (`git status --porcelain` empty)? yes / no

## Log or error excerpt

Smallest excerpt that shows the failure. **Secrets redacted.**

```
```

## Scope

- Phase or module affected:
- Related document or ADR, if any:

## Regression

- [ ] This previously worked
- [ ] This never worked
- [ ] Unknown

If it previously worked, the last commit known good:

## Verification already attempted

- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`
- [ ] `python -m pytest -q`
- [ ] Neither

What the gate reported:
