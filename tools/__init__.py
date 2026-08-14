"""Development tooling that is not part of the GLOBIN application.

Nothing here is imported by ``src/globin``, ships in a distribution, or runs at
runtime. This is the tree for things that act *on* the repository rather than
things the repository *is* — see ``docs/engineering/REPOSITORY_LAYOUT.md`` for
why that is a separate place from both ``src/globin/`` and ``scripts/``.

It is a package rather than a directory of loose scripts so that its contents
are importable, typed and testable. ``tools/quality`` is exercised by
``tests/unit/test_quality_runner.py``; a shell script could not be.
"""
