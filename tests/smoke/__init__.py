"""Smoke tests: the smallest set of checks that would catch a broken tree.

Import the package, confirm its public surface is coherent, confirm the
composition root can be reached. Nothing here is thorough; that is the point.

The value is latency. ``python -m tools.quality fast`` runs this level first so
that an obviously broken change fails in under a second rather than after the
full suite, and so pre-commit can afford to run it on every commit.
"""
