"""The GLOBIN test suite, organised as a package.

``tests`` is a real package rather than a loose directory so that test modules
are imported under stable, fully-qualified names (``tests.contract.test_...``)
and can import shared helpers from :mod:`tests.support` explicitly. Without it,
two modules of the same name in different taxonomy directories would collide,
and helper imports would depend on pytest's ``sys.path`` handling rather than on
anything written down.

Each subpackage is one level of the taxonomy defined in
``docs/TESTING_STRATEGY.md``. A test's directory determines its marker — the
mapping is applied automatically in ``conftest.py`` and asserted by
``tests/contract/test_quality_contract.py``, so the two cannot drift.
"""
