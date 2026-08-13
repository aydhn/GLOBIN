"""Abstract contracts for everything outside the application.

**May import:** :mod:`globin.domain` and the shared policy modules.

**May not import:** :mod:`globin.adapters`, :mod:`globin.runtime`, or any
I/O-capable standard library module.

A port describes *what* the core needs, in the core's own vocabulary, without
saying who provides it. That is what makes a fake possible: a test supplies an
object satisfying the port and never touches a network, a clock or a
credential — ``ENGINEERING_CONTRACT.md`` invariant 11.

Ports are declared with :class:`typing.Protocol`, so an implementation is
compatible by shape rather than by inheritance. An adapter therefore never has
to import the port it satisfies, which keeps the dependency pointing inward
even in the file that implements it.

This package deliberately re-exports nothing.
"""
