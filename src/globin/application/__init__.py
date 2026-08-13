"""Use cases that coordinate domain objects through ports.

**May import:** :mod:`globin.domain`, :mod:`globin.ports` and the shared policy
modules.

**May not import:** :mod:`globin.adapters`, :mod:`globin.runtime`, or any
I/O-capable standard library module.

An application service says what happens and in what order. It never says
*which* implementation does it: no HTTP client, no file path, no database
handle, no environment variable. Those arrive as constructor arguments typed as
ports, chosen by the composition root in :mod:`globin.runtime`.

The rule that keeps this honest is the one worth remembering: if a use case
cannot be exercised without a network, a real clock or live credentials, it is
built wrong.

This package deliberately re-exports nothing.
"""
