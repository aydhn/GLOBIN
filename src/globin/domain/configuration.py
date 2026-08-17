"""The typed configuration model, its defaults, and how layers override.

GLOBIN's configuration is a frozen dataclass, not a document. Everything an
operator may vary is a typed field with a declared default, and the only way to
obtain one of these objects is to hand :func:`as_config` a resolved set of
settings. A configuration that reaches the rest of the system has therefore
already been validated, and there is no partially-configured state for a caller
to observe.

**There is no schema library.** ADR-0003 makes the empty runtime dependency list
an invariant, so pydantic and its relatives were never available — but the
dataclasses are not a consolation prize. A declarative field table would have to
be restated by a dataclass anyway to be typed at all, which is two definitions
and a tripwire test to keep them equal. Here the dataclass *is* the schema:
:func:`section_keys` and :func:`section_defaults` derive the key registry and the
defaults from it, so a new setting is one line and cannot be half-added.

**Validation lives here, not in the adapter.** Reading ``"WARNING"`` as
:attr:`~globin.domain.observability.Severity.WARNING` is a domain rule. Putting
it in the TOML adapter would mean Phase 027's environment-variable source writes
a second copy, and two copies of a validation rule drift. The adapter's whole job
is to parse and flatten; the schema never leaves the core.

**Layers replace values; they never remove them.** A :class:`ConfigLayer` is a
flat mapping of dotted keys, and :func:`resolve` folds an ordered sequence of
them so that the last layer *mentioning* a key wins. Silence is not a value:
there is no unset sentinel, so no layer can delete a setting an earlier one
established. Flat keys are what make that simple — a nested deep-merge would have
to answer whether a table replaces or merges its counterpart, and every answer to
that question surprises somebody.

**Refusal happens once, at binding.** :func:`resolve` is total and never raises;
every rejection is in :func:`as_config`, where the schema and the *origin* of
each value are both in hand, so the message can say which document is wrong
rather than merely that something is.

What this module deliberately does not decide: where configuration files live
and what profiles exist (Phase 026), which sources are consulted and in what
order (Phase 027), how secrets are stored (Phase 028, against the rules in
``docs/security/SECURITY_BASELINE.md``), and what an environment is (Phase 035).
It knows nothing about files, environment variables, or the machine it runs on —
and the baseline is explicit that a secret never arrives through configuration
at all, which is why this module needs no notion of one.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields
from typing import Any, Final

from globin.domain.diagnostics import (
    MAXIMUM_BACKUP_COUNT,
    MAXIMUM_ROTATION_BYTES,
    MINIMUM_ROTATION_BYTES,
    RotationPolicy,
)
from globin.domain.health import (
    MAXIMUM_BUDGET_MILLIS,
    MAXIMUM_FRAME_DEPTH,
    MAXIMUM_THRESHOLD_BYTES,
    MAXIMUM_TOP_SITES,
    MINIMUM_BUDGET_MILLIS,
    MINIMUM_FRAME_DEPTH,
    MINIMUM_THRESHOLD_BYTES,
    HealthThresholds,
)
from globin.domain.observability import Severity, redact
from globin.domain.support import (
    MAXIMUM_ARCHIVE_BYTES,
    MAXIMUM_MEMBER_COUNT,
    MINIMUM_ARCHIVE_BYTES,
    BundleLimits,
)
from globin.domain.watchdog import (
    DEFAULT_ESCALATE_MILLIS as DEFAULT_WATCHDOG_ESCALATE_MILLIS,
)
from globin.domain.watchdog import (
    DEFAULT_GRACE_MILLIS as DEFAULT_WATCHDOG_GRACE_MILLIS,
)
from globin.domain.watchdog import (
    DEFAULT_INTERVAL_MILLIS as DEFAULT_WATCHDOG_INTERVAL_MILLIS,
)
from globin.domain.watchdog import (
    DEFAULT_STALL_MILLIS as DEFAULT_WATCHDOG_STALL_MILLIS,
)
from globin.domain.watchdog import (
    MAXIMUM_ESCALATE_MILLIS,
    MAXIMUM_GRACE_MILLIS,
    MAXIMUM_INTERVAL_MILLIS,
    MAXIMUM_STALL_MILLIS,
    MINIMUM_ESCALATE_MILLIS,
    MINIMUM_GRACE_MILLIS,
    MINIMUM_INTERVAL_MILLIS,
    MINIMUM_STALL_MILLIS,
    WatchdogPolicy,
)
from globin.errors import ConfigurationError, InternalError, ValidationError

KEY_SEPARATOR: Final[str] = "."
"""What separates a section from a setting name in a resolved key."""

LOGGING_SECTION: Final[str] = "logging"
"""The section name logging settings are filed under."""

DIAGNOSTICS_SECTION: Final[str] = "diagnostics"
"""The section name health and support-bundle settings are filed under.

A second section, added in Phase 024. ``known_keys`` had until now been able to
return one section's keys directly; it now unions two, which is the change a reader
comparing this module against ``CONFIGURATION_POLICY.md`` should expect to find.
"""

WATCHDOG_SECTION: Final[str] = "watchdog"

TELEMETRY_SECTION: Final[str] = "telemetry"
"""The fourth section, added in Phase 026.

What GLOBIN measures about itself, and whether any of it leaves the machine.
The default answers are "measure" and "no"."""
"""The section name liveness settings are filed under.

A third section, added in Phase 025, and the smallest of the three on purpose.
Only the four durations and the two switches are here; the bounds on how much
evidence a stall may gather are ``Final`` constants in
``globin.domain.watchdog``, because no operator has a basis for preferring
twenty-four frames to thirty-two and ``CONFIGURATION_POLICY.md`` warns that this is
exactly where such fields accumulate.
"""

DEFAULTS_ORIGIN: Final[str] = "defaults"
"""The origin recorded for values that came from the model's own declarations.

Named rather than left blank so that an error message about a defaulted value
reads the same way as one about a value from a file.
"""

MIN_SEVERITY: Final[str] = f"{LOGGING_SECTION}{KEY_SEPARATOR}min_severity"
"""The lowest severity a sink will write.

Spelled out here as well as being derivable from :class:`LoggingConfig` because
:func:`as_config` needs a name to bind. The two are compared by
``tests/contract/test_configuration_contract.py``, which is what makes this a
tripwire rather than a copy — see ``docs/engineering/SOURCE_OF_TRUTH.md``.
"""

ROTATION_MAX_BYTES: Final[str] = f"{LOGGING_SECTION}{KEY_SEPARATOR}rotation_max_bytes"
"""The size at which the log file is rotated."""

ROTATION_BACKUP_COUNT: Final[str] = f"{LOGGING_SECTION}{KEY_SEPARATOR}rotation_backup_count"
"""How many rotated log files are kept beside the live one."""

DEFAULT_ROTATION_MAX_BYTES: Final[int] = 1_048_576
"""One mebibyte per file.

Small on purpose. ``RUNTIME_FILESYSTEM.md`` says the runtime tree holds nothing
large, and with the default backup count this bounds the whole logs area at eight
mebibytes — a number an operator can lose without noticing and a reviewer can
check without multiplying.
"""

DEFAULT_ROTATION_BACKUP_COUNT: Final[int] = 7
"""How many rotated files are kept by default.

Seven, so that the live file plus its backups span roughly a working week of
ordinary operation rather than a fixed number of hours. Nothing depends on that
being exact; it is a default chosen to be useful, not a guarantee about time.
"""


MINIMUM_FREE_BYTES: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}minimum_free_bytes"
"""Free space on a runtime filesystem below which the disk check fails."""

DISK_WARNING_BYTES: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}disk_warning_bytes"
"""Free space below which the disk check warns."""

MINIMUM_AVAILABLE_MEMORY_BYTES: Final[str] = (
    f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}minimum_available_memory_bytes"
)
"""Available host memory below which the memory check fails."""

PROCESS_RSS_WARNING_BYTES: Final[str] = (
    f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}process_rss_warning_bytes"
)
"""This process's resident set above which the process-memory check warns."""

BUDGET_MILLIS: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}budget_millis"
"""How long a whole health snapshot may take."""

BUNDLE_TOTAL_INPUT_BYTES: Final[str] = (
    f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}bundle_total_input_bytes"
)
"""How much may be read from disk into one support bundle."""

BUNDLE_ARCHIVE_BYTES: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}bundle_archive_bytes"
"""How large a finished support bundle may be."""

BUNDLE_MEMBER_BYTES: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}bundle_member_bytes"
"""How large one bundle member may be before it is truncated."""

BUNDLE_LOG_BYTES: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}bundle_log_bytes"
"""How much log text a bundle may include in total."""

BUNDLE_MEMBER_COUNT: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}bundle_member_count"
"""How many members a bundle may hold."""

TRACEMALLOC_ENABLED: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}tracemalloc_enabled"
"""Whether the interpreter's allocator tracer runs."""

TRACEMALLOC_FRAME_DEPTH: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}tracemalloc_frame_depth"
"""How many frames each traced allocation retains."""

TRACEMALLOC_TOP: Final[str] = f"{DIAGNOSTICS_SECTION}{KEY_SEPARATOR}tracemalloc_top"

WATCHDOG_ENABLED: Final[str] = f"{WATCHDOG_SECTION}{KEY_SEPARATOR}enabled"

WATCHDOG_INTERVAL_MILLIS: Final[str] = f"{WATCHDOG_SECTION}{KEY_SEPARATOR}interval_millis"

WATCHDOG_GRACE_MILLIS: Final[str] = f"{WATCHDOG_SECTION}{KEY_SEPARATOR}grace_millis"

WATCHDOG_STALL_MILLIS: Final[str] = f"{WATCHDOG_SECTION}{KEY_SEPARATOR}stall_millis"

WATCHDOG_ESCALATE_MILLIS: Final[str] = f"{WATCHDOG_SECTION}{KEY_SEPARATOR}escalate_millis"

WATCHDOG_ESCALATION_ENABLED: Final[str] = f"{WATCHDOG_SECTION}{KEY_SEPARATOR}escalation_enabled"

TELEMETRY_ENABLED: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}enabled"
"""Whether measurements are recorded at all."""

TELEMETRY_EXPORT_ENABLED: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}export_enabled"
"""Whether anything is handed to an exporter.

**Off by default, and that default is the security posture.** With it off no
exporter, queue, pump or thread is constructed, so "GLOBIN opens no socket" is a
property of the object graph rather than of a branch somebody could get wrong."""

TELEMETRY_LISTENER_ENABLED: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}listener_enabled"
"""Whether a Prometheus scrape endpoint is bound on loopback.

Off by default. There is deliberately no *address* setting: the library's own
default is `0.0.0.0`, and GLOBIN passes `127.0.0.1` as a literal so no
configuration value can widen it."""

TELEMETRY_LISTENER_PORT: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}listener_port"
"""Which loopback port the scrape endpoint uses when it is enabled."""

TELEMETRY_QUEUE_CAPACITY: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}queue_capacity"
"""The most batches held before the queue starts dropping."""

TELEMETRY_BATCH_SIZE: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}batch_size"
"""The most documents handed over in one attempt."""

TELEMETRY_FLUSH_MILLIS: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}flush_millis"
"""How often the exporter loop wakes."""

MINIMUM_LISTENER_PORT: Final[int] = 1_024
"""Below this a listener needs privilege on most hosts."""

MAXIMUM_LISTENER_PORT: Final[int] = 65_535
"""The highest addressable port."""

MINIMUM_QUEUE_CAPACITY: Final[int] = 1
"""A queue of nothing could never deliver."""

MAXIMUM_QUEUE_CAPACITY: Final[int] = 4_096
"""Bounded so that "the queue is bounded" is a fact rather than a promise."""

MINIMUM_FLUSH_MILLIS: Final[int] = 100
"""Below this the loop spins rather than waits."""

MAXIMUM_FLUSH_MILLIS: Final[int] = 300_000
"""Five minutes, past which a flush is not a flush."""
"""How many allocation sites a memory summary reports."""

DEFAULT_MINIMUM_FREE_BYTES: Final[int] = 268_435_456
"""256 MiB, below which the runtime filesystem check fails.

Chosen against what GLOBIN actually needs rather than as a round number. The
bounded logs area is eight mebibytes, a support bundle is capped at thirty-two, and
the state documents are kilobytes; 256 MiB leaves room for all of that several
times over while still firing long before a disk that is genuinely filling up
stops the process from publishing its own shutdown record.
"""

DEFAULT_DISK_WARNING_BYTES: Final[int] = 1_073_741_824
"""1 GiB, below which the runtime filesystem check warns.

Four times the failure threshold, so the warning band has real width: an operator
who sees amber has time to act before anything refuses.
"""

DEFAULT_MINIMUM_AVAILABLE_MEMORY_BYTES: Final[int] = 134_217_728
"""128 MiB of available host memory, below which the memory check fails."""

DEFAULT_PROCESS_RSS_WARNING_BYTES: Final[int] = 1_073_741_824
"""1 GiB resident, above which the process-memory check warns.

Deliberately a warning and never a failure. GLOBIN has no basis yet for saying what
its own resident set *ought* to be — nothing here loads market data or a model —
so a threshold that refused would be asserting a number nobody has measured.
"""

DEFAULT_BUDGET_MILLIS: Final[int] = 5_000
"""Five seconds for a whole snapshot.

Generous against what the checks cost, which is a handful of syscalls, and short
enough that a command that has stopped responding is reported rather than waited
on. ``ENGINEERING_CONTRACT.md`` invariant 2 wants a bounded failure, not a hang.
"""

DEFAULT_BUNDLE_TOTAL_INPUT_BYTES: Final[int] = 67_108_864
"""64 MiB read from disk into one bundle."""

DEFAULT_BUNDLE_ARCHIVE_BYTES: Final[int] = 33_554_432
"""32 MiB for the finished archive.

Small enough to attach to a message, which is what a support bundle is for. A
bundle that cannot be sent is a bundle that does not do its job.
"""

DEFAULT_BUNDLE_MEMBER_BYTES: Final[int] = 8_388_608
"""8 MiB for one member, above which it is truncated and marked as truncated."""

DEFAULT_BUNDLE_LOG_BYTES: Final[int] = 16_777_216
"""16 MiB of log text across every log member.

Twice the bounded size of the whole logs area, so the ordinary case is never
truncated and a logs area that has somehow grown past its own policy still cannot
fill the archive.
"""

DEFAULT_BUNDLE_MEMBER_COUNT: Final[int] = 64
"""How many members a bundle may hold.

Comfortably above the live log plus its seven rotations plus the state documents,
and far below anything that would suggest a directory was walked.
"""

DEFAULT_TRACEMALLOC_FRAME_DEPTH: Final[int] = 8
"""How many frames each traced allocation retains.

``tracemalloc``'s own default is one, which names the line that allocated and
nothing about who asked it to. Eight is enough to see through a couple of layers of
GLOBIN's own call stack, and the cost is paid per allocation rather than once.
"""

DEFAULT_TRACEMALLOC_TOP: Final[int] = 10
"""How many allocation sites a memory summary reports."""


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """How much of what GLOBIN records is worth keeping.

    Args:
        min_severity: The lowest severity a sink will write. Records below it are
            discarded.
        rotation_max_bytes: The size at which the log file is rotated.
        rotation_backup_count: How many rotated files are kept beside the live one.

    The default is :attr:`~globin.domain.observability.Severity.DEBUG`, which
    discards nothing. Two arguments land on that value independently. It
    preserves Phase 006's behaviour exactly, so adding configuration changes no
    existing output; and ``ENGINEERING_CONTRACT.md`` invariant 22 makes
    discarding data an explicit decision rather than a side effect, which a
    default of ``INFO`` would quietly violate on GLOBIN's behalf.

    That is not in tension with invariant 2, "fail closed". Failing closed
    governs *ambiguity* — an unreadable severity raises rather than falling back,
    and :func:`as_config` does exactly that. It says nothing about which value a
    declared default should be.
    """

    min_severity: Severity = Severity.DEBUG
    rotation_max_bytes: int = DEFAULT_ROTATION_MAX_BYTES
    rotation_backup_count: int = DEFAULT_ROTATION_BACKUP_COUNT

    def rotation(self) -> RotationPolicy:
        """The bound on the logs area these settings describe.

        Returns:
            The validated :class:`~globin.domain.diagnostics.RotationPolicy`.

        Raises:
            ValidationError: If the two values are outside the policy's bounds.
                Unreachable through :func:`as_config`, which refuses them first
                with a message naming the document they came from. This is the
                second of two gates, kept because a caller may construct a
                :class:`LoggingConfig` directly.

        A method rather than a field, because ``RotationPolicy(...)`` in a class
        body would be a call, and
        ``tests/architecture/test_architecture_contract.py`` holds every layer
        package to performing no work at import.
        """
        return RotationPolicy(
            max_bytes=self.rotation_max_bytes, backup_count=self.rotation_backup_count
        )


@dataclass(frozen=True, slots=True)
class DiagnosticsConfig:
    """The bounds a health snapshot and a support bundle are measured against.

    Args:
        minimum_free_bytes: Free space on a runtime filesystem below which the
            disk check fails.
        disk_warning_bytes: Free space below which it warns. Must be above the
            failure threshold, or the warning band has no width.
        minimum_available_memory_bytes: Available host memory below which the
            memory check fails.
        process_rss_warning_bytes: This process's resident set above which the
            process-memory check warns.
        budget_millis: How long a whole snapshot may take.
        bundle_total_input_bytes: How much may be read from disk into one bundle.
        bundle_archive_bytes: How large the finished archive may be.
        bundle_member_bytes: How large one member may be before truncation.
        bundle_log_bytes: How much log text may be included in total.
        bundle_member_count: How many members a bundle may hold.
        tracemalloc_enabled: Whether the allocator tracer runs.
        tracemalloc_frame_depth: How many frames each traceback retains.
        tracemalloc_top: How many allocation sites a summary reports.

    **Thirteen settings arriving in one phase is a lot, and the alternative was
    worse.** Each is a number a health check or a bundle limit compares against,
    and the only other place for such a number is a literal at the comparison —
    which is precisely the magic constant an operator cannot change and a reader
    cannot find. ``CONFIGURATION_POLICY.md`` warns that a configuration model is
    where speculative fields accumulate; none of these is speculative, because each
    has exactly one call site in this phase's own code.

    ``tracemalloc_enabled`` defaults to ``False`` and that default is load-bearing
    rather than cautious. Tracing costs the whole process on every allocation, so a
    runtime that enabled it because the setting existed would be paying a
    profiler's price for a diagnostic nobody had asked for.
    """

    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES
    disk_warning_bytes: int = DEFAULT_DISK_WARNING_BYTES
    minimum_available_memory_bytes: int = DEFAULT_MINIMUM_AVAILABLE_MEMORY_BYTES
    process_rss_warning_bytes: int = DEFAULT_PROCESS_RSS_WARNING_BYTES
    budget_millis: int = DEFAULT_BUDGET_MILLIS
    bundle_total_input_bytes: int = DEFAULT_BUNDLE_TOTAL_INPUT_BYTES
    bundle_archive_bytes: int = DEFAULT_BUNDLE_ARCHIVE_BYTES
    bundle_member_bytes: int = DEFAULT_BUNDLE_MEMBER_BYTES
    bundle_log_bytes: int = DEFAULT_BUNDLE_LOG_BYTES
    bundle_member_count: int = DEFAULT_BUNDLE_MEMBER_COUNT
    tracemalloc_enabled: bool = False
    tracemalloc_frame_depth: int = DEFAULT_TRACEMALLOC_FRAME_DEPTH
    tracemalloc_top: int = DEFAULT_TRACEMALLOC_TOP

    def thresholds(self) -> HealthThresholds:
        """The validated health bounds these settings describe.

        Returns:
            The :class:`~globin.domain.health.HealthThresholds`.

        Raises:
            ValidationError: If the values are out of range or in the wrong order.
                Unreachable through :func:`as_config`, which refuses first with a
                message naming the document. Kept as the second gate for the
                reason :meth:`LoggingConfig.rotation` keeps its own.
        """
        return HealthThresholds(
            minimum_free_bytes=self.minimum_free_bytes,
            disk_warning_bytes=self.disk_warning_bytes,
            minimum_available_memory_bytes=self.minimum_available_memory_bytes,
            process_rss_warning_bytes=self.process_rss_warning_bytes,
            budget_millis=self.budget_millis,
        )

    def limits(self) -> BundleLimits:
        """The validated bundle bounds these settings describe.

        Returns:
            The :class:`~globin.domain.support.BundleLimits`.

        Raises:
            ValidationError: If the values describe a bundle that could not be
                built.
        """
        return BundleLimits(
            total_input_bytes=self.bundle_total_input_bytes,
            archive_bytes=self.bundle_archive_bytes,
            member_bytes=self.bundle_member_bytes,
            log_bytes=self.bundle_log_bytes,
            member_count=self.bundle_member_count,
        )


@dataclass(frozen=True, slots=True)
class WatchdogConfig:
    """When silence stops being normal, and what happens then.

    Args:
        enabled: Whether the watchdog runs at all.
        interval_millis: How often it looks. Also what a first missed beat is
            measured against, which is why ``suspect`` needs no threshold of its
            own.
        grace_millis: How long start-up is given before anything is judged.
        stall_millis: How long a required component may be silent.
        escalate_millis: How long after that the process has to stop itself.
        escalation_enabled: Whether the process is ended when it does not.

    **Six settings, and the two switches are the ones worth defending.**
    ``enabled`` exists because a watchdog is a safety mechanism and an operator
    diagnosing something else must be able to take it out of the picture without
    editing code. ``escalation_enabled`` is the narrower one: it keeps the
    detection, the evidence and the graceful request, and stops only at the
    termination — which is what an operator wants while they are still learning
    what their own thresholds mean. Neither defaults to off, because a safety
    mechanism nobody switched on protects nobody.

    What is deliberately *not* here: how many threads or frames a stall dump may
    describe, and which exit code a termination leaves. The first two are bounds on
    a record's size, chosen so it stays readable, and
    ``globin.domain.watchdog`` holds them as constants on the precedent
    ``TRACEBACK_LIMIT`` set. The third is
    :attr:`~globin.domain.bootstrap.ExitCode.WATCHDOG_STALLED`, and a configurable
    exit code would let an operator set it to zero, which would tell a launcher the
    run succeeded.
    """

    enabled: bool = True
    interval_millis: int = DEFAULT_WATCHDOG_INTERVAL_MILLIS
    grace_millis: int = DEFAULT_WATCHDOG_GRACE_MILLIS
    stall_millis: int = DEFAULT_WATCHDOG_STALL_MILLIS
    escalate_millis: int = DEFAULT_WATCHDOG_ESCALATE_MILLIS
    escalation_enabled: bool = True

    def policy(self) -> WatchdogPolicy:
        """The validated thresholds these settings describe.

        Returns:
            The :class:`~globin.domain.watchdog.WatchdogPolicy`.

        Raises:
            ValidationError: If the durations describe a watchdog that could not do
                its job. Unreachable through :func:`as_config`, which refuses first
                with a message naming the document the values came from. Kept as
                the second gate for the reason :meth:`LoggingConfig.rotation` keeps
                its own: the first exists to explain, the second to guarantee.
        """
        return WatchdogPolicy(
            interval_millis=self.interval_millis,
            grace_millis=self.grace_millis,
            stall_millis=self.stall_millis,
            escalate_millis=self.escalate_millis,
        )


@dataclass(frozen=True, slots=True)
class TelemetryConfig:
    """What GLOBIN measures about itself, and whether any of it leaves.

    Args:
        enabled: Whether measurements are recorded at all.
        export_enabled: Whether anything is handed to an exporter.
        listener_enabled: Whether a scrape endpoint is bound on loopback.
        listener_port: Which loopback port it uses.
        queue_capacity: The most batches held before dropping starts.
        batch_size: The most documents handed over in one attempt.
        flush_millis: How often the exporter loop wakes.

    **Seven settings, and the two that are off by default are the interesting
    ones.** `enabled` defaults on because recording costs a dictionary write and
    an unmeasured process cannot explain itself. `export_enabled` and
    `listener_enabled` default off because each adds a capability GLOBIN otherwise
    does not have -- reaching the network, and accepting a connection -- and
    ADR-0003's zero-budget posture plus the offline-by-default rule make silence
    the right default for both.

    **There is deliberately no address setting.** `prometheus_client` defaults its
    bind address to `0.0.0.0`, which is every interface; GLOBIN passes `127.0.0.1`
    as a literal and exposes nothing that could widen it, so the absence of a
    setting here is load-bearing rather than an omission.

    What is also not here: which exporter to use. That is a parameter to
    `build_telemetry`, because `runtime/composition.py`'s own rule is that these
    functions build rather than choose -- and a configuration value that selected a
    provider would be a value that could open a socket.
    """

    enabled: bool = True
    export_enabled: bool = False
    listener_enabled: bool = False
    listener_port: int = 9_464
    queue_capacity: int = 256
    batch_size: int = 32
    flush_millis: int = 5_000


@dataclass(frozen=True, slots=True)
class GlobinConfig:
    """Everything an operator may vary, one field per subsystem that has any.

    Args:
        logging: Logging settings.
        diagnostics: Health and support-bundle settings, added in Phase 024.

    One section is the honest width today. Of everything Phases 001-006 built,
    only logging has something an operator may reasonably change: the project
    contract and the roadmap are immutable identity, the error taxonomy has
    nothing to tune, and the architecture review's two paths are constants rather
    than settings. A configuration model is exactly where speculative fields
    accumulate, and ``REPOSITORY_LAYOUT.md`` already refuses the same thing for
    directories — an entry named after a future capability is a claim that the
    capability is being worked on.

    Neither field has a default. A nested dataclass default would have to be
    written ``LoggingConfig()``, and a call in a class body is work performed at
    import, which ``tests/architecture/test_architecture_contract.py`` forbids in
    every layer package. :func:`default_config` is the supported way to obtain a
    fully-defaulted instance.
    """

    logging: LoggingConfig
    diagnostics: DiagnosticsConfig
    watchdog: WatchdogConfig
    telemetry: TelemetryConfig


@dataclass(frozen=True, slots=True)
class ConfigLayer:
    """One source's contribution: flat dotted keys, and where they came from.

    Args:
        origin: Where these values came from, in words an operator would
            recognise — a file path, or :data:`DEFAULTS_ORIGIN`. It travels with
            the values so that a later refusal can name the document at fault.
        values: Settings this layer sets, as key/value pairs. Usually easier to
            pass as a mapping; :func:`config_layer` does the conversion.

    Raises:
        ValidationError: If ``origin`` is empty, or a key is set more than once.

    Construction normalises: pairs are sorted by key, so two layers carrying the
    same settings compare equal regardless of the order they were supplied in
    (``ENGINEERING_CONTRACT.md`` invariant 3).

    A layer setting the same key twice is refused rather than resolved by
    position. Within one document that is a mistake with no defensible reading —
    unlike the *between* layers case, which is the whole point of the mechanism.
    """

    origin: str
    values: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        """Validate the origin and the keys, then canonicalise the order."""
        if not self.origin:
            msg = "configuration layer has an empty origin; name where its values came from"
            raise ValidationError(msg)

        seen: set[str] = set()
        repeated: set[str] = set()
        for key, _value in self.values:
            if key in seen:
                repeated.add(key)
            seen.add(key)
        if repeated:
            msg = f"configuration layer {self.origin!r} sets {sorted(repeated)} more than once"
            raise ValidationError(msg)

        object.__setattr__(self, "values", tuple(sorted(self.values, key=_key_of)))


def _key_of(item: tuple[str, object]) -> str:
    """Return the key of a key/value pair, for sorting.

    Args:
        item: One key/value pair.

    Returns:
        The key alone.

    Sorting by the key rather than by the whole pair is not tidiness.
    :class:`~globin.domain.observability.LogEvent` gets away with sorting whole
    items because it sorts a dictionary, whose keys are unique, so the tie-break
    on values never runs. This class accepts a tuple of pairs, where a duplicate
    key *would* reach the value comparison and raise :exc:`TypeError` on two
    values of different types. Duplicates are rejected before the sort anyway;
    keying it means the sort cannot depend on that ordering being correct.
    """
    return item[0]


def config_layer(origin: str, values: Mapping[str, object]) -> ConfigLayer:
    """Build a :class:`ConfigLayer` from a mapping.

    Args:
        origin: Where these values came from.
        values: Dotted keys mapped to their values.

    Returns:
        A canonically ordered :class:`ConfigLayer`.

    Raises:
        ValidationError: As :class:`ConfigLayer`.
    """
    return ConfigLayer(origin=origin, values=tuple(values.items()))


@dataclass(frozen=True, slots=True)
class Setting:
    """One resolved value, and the layer that won it.

    Args:
        key: The dotted setting name.
        value: Whatever the winning layer supplied, not yet validated.
        origin: The :attr:`ConfigLayer.origin` of the layer that supplied it.

    The origin is carried rather than discarded because the question an operator
    asks when configuration surprises them is never "what is the value" — they
    can see that — but "which file set it".
    """

    key: str
    value: object
    origin: str


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Every setting any layer mentioned, one entry each, sorted by key.

    Args:
        settings: The winning :class:`Setting` per key.

    Still untyped and still unvalidated: this is the output of the fold, not of
    the schema. :func:`as_config` turns it into a :class:`GlobinConfig`.
    """

    settings: tuple[Setting, ...] = ()

    def keys(self) -> tuple[str, ...]:
        """Return every key that resolved to a value.

        Returns:
            The keys, in sorted order.
        """
        return tuple(setting.key for setting in self.settings)

    def setting(self, key: str) -> Setting:
        """Return the winning setting for ``key``.

        Args:
            key: The dotted setting name.

        Returns:
            The :class:`Setting` that won.

        Raises:
            InternalError: If nothing resolved for ``key``. Callers check
                completeness before asking, so reaching this means a GLOBIN
                invariant broke rather than a document being wrong — the same
                reasoning as
                :meth:`~globin.domain.architecture.ArchitectureContract.policy_for`.
        """
        for setting in self.settings:
            if setting.key == key:
                return setting
        msg = f"no value resolved for {key!r}; resolved keys are {list(self.keys())}"
        raise InternalError(msg)


def section_keys(section: str, model: type[Any]) -> tuple[str, ...]:
    """Return the dotted key of every field on a configuration section.

    Args:
        section: The section name the fields are filed under.
        model: The frozen dataclass declaring the section's settings.

    Returns:
        One dotted key per field, in declaration order.

    ``model`` is typed :class:`typing.Any` because there is no public runtime
    type for "a dataclass". Naming it honestly is better than a cast that claims
    a precision this signature does not have — the same reasoning
    ``docs/engineering/STATIC_ANALYSIS.md`` gives for leaving
    ``disallow_any_explicit`` off.
    """
    return tuple(f"{section}{KEY_SEPARATOR}{item.name}" for item in fields(model))


def section_defaults(section: str, model: type[Any]) -> dict[str, object]:
    """Return the declared default of every field on a configuration section.

    Args:
        section: The section name the fields are filed under.
        model: The frozen dataclass declaring the section's settings.

    Returns:
        Dotted keys mapped to the defaults declared on the dataclass.

    Raises:
        InternalError: If a field declares no default. A setting that cannot be
            resolved without a configuration file makes the defaults layer
            incomplete, which is a defect in the model rather than in anything an
            operator wrote.
    """
    values: dict[str, object] = {}
    for item in fields(model):
        if item.default is MISSING:
            msg = (
                f"setting {section}{KEY_SEPARATOR}{item.name} declares no default; "
                f"every setting must resolve without a configuration file"
            )
            raise InternalError(msg)
        values[f"{section}{KEY_SEPARATOR}{item.name}"] = item.default
    return values


def known_keys() -> tuple[str, ...]:
    """Return every setting an operator may set.

    Returns:
        The dotted keys :func:`as_config` accepts, in declaration order, section
        by section.

    Derived from the dataclasses rather than written out, which is what keeps a
    new field from being half-added: declare it on the model and it is a known key,
    a default and a documented row in the same commit or not at all.
    """
    return (
        section_keys(LOGGING_SECTION, LoggingConfig)
        + section_keys(DIAGNOSTICS_SECTION, DiagnosticsConfig)
        + section_keys(WATCHDOG_SECTION, WatchdogConfig)
        + section_keys(TELEMETRY_SECTION, TelemetryConfig)
    )


def default_layer() -> ConfigLayer:
    """Return the weakest layer: every setting at its declared default.

    Returns:
        A :class:`ConfigLayer` whose origin is :data:`DEFAULTS_ORIGIN`.

    Raises:
        InternalError: As :func:`section_defaults`.

    This belongs at position zero of the sequence given to :func:`resolve`.
    Without it a document that omits a setting resolves to nothing for that key,
    and :func:`as_config` refuses.
    """
    return config_layer(
        DEFAULTS_ORIGIN,
        {
            **section_defaults(LOGGING_SECTION, LoggingConfig),
            **section_defaults(DIAGNOSTICS_SECTION, DiagnosticsConfig),
            **section_defaults(WATCHDOG_SECTION, WatchdogConfig),
            **section_defaults(TELEMETRY_SECTION, TelemetryConfig),
        },
    )


def default_config() -> GlobinConfig:
    """Return the configuration GLOBIN uses when nothing overrides anything.

    Returns:
        A :class:`GlobinConfig` with every setting at its declared default.

    Derived by construction rather than by resolution, so that
    ``tests/property/test_configuration_properties.py`` can assert the two routes
    to "the defaults" agree. If they ever disagree, one of them is lying.
    """
    return GlobinConfig(
        logging=LoggingConfig(),
        diagnostics=DiagnosticsConfig(),
        watchdog=WatchdogConfig(),
        telemetry=TelemetryConfig(),
    )


def resolve(layers: Sequence[ConfigLayer]) -> ResolvedConfig:
    """Fold ordered layers into one value per key, later layers winning.

    Args:
        layers: Weakest first, strongest last. :func:`default_layer` belongs at
            position zero.

    Returns:
        A :class:`ResolvedConfig` holding the winning :class:`Setting` for every
        key any layer mentioned, sorted by key.

    **This never raises.** It does not know the schema, so an unknown key is
    carried through rather than rejected here; refusal is :func:`as_config`'s
    job, where the schema and the origin are both available. Keeping the fold
    total is what makes it a mechanism rather than a policy, and it is the
    property Phase 027 will build its source ordering on top of.

    ``layers`` is a :class:`~collections.abc.Sequence` rather than an
    :class:`~collections.abc.Iterable` deliberately.
    :func:`~globin.domain.architecture.import_cycles` shipped a defect in Phase
    005 by reading a one-shot iterable twice and confidently reporting no cycles;
    this reads once, and declaring the narrower type removes the class of mistake
    rather than relying on it not recurring.
    """
    winners: dict[str, Setting] = {}
    for layer in layers:
        for key, value in layer.values:
            winners[key] = Setting(key=key, value=value, origin=layer.origin)
    return ResolvedConfig(settings=tuple(winners[key] for key in sorted(winners)))


def as_config(resolved: ResolvedConfig) -> GlobinConfig:
    """Validate resolved settings and build the typed model.

    Args:
        resolved: The output of :func:`resolve`.

    Returns:
        The validated :class:`GlobinConfig`.

    Raises:
        ConfigurationError: If a key is not a setting, or a value cannot be read
            as the type its setting requires. The operator edits a document, and
            the message names both the key and the document.
        InternalError: If a known setting resolved to nothing. The only way to
            reach this is to resolve without :func:`default_layer`, which no
            operator can do.

    An unknown key is refused rather than ignored. Ignoring it is how a typo
    silently disables a setting an operator believes they have set, which is the
    failure this whole module exists to prevent — and every unknown key is
    reported at once, so fixing one does not merely reveal the next.
    """
    known = known_keys()
    unknown = [item for item in resolved.settings if item.key not in known]
    if unknown:
        detail = ", ".join(f"{item.key!r} (set by {item.origin})" for item in unknown)
        msg = f"unknown setting(s): {detail}; known settings are {sorted(known)}"
        raise ConfigurationError(msg)

    resolved_keys = resolved.keys()
    missing = [key for key in known if key not in resolved_keys]
    if missing:
        msg = (
            f"no value resolved for {missing}; the defaults layer was not included "
            f"in the sequence given to resolve()"
        )
        raise InternalError(msg)

    return GlobinConfig(
        logging=LoggingConfig(
            min_severity=_severity(resolved.setting(MIN_SEVERITY)),
            rotation_max_bytes=_bounded(
                resolved.setting(ROTATION_MAX_BYTES),
                low=MINIMUM_ROTATION_BYTES,
                high=MAXIMUM_ROTATION_BYTES,
            ),
            rotation_backup_count=_bounded(
                resolved.setting(ROTATION_BACKUP_COUNT), low=0, high=MAXIMUM_BACKUP_COUNT
            ),
        ),
        diagnostics=DiagnosticsConfig(
            minimum_free_bytes=_bounded(
                resolved.setting(MINIMUM_FREE_BYTES),
                low=MINIMUM_THRESHOLD_BYTES,
                high=MAXIMUM_THRESHOLD_BYTES,
            ),
            disk_warning_bytes=_bounded(
                resolved.setting(DISK_WARNING_BYTES),
                low=MINIMUM_THRESHOLD_BYTES,
                high=MAXIMUM_THRESHOLD_BYTES,
            ),
            minimum_available_memory_bytes=_bounded(
                resolved.setting(MINIMUM_AVAILABLE_MEMORY_BYTES),
                low=MINIMUM_THRESHOLD_BYTES,
                high=MAXIMUM_THRESHOLD_BYTES,
            ),
            process_rss_warning_bytes=_bounded(
                resolved.setting(PROCESS_RSS_WARNING_BYTES),
                low=MINIMUM_THRESHOLD_BYTES,
                high=MAXIMUM_THRESHOLD_BYTES,
            ),
            budget_millis=_bounded(
                resolved.setting(BUDGET_MILLIS),
                low=MINIMUM_BUDGET_MILLIS,
                high=MAXIMUM_BUDGET_MILLIS,
            ),
            bundle_total_input_bytes=_bounded(
                resolved.setting(BUNDLE_TOTAL_INPUT_BYTES),
                low=MINIMUM_ARCHIVE_BYTES,
                high=MAXIMUM_THRESHOLD_BYTES,
            ),
            bundle_archive_bytes=_bounded(
                resolved.setting(BUNDLE_ARCHIVE_BYTES),
                low=MINIMUM_ARCHIVE_BYTES,
                high=MAXIMUM_ARCHIVE_BYTES,
            ),
            bundle_member_bytes=_bounded(
                resolved.setting(BUNDLE_MEMBER_BYTES),
                low=1,
                high=MAXIMUM_ARCHIVE_BYTES,
            ),
            bundle_log_bytes=_bounded(
                resolved.setting(BUNDLE_LOG_BYTES),
                low=1,
                high=MAXIMUM_THRESHOLD_BYTES,
            ),
            bundle_member_count=_bounded(
                resolved.setting(BUNDLE_MEMBER_COUNT), low=1, high=MAXIMUM_MEMBER_COUNT
            ),
            tracemalloc_enabled=_flag(resolved.setting(TRACEMALLOC_ENABLED)),
            tracemalloc_frame_depth=_bounded(
                resolved.setting(TRACEMALLOC_FRAME_DEPTH),
                low=MINIMUM_FRAME_DEPTH,
                high=MAXIMUM_FRAME_DEPTH,
            ),
            tracemalloc_top=_bounded(
                resolved.setting(TRACEMALLOC_TOP), low=1, high=MAXIMUM_TOP_SITES
            ),
        ),
        watchdog=WatchdogConfig(
            enabled=_flag(resolved.setting(WATCHDOG_ENABLED)),
            interval_millis=_bounded(
                resolved.setting(WATCHDOG_INTERVAL_MILLIS),
                low=MINIMUM_INTERVAL_MILLIS,
                high=MAXIMUM_INTERVAL_MILLIS,
            ),
            grace_millis=_bounded(
                resolved.setting(WATCHDOG_GRACE_MILLIS),
                low=MINIMUM_GRACE_MILLIS,
                high=MAXIMUM_GRACE_MILLIS,
            ),
            stall_millis=_bounded(
                resolved.setting(WATCHDOG_STALL_MILLIS),
                low=MINIMUM_STALL_MILLIS,
                high=MAXIMUM_STALL_MILLIS,
            ),
            escalate_millis=_bounded(
                resolved.setting(WATCHDOG_ESCALATE_MILLIS),
                low=MINIMUM_ESCALATE_MILLIS,
                high=MAXIMUM_ESCALATE_MILLIS,
            ),
            escalation_enabled=_flag(resolved.setting(WATCHDOG_ESCALATION_ENABLED)),
        ),
        telemetry=TelemetryConfig(
            enabled=_flag(resolved.setting(TELEMETRY_ENABLED)),
            export_enabled=_flag(resolved.setting(TELEMETRY_EXPORT_ENABLED)),
            listener_enabled=_flag(resolved.setting(TELEMETRY_LISTENER_ENABLED)),
            listener_port=_bounded(
                resolved.setting(TELEMETRY_LISTENER_PORT),
                low=MINIMUM_LISTENER_PORT,
                high=MAXIMUM_LISTENER_PORT,
            ),
            queue_capacity=_bounded(
                resolved.setting(TELEMETRY_QUEUE_CAPACITY),
                low=MINIMUM_QUEUE_CAPACITY,
                high=MAXIMUM_QUEUE_CAPACITY,
            ),
            batch_size=_bounded(
                resolved.setting(TELEMETRY_BATCH_SIZE),
                low=1,
                high=MAXIMUM_QUEUE_CAPACITY,
            ),
            flush_millis=_bounded(
                resolved.setting(TELEMETRY_FLUSH_MILLIS),
                low=MINIMUM_FLUSH_MILLIS,
                high=MAXIMUM_FLUSH_MILLIS,
            ),
        ),
    )


def config_fingerprint(resolved: ResolvedConfig) -> str:
    """A digest over what was configured, without publishing what was configured.

    Args:
        resolved: The output of :func:`resolve`.

    Returns:
        ``"sha256:"`` followed by 64 lowercase hexadecimal characters.

    **The point is to be able to compare two runs without disclosing either.** A
    health snapshot travels — into a support bundle, into a message an operator
    sends somewhere — and "was this machine configured the same way as that one"
    is a question worth answering without the answer carrying the configuration.
    Two runs with identical settings produce identical fingerprints; a single
    changed value changes it; and nothing about the values can be read back out.

    **Values are redacted before they are folded in**, so that a setting whose
    name looks credential-shaped contributes ``[redacted]`` rather than its
    content. No setting today holds anything sensitive — ``SECURITY_BASELINE.md``
    is explicit that a secret never arrives through configuration at all — and
    that is a property of the current register rather than of this function, so
    the redaction is applied anyway.

    **The origin is deliberately excluded.** The same values loaded from a
    different path are the same configuration, and folding the origin in would
    make a fingerprint change when somebody moved a file, which is exactly the
    false positive that trains people to ignore a comparison.
    """
    safe = redact({item.key: item.value for item in resolved.settings})
    parts = tuple(f"{key}={safe[key]!r}" for key in sorted(safe))
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _flag(setting: Setting) -> bool:
    """Read a boolean, refusing anything that is merely truthy.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The boolean.

    Raises:
        ConfigurationError: If the value is not a boolean or one of the two
            spellings below.

    The first boolean in the register, and it is stricter than Python would be.
    ``bool(value)`` would accept ``"false"`` as ``True``, which is not a corner
    case — it is the single most likely thing an operator writes when they want
    tracing off, and it would silently turn the profiler on.

    Two string spellings are accepted, ``"true"`` and ``"false"``, in any case.
    They exist for the same two reasons :func:`_bounded` accepts a digit string:
    ``CONFIGURATION_POLICY.md`` writes the documented default in a table that
    ``tests/contract/test_configuration_contract.py`` feeds back through this
    binder, and Phase 027's environment variables are strings and nothing else.
    Nothing else is accepted — not ``1``, not ``"yes"``, not ``"on"`` — because a
    value with several spellings has several ways to be typed wrong, and each of
    them fails silently in the permissive direction.
    """
    value = setting.value
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    msg = f"{setting.origin}: {setting.key} is {value!r}; expected true or false"
    raise ConfigurationError(msg)


def _bounded(setting: Setting, *, low: int, high: int) -> int:
    """Read an integer within a declared range, refusing anything else.

    Args:
        setting: The resolved setting, carrying its origin for the message.
        low: The smallest acceptable value.
        high: The largest.

    Returns:
        The integer.

    Raises:
        ConfigurationError: If the value is not an integer in range.

    **A ``bool`` is refused**, even though Python makes it an ``int``. ``true``
    resolving to a rotation size of one byte is the kind of accident that looks
    like it worked, and refusing it costs an operator nothing they meant to do.

    **A string of plain digits is accepted**, matching what :func:`_severity` does
    with a severity name. Two reasons, and the second is the load-bearing one. A
    documented default is written in a Markdown table and
    ``tests/contract/test_configuration_contract.py`` feeds that spelling back
    through this binder to prove the column is not stale, so the binder has to
    accept what the document says. And Phase 027 will resolve environment
    variables, which are strings and nothing else — a binder that only took
    integers would have to be widened then, in a phase about precedence rather
    than about types.

    *Plain* digits, checked with :meth:`str.isdigit` against the unstripped value.
    That refuses ``" 1 "``, ``"+1"``, ``"1_000"`` and ``"1.0"`` — the same
    spellings ``VALUE_TYPES_POLICY.md`` refuses for an amount, for the same reason:
    a value with two possible readings has none.

    The bound is checked here as well as in
    :class:`~globin.domain.diagnostics.RotationPolicy` deliberately. The value type
    refuses because a policy that cannot be honoured must not exist; this refuses
    because an operator who wrote a bad number deserves a message naming the file
    they wrote it in, which a :class:`ValidationError` raised deeper down cannot
    give them. Fail closed, and say where.
    """
    value = setting.value
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{setting.origin}: {setting.key} is {value!r}; expected an integer"
        raise ConfigurationError(msg)
    if not low <= value <= high:
        msg = f"{setting.origin}: {setting.key} is {value}; expected between {low} and {high}"
        raise ConfigurationError(msg)
    return value


def _severity(setting: Setting) -> Severity:
    """Read a severity from a resolved value, refusing anything else.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The :class:`~globin.domain.observability.Severity` it names.

    Raises:
        ConfigurationError: If the value is not a severity name.

    Two refusals are deliberate. **An integer is not accepted**, even though
    :class:`~globin.domain.observability.Severity` is an :class:`~enum.IntEnum`:
    ``25`` is not a member, and a threshold that silently means something between
    two levels is worse than one that refuses. **Case is exact**, matching the
    spelling in ``docs/LOGGING_POLICY.md`` and the existing behaviour of
    ``globin.adapters.architecture``. One spelling, and the message enumerates
    it, so a rejected value tells the operator what to write instead.
    """
    value = setting.value
    if isinstance(value, Severity):
        return value
    names = [member.name for member in Severity]
    if not isinstance(value, str) or value not in names:
        msg = f"{setting.origin}: {setting.key} is {value!r}; expected one of {names}"
        raise ConfigurationError(msg)
    return Severity[value]
