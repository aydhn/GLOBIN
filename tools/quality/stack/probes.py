"""Running the behaviour probes, and reading what is installed.

The measuring half of the gate. :mod:`tools.quality.stack.plan` decides what
counts as correct; this performs the operation and hands over what happened, so
neither half can quietly agree with the other.

**Every import of ``numpy`` and ``pandas`` is inside a function.** Importing
either at module scope would make every quality command that merely touches this
package pay for it, and would make ``python -m tools.quality stack --help`` depend
on the very libraries it exists to report on. It also keeps the failure honest: a
library that cannot be imported is a *finding*, and a module that cannot be
imported is a crash.

**Nothing here decides anything.** Each probe returns measurements, and the
matching expectation function in ``plan`` turns them into problems. A probe that
returned a boolean would have made the judgement already, and the judgement is the
half worth testing from literals.
"""

import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata, util
from typing import Final

from tools.quality.stack.plan import (
    SMA_PERIOD,
    SMA_SERIES_LENGTH,
    Library,
    binary64_problems,
    copy_on_write_problems,
    indicator_table_problems,
    missing_value_problems,
    nan_infinity_problems,
    native_library_problems,
    overflow_problems,
    round_trip_problems,
    timestamp_problems,
    warmup_problems,
)

WHEEL_METADATA: Final[str] = "WHEEL"
"""The file inside a ``.dist-info`` that records which wheel was unpacked."""

TAG_FIELD: Final[str] = "tag:"
"""The field in that file naming the PEP 425 tag, lower-cased for comparison."""

INT64_MAXIMUM: Final[int] = 2**63 - 1
"""The value the overflow probe adds one to."""

TALIB_DISTRIBUTION: Final[str] = "ta-lib"
"""The distribution name, which is not the module name. The module is ``talib``."""

EXTENSION_SUFFIXES: Final[tuple[str, ...]] = (".pyd", ".so")
"""What a compiled Python extension is called, on Windows and elsewhere."""

LIBRARY_SUFFIXES: Final[tuple[str, ...]] = (".dll", ".dylib")
"""What a shared library shipped beside one is called.

Reported rather than refused. On this host TA-Lib's C library is linked into the
extension and no companion library ships, but a wheel that shipped one would carry
the library just as well, and the probe is about whether the library is *there*.
"""

SAMPLE_INSTANT: Final[str] = "2026-08-16T12:34:56.789000Z"
"""The timestamp the round-trip probe uses.

A literal rather than a clock reading. A probe that read the wall clock would
still pass, but the manifest it contributed to would differ between two runs of
the same tree — which is the determinism every gate here is checked against.
"""


class ProbeError(Exception):
    """A probe was asked for that this module does not implement."""


@dataclass(frozen=True, slots=True)
class LibraryFacts:
    """What was observed about one installed library.

    Args:
        installed: The version the environment reports, or ``None`` when the
            distribution is not installed.
        wheel_tag: The PEP 425 tag its own ``.dist-info/WHEEL`` records, or
            ``None`` when there is no such record.
        module_location: Where importing it resolved to, or ``None`` when it could
            not be imported.
    """

    installed: str | None
    wheel_tag: str | None
    module_location: str | None


def measure(library: Library) -> LibraryFacts:
    """Read what is installed for one declared library.

    Args:
        library: The declared library.

    Returns:
        Its version, provenance and import location, each ``None`` when it could
        not be established.

    Nothing raises. A missing distribution and an unimportable module are both
    ordinary findings on a broken host, and turning either into an exception would
    replace a named check failure with a traceback.
    """
    try:
        distribution = metadata.distribution(library.name)
    except metadata.PackageNotFoundError:
        return LibraryFacts(installed=None, wheel_tag=None, module_location=_location(library))
    return LibraryFacts(
        installed=distribution.version,
        wheel_tag=wheel_tag_of(_wheel_metadata(distribution)),
        module_location=_location(library),
    )


def _wheel_metadata(distribution: metadata.Distribution) -> str | None:
    """The contents of a distribution's ``WHEEL`` file.

    Args:
        distribution: The installed distribution.

    Returns:
        The text, or ``None`` when there is none — which is the normal state of a
        distribution installed from a source tree rather than from a wheel.
    """
    try:
        return distribution.read_text(WHEEL_METADATA)
    except OSError:
        return None


def wheel_tag_of(text: str | None) -> str | None:
    """Read the PEP 425 tag out of a ``WHEEL`` file.

    Args:
        text: The file's contents, or ``None``.

    Returns:
        The first ``Tag:`` value, or ``None`` when there is none.

    Separated from the reading so that a malformed or absent record is reachable
    from a literal. Only the first tag is taken: a wheel may record several, and
    the first is the one the installer matched.
    """
    if text is None:
        return None
    for line in text.splitlines():
        if line.lower().startswith(TAG_FIELD):
            tag = line.split(":", 1)[1].strip()
            if tag:
                return tag
    return None


def _location(library: Library) -> str | None:
    """Where importing a module would resolve to, without importing it.

    Args:
        library: The declared library.

    Returns:
        The origin the import machinery reports, or ``None`` when the module
        cannot be found.

    :func:`importlib.util.find_spec` is used rather than an import because this
    answers "which one would be found", which is the question a shadowed library
    makes interesting, and because the probes below import it anyway a moment
    later — this must not be the thing that decides whether that works.
    """
    try:
        spec = util.find_spec(library.import_name)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    return spec.origin or ""


# ---------------------------------------------------------------------------
# The probes. Each measures, then delegates the judgement to `plan`.
# ---------------------------------------------------------------------------


def _numpy_float64_is_binary64() -> tuple[str, ...]:
    """Measure this build's ``float64`` against IEEE-754 binary64.

    Returns:
        What was wrong, empty when nothing was.
    """
    import numpy

    info = numpy.finfo(numpy.float64)
    return binary64_problems(
        mantissa_bits=int(info.nmant),
        epsilon=float(info.eps),
        bits=int(info.bits),
        item_bytes=numpy.dtype(numpy.float64).itemsize,
    )


def _numpy_nan_and_infinity_propagate() -> tuple[str, ...]:
    """Measure whether non-finite results propagate rather than being substituted.

    Returns:
        What was wrong, empty when nothing was.

    ``errstate`` suppresses the warnings the two divisions raise. They are
    expected here — the probe is about the *value* produced, and letting the
    warning through would make this the one probe whose output depends on the
    ambient warning filter.
    """
    import numpy

    with numpy.errstate(divide="ignore", invalid="ignore"):
        infinity = numpy.float64(1.0) / numpy.float64(0.0)
        indeterminate = numpy.float64(0.0) / numpy.float64(0.0)
    not_a_number = numpy.float64("nan")
    return nan_infinity_problems(
        infinity_is_infinite=bool(numpy.isinf(infinity)),
        zero_over_zero_is_nan=bool(numpy.isnan(indeterminate)),
        nan_differs_from_itself=bool(not_a_number != not_a_number),
    )


def _numpy_integer_overflow_wraps_observably() -> tuple[str, ...]:
    """Measure whether a signed 64-bit overflow wraps and says so.

    Returns:
        What was wrong, empty when nothing was.

    The warning is captured rather than suppressed, because whether one is emitted
    at all is half of what this probe establishes. ``simplefilter("always")``
    defeats the once-per-location deduplication that would otherwise make the
    result depend on whether anything earlier in the process had already
    overflowed.
    """
    import numpy

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        wrapped = numpy.int64(INT64_MAXIMUM) + numpy.int64(1)
    return overflow_problems(wrapped_to=int(wrapped), warned=bool(caught))


def _pandas_float64_round_trip_is_bit_exact() -> tuple[str, ...]:
    """Measure whether a float column survives a frame round trip unchanged.

    Returns:
        What was wrong, empty when nothing was.

    The sample deliberately includes ``-0.0`` and a subnormal-adjacent magnitude:
    a comparison by value would call ``-0.0`` equal to ``0.0``, so the bytes are
    compared instead.
    """
    import numpy
    import pandas

    values = numpy.array(
        [0.1, 1.0 / 3.0, 1e-308, 2.0**-52, -0.0, float("inf")], dtype=numpy.float64
    )
    column = pandas.DataFrame({"x": values})["x"]
    returned = column.to_numpy(dtype=numpy.float64)
    return round_trip_problems(
        bit_exact=returned.tobytes() == values.tobytes(), dtype=str(column.dtype)
    )


def _pandas_missing_value_survives_a_round_trip() -> tuple[str, ...]:
    """Measure whether a missing value stays missing.

    Returns:
        What was wrong, empty when nothing was.
    """
    import numpy
    import pandas

    values = numpy.array([1.0, numpy.nan, 3.0], dtype=numpy.float64)
    column = pandas.DataFrame({"x": values})["x"]
    returned = column.to_numpy(dtype=numpy.float64)
    positions = [index for index, missing in enumerate(numpy.isnan(returned)) if missing]
    return missing_value_problems(missing_positions=positions, dtype=str(column.dtype))


def _pandas_utc_timestamp_round_trip_preserves_the_instant() -> tuple[str, ...]:
    """Measure whether a UTC-aware timestamp survives a frame round trip.

    Returns:
        What was wrong, empty when nothing was.
    """
    import datetime

    import pandas

    original = pandas.Timestamp(SAMPLE_INSTANT)
    column = pandas.DataFrame({"t": [original]})["t"]
    returned = column.iloc[0]
    zone = getattr(column.dtype, "tz", None)
    return timestamp_problems(
        timezone_name="" if zone is None else str(zone),
        instant_preserved=bool(returned == original),
        is_utc=returned.tzinfo is not None
        and returned.tzinfo.utcoffset(None) == datetime.timedelta(0),
    )


def _pandas_copy_on_write_is_active() -> tuple[str, ...]:
    """Measure whether mutating a derived object leaves its parent alone.

    Returns:
        What was wrong, empty when nothing was.

    The behaviour is observed rather than ``mode.copy_on_write`` being read.
    pandas 3.0 deprecated that option — reading it emits a warning saying
    copy-on-write can no longer be disabled — and pandas 4.0 removes it, so a
    probe that read it would fail on an upgrade for a reason unrelated to whether
    GLOBIN's assumption still holds.
    """
    import pandas

    parent = pandas.DataFrame({"x": [1.0, 2.0, 3.0]})
    derived = parent["x"]
    derived.iloc[0] = 99.0
    return copy_on_write_problems(parent_unchanged=bool(parent["x"].iloc[0] == 1.0))


def _shipped_binaries(distribution: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Which compiled artefacts a distribution installed.

    Args:
        distribution: The distribution name to read.

    Returns:
        Extension modules, then shared libraries shipped beside them. Both empty
        when the distribution is not installed, which the probe's judgement turns
        into a finding rather than a crash.
    """
    try:
        files = metadata.distribution(distribution).files or []
    except metadata.PackageNotFoundError:
        return (), ()
    names = [str(item) for item in files]
    extensions = tuple(name for name in names if name.lower().endswith(EXTENSION_SUFFIXES))
    libraries = tuple(name for name in names if name.lower().endswith(LIBRARY_SUFFIXES))
    return extensions, libraries


def _talib_native_library_is_carried_by_the_wheel() -> tuple[str, ...]:
    """Ask the native TA-Lib library to name itself.

    Returns:
        What was wrong, empty when the wheel carried it.

    ``__ta_version__`` is answered by the C library rather than by the wrapper, so
    a reply proves it linked and initialised. It is ``bytes`` on this host, and the
    decode handles ``str`` too — the attribute is not documented in the project's
    README, so its type is a measurement rather than a contract.
    """
    import talib

    raw = getattr(talib, "__ta_version__", b"")
    reported = raw.decode("ascii", "replace") if isinstance(raw, bytes) else str(raw)
    extensions, libraries = _shipped_binaries(TALIB_DISTRIBUTION)
    return native_library_problems(
        reported_version=reported.strip(),
        extension_modules=extensions,
        external_libraries=libraries,
    )


def _talib_indicator_table_is_complete() -> tuple[str, ...]:
    """Count what the linked library actually offers.

    Returns:
        What was wrong, empty when the table is complete.
    """
    import talib

    # The wrapper is Cython and ships no `py.typed`, so both of these are untyped
    # calls in a typed context on any host that actually has it installed. The
    # values are converted to tuples of `str` here, at the boundary, and everything
    # downstream is checked strictly.
    return indicator_table_problems(
        functions=tuple(talib.get_functions()),  # type: ignore[no-untyped-call]
        groups=tuple(talib.get_function_groups()),  # type: ignore[no-untyped-call]
    )


def _talib_moving_average_warmup_is_the_documented_length() -> tuple[str, ...]:
    """Measure where a moving average starts emitting, and what it emits.

    Returns:
        What was wrong, empty when the seeding convention held.

    Consecutive integers are used because their mean is exact in binary64, so the
    value check is an equality rather than a tolerance — this probe is about a
    convention, and a tolerance would let a one-bar shift through.
    """
    import numpy
    import talib

    series = numpy.arange(1.0, float(SMA_SERIES_LENGTH) + 1.0)
    averaged = talib.SMA(series, timeperiod=SMA_PERIOD)
    finite = numpy.flatnonzero(~numpy.isnan(averaged))
    leading = int(finite[0]) if finite.size else int(averaged.size)
    return warmup_problems(leading_gaps=leading, final_value=float(averaged[-1]))


def registry() -> Mapping[str, Callable[[], tuple[str, ...]]]:
    """Every probe this module can run, by identifier.

    Returns:
        Identifier to the callable that runs it.

    A function rather than a constant, matching
    :func:`tools.quality.stack.plan.implemented_probes`, which a contract test
    compares this against — two registries that must stay equal are easier to keep
    honest when they look alike.
    """
    return {
        "numpy.float64_is_binary64": _numpy_float64_is_binary64,
        "numpy.nan_and_infinity_propagate": _numpy_nan_and_infinity_propagate,
        "numpy.integer_overflow_wraps_observably": _numpy_integer_overflow_wraps_observably,
        "pandas.float64_round_trip_is_bit_exact": _pandas_float64_round_trip_is_bit_exact,
        "pandas.missing_value_survives_a_round_trip": _pandas_missing_value_survives_a_round_trip,
        "pandas.utc_timestamp_round_trip_preserves_the_instant": (
            _pandas_utc_timestamp_round_trip_preserves_the_instant
        ),
        "pandas.copy_on_write_is_active": _pandas_copy_on_write_is_active,
        "talib.native_library_is_carried_by_the_wheel": (
            _talib_native_library_is_carried_by_the_wheel
        ),
        "talib.indicator_table_is_complete": _talib_indicator_table_is_complete,
        "talib.moving_average_warmup_is_the_documented_length": (
            _talib_moving_average_warmup_is_the_documented_length
        ),
    }


def run(identifier: str) -> tuple[str, ...]:
    """Run one probe.

    Args:
        identifier: Which probe to run.

    Returns:
        What it found wrong, empty when nothing was.

    Raises:
        ProbeError: If no probe has that identifier, or the library it needs
            could not be imported. Both are the gate's problem to report rather
            than this module's to swallow.
    """
    probe = registry().get(identifier)
    if probe is None:
        msg = f"no probe is implemented for {identifier!r}"
        raise ProbeError(msg)
    try:
        return probe()
    except ImportError as fault:
        msg = f"{identifier} could not run: {fault}"
        raise ProbeError(msg) from fault
