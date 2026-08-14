"""Contract tests: project rules, asserted executably rather than written down.

These assert what the repository *promises* rather than what any single function
computes — identity and policy constants, packaging metadata, documentation
structure, file placement, and the machine-readable configuration that the
quality gates read.

They are the reason a policy erodes visibly instead of quietly. GLOBIN develops
on ``master`` with no reviewer (ADR-0005), so a rule nothing fails on is a rule
that will eventually stop being true.
"""
