"""Integration tests: several GLOBIN components working together, still local.

The distinction from a unit test is that real collaborators are used instead of
substitutes — typically wired through the composition root, so the object graph
under test is the one the application actually builds.

The distinction from an external test is that no network is involved. Nothing
here reaches an exchange, and nothing here uses a credential. Tests that talk to
real Binance non-production endpoints arrive with the API layer in Phases
033-048, carry the ``external`` marker, and are skipped by default.
"""
