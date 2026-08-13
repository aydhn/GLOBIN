"""Concrete implementations of ports. The only layer that touches the world.

**May import:** :mod:`globin.domain`, :mod:`globin.ports`,
:mod:`globin.application`, the shared policy modules, and I/O-capable modules.

**May not import:** :mod:`globin.runtime`. An adapter is constructed by the
composition root; it does not construct itself, and it must not reach back into
the wiring that chose it.

Everything GLOBIN will eventually have to distrust lives here: exchange
clients, storage, the filesystem, the clock, notifications. Confining it to one
layer is what makes the rest of the codebase testable without a network.

Sub-packages appear when a phase puts real content in them —
``docs/engineering/REPOSITORY_LAYOUT.md`` prohibits scaffolding directories in
advance, so there is no empty ``exchange/`` or ``persistence/`` waiting here.

This package deliberately re-exports nothing.
"""
