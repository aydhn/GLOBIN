"""Property level: invariants asserted over generated input rather than examples.

A test here states something that must hold for *every* input in a described
space, and Hypothesis searches that space for a counter-example. The point is
not extra coverage. It is that an example-based test only ever asserts what its
author already thought of, and the inputs that break a function are usually the
ones nobody pictured — an empty sequence, a boundary, a value that is
technically in range and nonsensical.

A property test earns its place when a real invariant exists: an idempotent
normalisation, a round trip, a total function over a bounded domain, an ordering
that must not depend on input order. Where there is no such invariant, an
example-based test at the level that owns the behaviour is clearer, and writing
a property test anyway produces a slow test that asserts very little.

Everything here is pure and offline, like every other level. Reproducing a
failure is covered in ``docs/TESTING_STRATEGY.md``.
"""
