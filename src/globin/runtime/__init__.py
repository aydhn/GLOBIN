"""The composition root: where objects are built and dependencies are wired.

**May import:** every other layer, plus the shared policy modules.

**May not be imported by** any of them. This is the one layer that is allowed
to know the whole picture, and it earns that by being the only place where a
concrete implementation is chosen. Everywhere else, an implementation arrives
as an argument.

Two rules make the arrangement worth having, and both are testable:

* **One place decides.** If a second module starts constructing adapters, the
  question "what is this program actually made of?" no longer has one answer.
* **Deciding happens when called, not when imported.** Building the object
  graph is work, and ``ENGINEERING_CONTRACT.md`` invariant 5 prohibits import
  from performing work. A module-level client, connection or file read would
  make ``import globin`` depend on the machine it runs on.

GLOBIN uses no dependency injection framework. Explicit construction in a
function is smaller, typed, and traceable in a stack trace; a container would
add a runtime dependency and hide the graph behind reflection.

This package deliberately re-exports nothing.
"""
