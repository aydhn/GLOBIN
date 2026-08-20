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

from globin.domain.api_reality import ApiKeyType
from globin.domain.auth_timing import TimestampUnit, parse_recv_window
from globin.domain.diagnostics import (
    MAXIMUM_BACKUP_COUNT,
    MAXIMUM_ROTATION_BYTES,
    MINIMUM_ROTATION_BYTES,
    RotationPolicy,
)
from globin.domain.diagnostics_http import (
    LOOPBACK_IPV4,
    MAXIMUM_CONCURRENT_REQUESTS,
    MAXIMUM_PORT,
    MAXIMUM_RESPONSE_BYTES,
    MAXIMUM_TIMEOUT_SECONDS,
    MINIMUM_CONCURRENT_REQUESTS,
    MINIMUM_PORT,
    MINIMUM_RESPONSE_BYTES,
    MINIMUM_TIMEOUT_SECONDS,
    DiagnosticsHttpPolicy,
    LoopbackAddress,
    address_problems,
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
"""The section name liveness settings are filed under.

A third section, added in Phase 025, and the smallest of the three on purpose.
Only the four durations and the two switches are here; the bounds on how much
evidence a stall may gather are ``Final`` constants in
``globin.domain.watchdog``, because no operator has a basis for preferring
twenty-four frames to thirty-two and ``CONFIGURATION_POLICY.md`` warns that this is
exactly where such fields accumulate.
"""

TELEMETRY_SECTION: Final[str] = "telemetry"
"""The fourth section, added in Phase 026.

What GLOBIN measures about itself, and whether any of it leaves the machine.
The default answers are "measure" and "no".
"""

AUTH_SECTION: Final[str] = "auth"

CLOCK_SECTION: Final[str] = "clock"

"""The sixth section, added in Phase 035.

**Every key in it is about a POLICY, and none is about a secret.** A credential
lives in the Windows Credential Manager or the DPAPI vault and is named by a
reference; ``docs/security/SECURITY_BASELINE.md`` forbids one in this tree, and the
shape of this section is what makes that easy to keep rather than a rule somebody
remembers. What an operator sets here is which key type is expected, how long a
request stays valid, and whether an authenticated probe is permitted at all.

**`auth.key_type` has no default**, which is the same refusal
:func:`globin.domain.auth.algorithm_for` makes at the other end. A default would
be HMAC on every unconfigured host -- the algorithm the venue documents as
deprecated -- and it would apply silently to whatever secret happened to be
enrolled.
"""

DIAGNOSTICS_HTTP_SECTION: Final[str] = "diagnostics_http"
"""The fifth section, added in Phase 027.

Whether GLOBIN answers questions about itself over a socket, and inside what
bounds. Every switch here defaults **off** or to a value that opens nothing, so a
default bootstrap has no listener — which is the same posture
:data:`TELEMETRY_EXPORT_ENABLED` takes and for the same reason.

**Two words rather than one, unlike its four neighbours.** ``diagnostics`` is
already a section, and ``endpoint`` alone will stop being unambiguous the moment
Phases 033-048 give GLOBIN exchange endpoints to configure. The section that serves
health over HTTP should not one day have to be told apart from the section that
names a venue's base URL.
"""

DEFAULTS_ORIGIN: Final[str] = "defaults"
"""The origin recorded for values that came from the model's own declarations.

Named rather than left blank so that an error message about a defaulted value
reads the same way as one about a value from a file.
"""

ENVIRONMENT_ORIGIN: Final[str] = "environment"
"""The origin recorded for values that came from environment variables.

A word rather than a path, unlike the four document origins. There is no file to
open and no line to point at, so the most specific true thing an error message can
say is which *kind* of source set the value — and it then names the variable, which
is the part an operator can act on.
"""

COMMAND_LINE_ORIGIN: Final[str] = "command line"
"""The origin recorded for values a launcher set with ``--set``.

A word rather than a path, for the reason :data:`ENVIRONMENT_ORIGIN` gives, and
**the strongest origin there is**. The order the whole precedence follows is
narrowness: a committed document is set for every invocation, an environment
variable for a shell session, and a flag for exactly one run. The narrowest act
wins because it is the one somebody performed most deliberately and the one
they are most likely to be watching the result of.
"""

ENVIRONMENT_PREFIX: Final[str] = "GLOBIN_"
"""What every environment variable GLOBIN reads begins with.

The prefix is what makes an unrecognised variable *detectable*. Without it there
would be no way to tell "a setting spelled wrongly" from "some other program's
variable", and the choice would be between ignoring typos and refusing to start
because of somebody else's ``PATH``.
"""

PROFILE_VARIABLE: Final[str] = f"{ENVIRONMENT_PREFIX}PROFILE"
"""The variable that selects a configuration profile.

**Not a setting, and deliberately not in the register.** Which profile is active
decides *which documents are read*, so it has to be known before any document can
be opened — a value that could itself be set by one of those documents would be a
circular definition. It is therefore read from the environment and the launcher
only, and :func:`profile_from` is where the two are ordered.
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
"""How many allocation sites a memory summary reports."""

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

TELEMETRY_QUEUE_CAPACITY: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}queue_capacity"
"""The most batches held before the queue starts dropping."""

TELEMETRY_BATCH_SIZE: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}batch_size"
"""The most documents handed over in one attempt."""

TELEMETRY_FLUSH_MILLIS: Final[str] = f"{TELEMETRY_SECTION}{KEY_SEPARATOR}flush_millis"
"""How often the exporter loop wakes."""

ENDPOINT_ENABLED: Final[str] = f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}enabled"
"""Whether the diagnostics surface binds a socket at all.

**Off by default, and the default is the posture.** With it off no server, socket,
queue or worker thread is constructed, so "GLOBIN is listening on nothing" is a
property of the object graph rather than of a branch somebody could get wrong.
"""

ENDPOINT_BIND_HOST: Final[str] = f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}bind_host"
"""Which loopback address the surface binds.

**A setting, and it still cannot be widened.** Phase 026 refused an address setting
outright, on the grounds that a configurable address is one typo away from
publishing this process's internals. That reasoning was right about the danger and
reached for the wrong instrument: a literal keeps the address safe while making IPv6
unreachable, and it puts the guarantee in a constant somebody could edit rather than
in a type. What replaces it is
:class:`~globin.domain.diagnostics_http.LoopbackAddress`, which refuses anything
:mod:`ipaddress` does not call loopback — so the *field itself cannot hold* a
wildcard, a LAN address, or a hostname, and the refusal covers spellings no denylist
would have thought of. ADR-0072 records the exchange.
"""

ENDPOINT_PORT: Final[str] = f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}port"
"""Which port the surface binds."""

ENDPOINT_REQUEST_TIMEOUT_SECONDS: Final[str] = (
    f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}request_timeout_seconds"
)
"""How long one request may occupy a worker before its socket times out."""

ENDPOINT_SHUTDOWN_TIMEOUT_SECONDS: Final[str] = (
    f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}shutdown_timeout_seconds"
)
"""How long in-flight requests are given to finish during an orderly stop."""

ENDPOINT_MAX_CONCURRENT_REQUESTS: Final[str] = (
    f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}max_concurrent_requests"
)
"""How many requests may be in flight at once, which is also the worker count."""

ENDPOINT_MAX_RESPONSE_BYTES: Final[str] = (
    f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}max_response_bytes"
)
"""The largest body the surface will send."""

ENDPOINT_SNAPSHOT_ENABLED: Final[str] = (
    f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}diagnostics_snapshot_enabled"
)
"""Whether the snapshot route answers.

Off by default even when the surface is on, because it is the most detailed thing
the surface can say about this process and the only one an operator has to opt into
twice.
"""

AUTH_KEY_TYPE: Final[str] = f"{AUTH_SECTION}{KEY_SEPARATOR}key_type"

AUTH_RECV_WINDOW_MILLIS: Final[str] = f"{AUTH_SECTION}{KEY_SEPARATOR}recv_window_millis"

AUTH_TIMESTAMP_UNIT: Final[str] = f"{AUTH_SECTION}{KEY_SEPARATOR}timestamp_unit"

AUTH_PROBE_ENABLED: Final[str] = f"{AUTH_SECTION}{KEY_SEPARATOR}probe_enabled"

AUTH_ALLOW_PRODUCTION_PROBE: Final[str] = f"{AUTH_SECTION}{KEY_SEPARATOR}allow_production_probe"

CLOCK_SAMPLE_COUNT: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}sample_count"

CLOCK_FRESHNESS_TTL_MILLIS: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}freshness_ttl_millis"

CLOCK_DEGRADED_GRACE_MILLIS: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}degraded_grace_millis"

CLOCK_MAX_ROUND_TRIP_MILLIS: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}max_round_trip_millis"

CLOCK_MAX_UNCERTAINTY_MILLIS: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}max_uncertainty_millis"

CLOCK_MAX_OFFSET_JUMP_MILLIS: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}max_offset_jump_millis"

CLOCK_MAX_WALL_DIVERGENCE_MILLIS: Final[str] = (
    f"{CLOCK_SECTION}{KEY_SEPARATOR}max_wall_divergence_millis"
)

CLOCK_NETWORK_BUDGET_MILLIS: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}network_budget_millis"

CLOCK_REQUIRE_CALIBRATION: Final[str] = f"{CLOCK_SECTION}{KEY_SEPARATOR}require_calibration"

MINIMUM_CLOCK_SAMPLES: Final[int] = 1
"""The fewest calibration samples a window may keep."""

MAXIMUM_CLOCK_SAMPLES: Final[int] = 16
"""The most a window may keep, matching :data:`globin.domain.clock_sync.MAX_SAMPLE_COUNT`.

Restated here because this module may not import the clock layer -- both are in the
domain layer and a cycle would follow -- and compared against it by
``tests/contract/test_clock_contract.py`` so the two cannot drift.
"""

MINIMUM_CLOCK_INTERVAL_MILLIS: Final[int] = 1
"""The shortest interval any clock threshold may be. Zero would disable a gate."""

MAXIMUM_CLOCK_INTERVAL_MILLIS: Final[int] = 86_400_000
"""The longest, one day.

A bound rather than a preference: a freshness interval of a year is not a
configuration, it is the calibration gate being switched off by arithmetic, and
``docs/CONFIGURATION_POLICY.md`` asks that a setting which could disable a safety
property be bounded rather than trusted.
"""

ENDPOINT_METRICS_ENABLED: Final[str] = f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}metrics_enabled"
"""Whether the scrape route answers."""

ENDPOINT_HEALTH_ENABLED: Final[str] = f"{DIAGNOSTICS_HTTP_SECTION}{KEY_SEPARATOR}health_enabled"
"""Whether the three health routes answer.

A single switch for all three rather than one each. Liveness, readiness and the
runtime snapshot are what a supervisor asks in sequence, and an installation that
wanted liveness without readiness would be configuring a supervisor that cannot
work.
"""

MINIMUM_QUEUE_CAPACITY: Final[int] = 1
"""A queue of nothing could never deliver."""

MAXIMUM_QUEUE_CAPACITY: Final[int] = 4_096
"""Bounded so that "the queue is bounded" is a fact rather than a promise."""

MINIMUM_FLUSH_MILLIS: Final[int] = 100
"""Below this the loop spins rather than waits."""

MAXIMUM_FLUSH_MILLIS: Final[int] = 300_000
"""Five minutes, past which a flush is not a flush."""

DEFAULT_ENDPOINT_PORT: Final[int] = 9_464
"""Which port the diagnostics surface binds by default.

Inherited from the scrape listener Phase 026 declared and never started, rather than
chosen afresh. It is the port the OpenTelemetry project's own Prometheus exporter
uses, so a scrape configuration written against any other OpenTelemetry deployment
already points at it — and reusing the number means the one this repository has
already documented does not become the one that used to be right.
"""

DEFAULT_ENDPOINT_REQUEST_TIMEOUT_SECONDS: Final[int] = 5
"""Five seconds for one request.

Matched to :data:`DEFAULT_BUDGET_MILLIS`, which is the health snapshot's own budget
and therefore the longest honest answer any route has to produce. A shorter timeout
would cut off the slowest legitimate request; a longer one would hold a worker past
the point at which the work should already have finished or failed.
"""

DEFAULT_ENDPOINT_SHUTDOWN_TIMEOUT_SECONDS: Final[int] = 5
"""How long in-flight requests get to finish when the process is stopping.

The same five seconds, for the same reason: a request that arrived a moment before
the stop is entitled to exactly the time a request is ever entitled to, and no more.
"""

DEFAULT_ENDPOINT_MAX_CONCURRENT_REQUESTS: Final[int] = 4
"""How many requests may be in flight at once, and therefore how many workers exist.

Four, against a realistic load of one scraper and one supervisor. This surface is
not a service with users; it answers a handful of pollers on a fixed interval, and a
number chosen for an imagined crowd would be four threads that exist to be idle.
Capacity beyond this is refused deterministically rather than queued indefinitely,
so the honest small number is also the safe one.
"""

DEFAULT_ENDPOINT_MAX_RESPONSE_BYTES: Final[int] = 1_048_576
"""One mebibyte.

Comfortably above every document this surface serves — the largest is a health
snapshot, which is tens of kilobytes — and small enough that a body which somehow
grew past it is refused while the mistake is still cheap.
"""

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
        queue_capacity: The most batches held before dropping starts.
        batch_size: The most documents handed over in one attempt.
        flush_millis: How often the exporter loop wakes.

    **Five settings, and the one that is off by default is the interesting one.**
    `enabled` defaults on because recording costs a dictionary write and an
    unmeasured process cannot explain itself. `export_enabled` defaults off because
    it adds a capability GLOBIN otherwise does not have -- reaching the network --
    and ADR-0003's zero-budget posture plus the offline-by-default rule make silence
    the right default.

    **Phase 026's two `listener_` settings are gone, and this is where they went.**
    They described a scrape endpoint that nothing ever started, serving a registry
    GLOBIN never populated. Phase 027 built the endpoint properly, and it serves
    health as well as metrics, so its settings belong to
    :class:`DiagnosticsHttpConfig` rather than here. Leaving a second, dormant way
    to open a socket beside a working one would have been exactly the "second
    independent source of truth" this repository refuses. ADR-0072 records it.

    What is also not here: which exporter to use. That is a parameter to
    `build_telemetry`, because `runtime/composition.py`'s own rule is that these
    functions build rather than choose -- and a configuration value that selected a
    provider would be a value that could open a socket.
    """

    enabled: bool = True
    export_enabled: bool = False
    queue_capacity: int = 256
    batch_size: int = 32
    flush_millis: int = 5_000


@dataclass(frozen=True, slots=True)
class DiagnosticsHttpConfig:
    """Whether GLOBIN answers questions about itself over a socket, and inside what.

    Args:
        enabled: Whether a socket is bound at all.
        bind_host: Which loopback address. Validated as a loopback address, so it
            cannot name anything another machine could reach.
        port: Which port.
        request_timeout_seconds: How long one request may occupy a worker.
        shutdown_timeout_seconds: How long in-flight requests get to finish.
        max_concurrent_requests: How many requests may be in flight, which is also
            exactly how many worker threads exist.
        max_response_bytes: The largest body that will be sent.
        diagnostics_snapshot_enabled: Whether the snapshot route answers.
        metrics_enabled: Whether the scrape route answers.
        health_enabled: Whether the three health routes answer.

    **Ten settings, of which two are switches that default off and five are
    bounds.** That ratio is the shape of the feature: almost everything an operator
    may vary here is a limit, because a read-only surface's only real degrees of
    freedom are where it listens and how much work it will do.

    **`enabled` off by default means the object graph, not a branch.** Nothing in
    :func:`~globin.runtime.composition.build_diagnostics_endpoint` constructs a
    server, a socket, a queue or a thread when this is false, so a default
    bootstrap cannot be listening whatever else is wrong.

    The three route switches are separate from `enabled` because they answer a
    different question. `enabled` is "may this process be asked anything"; the
    others are "which of the things it could say is it willing to say". An operator
    who wants liveness for a supervisor and no metrics for anybody sets them
    independently, and an installation that wants nothing turns off the one switch
    above them all.
    """

    enabled: bool = False
    bind_host: str = LOOPBACK_IPV4
    port: int = DEFAULT_ENDPOINT_PORT
    request_timeout_seconds: int = DEFAULT_ENDPOINT_REQUEST_TIMEOUT_SECONDS
    shutdown_timeout_seconds: int = DEFAULT_ENDPOINT_SHUTDOWN_TIMEOUT_SECONDS
    max_concurrent_requests: int = DEFAULT_ENDPOINT_MAX_CONCURRENT_REQUESTS
    max_response_bytes: int = DEFAULT_ENDPOINT_MAX_RESPONSE_BYTES
    diagnostics_snapshot_enabled: bool = False
    metrics_enabled: bool = True
    health_enabled: bool = True

    def policy(self) -> DiagnosticsHttpPolicy:
        """The validated bounds a server would run under.

        Returns:
            The policy.

        Raises:
            ValidationError: If the address is not loopback, or a bound is outside
                its permitted range.

        A method rather than a field, matching :meth:`LoggingConfig.rotation` and
        :meth:`WatchdogConfig.policy`: the section holds what an operator wrote and
        this turns it into the value type the rest of the system uses. Calling it is
        also how a caller finds out that a configuration is unusable *before* a
        socket exists, which is what makes the surface fail closed.
        """
        return DiagnosticsHttpPolicy(
            address=LoopbackAddress(self.bind_host),
            port=self.port,
            request_timeout_seconds=self.request_timeout_seconds,
            shutdown_timeout_seconds=self.shutdown_timeout_seconds,
            max_concurrent_requests=self.max_concurrent_requests,
            max_response_bytes=self.max_response_bytes,
        )


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """How GLOBIN authenticates a REST request, and whether it may send one.

    Args:
        key_type: Which API key type is expected, as its
            :class:`~globin.domain.api_reality.ApiKeyType` value. Empty means
            **not configured**, which is a different state from a wrong one.
        recv_window_millis: How long a signed request stays valid, in
            milliseconds, **as text**.
        timestamp_unit: Which unit the ``timestamp`` parameter carries.
        probe_enabled: Whether the authenticated read-only probe may run at all.
        allow_production_probe: Whether it may run against the live exchange.

    **`recv_window_millis` is a string and that is not an oversight.** The venue
    documents *"up to three decimal places of precision (e.g., 6000.346)"*, and
    ``6000.346`` is not representable as a binary float — a TOML float would have
    changed the number before any type could refuse it, and a TOML integer could
    not express it at all. Reading the operator's own characters and parsing them
    into a :class:`~decimal.Decimal` at
    :func:`~globin.domain.auth_timing.parse_recv_window` means the value that
    reaches the venue is the value they wrote.

    **`key_type` defaults to empty rather than to a key type.** A default here
    would be a global assumption about which algorithm a host uses, applied to
    whatever secret happens to be enrolled, and the obvious default is the one the
    venue calls deprecated. Empty produces
    :attr:`~globin.domain.auth.AuthStatus.MISSING_CREDENTIAL` with a message
    naming what to enrol.

    **Two switches for the probe, not one**, and the second is not redundant.
    ``probe_enabled`` says an authenticated read-only request may be made at all;
    ``allow_production_probe`` says it may be made against the environment where
    an order would move capital. An operator who turns the first on for testnet has
    not thereby consented to the second, and a single switch would make those the
    same decision.
    """

    key_type: str = ""
    recv_window_millis: str = "5000"
    timestamp_unit: str = "milliseconds"
    probe_enabled: bool = False
    allow_production_probe: bool = False


@dataclass(frozen=True, slots=True)
class ClockConfig:
    """How much GLOBIN must trust a venue clock before it signs anything.

    Args:
        sample_count: How many calibration samples the window keeps.
        freshness_ttl_millis: How long a sample stays fresh enough to sign with.
        degraded_grace_millis: How long a sample keeps a domain describable after
            a probe failure.
        max_round_trip_millis: The slowest usable round trip.
        max_uncertainty_millis: The widest admissible error bound.
        max_offset_jump_millis: How far the estimated offset may move between
            calibrations before it is disbelieved.
        max_wall_divergence_millis: How far the host's two clocks may disagree
            before a wall-clock adjustment is declared.
        network_budget_millis: The unobservable delay a signed request is assumed
            to meet.
        require_calibration: Whether a signed request needs a fresh calibration.

    **Every default here is the safe one, and one of them is not adjustable
    downward in effect.** ``require_calibration`` defaults to ``True`` and turning
    it off does not make GLOBIN sign against an unsynchronised clock -- nothing
    consults it in :func:`globin.domain.clock_sync.admit`, which refuses on the
    state alone. It exists so an operator can say *this host is not expected to
    reach a venue at all*, and so a diagnostic can report that intent rather than
    reporting an absence.

    **The thresholds are milliseconds because operators write milliseconds**, and
    the venue documents its own bounds in them. They become
    :class:`~globin.domain.clock.Duration` values at
    :func:`globin.adapters.clock_sync.discipline_from`, which is also where a set
    that contradicts itself is refused -- so a configuration whose freshness
    interval outlives its own degraded grace fails at ``config.valid`` and exit
    ``14``, not at the first request.
    """

    sample_count: int = 5
    freshness_ttl_millis: int = 300_000
    degraded_grace_millis: int = 900_000
    max_round_trip_millis: int = 2_000
    max_uncertainty_millis: int = 250
    max_offset_jump_millis: int = 1_000
    max_wall_divergence_millis: int = 500
    network_budget_millis: int = 1_000
    require_calibration: bool = True


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
    diagnostics_http: DiagnosticsHttpConfig
    auth: AuthConfig
    clock: ClockConfig


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
        + section_keys(DIAGNOSTICS_HTTP_SECTION, DiagnosticsHttpConfig)
        + section_keys(AUTH_SECTION, AuthConfig)
        + section_keys(CLOCK_SECTION, ClockConfig)
    )


def environment_variable(key: str) -> str:
    """The environment variable that sets one setting.

    Args:
        key: The dotted setting key.

    Returns:
        The variable name, prefixed and upper-cased.

    **Derived, never declared, and checked for collisions in both directions.** A
    hand-written table would be a second place to add a setting and therefore a
    place to forget one. What derivation costs is the possibility of two keys
    collapsing onto one name — ``a.b_c`` and ``a_b.c`` both become ``GLOBIN_A_B_C``
    — and the answer is not to hope: ``tests/contract/test_configuration_contract.py``
    asserts the map is injective over :func:`known_keys`, so a colliding pair fails
    the suite instead of silently making one setting unreachable.

    Upper case with underscores because that is what an environment variable looks
    like on every platform GLOBIN runs on, and because Windows compares variable
    names case-insensitively — a lower-case scheme would give two spellings of one
    name on one host and two distinct names on another.
    """
    return f"{ENVIRONMENT_PREFIX}{key.replace(KEY_SEPARATOR, '_').upper()}"


def environment_names() -> tuple[tuple[str, str], ...]:
    """Every setting, paired with the variable that sets it.

    Returns:
        Pairs of ``(variable name, dotted key)``, in :func:`known_keys` order.

    The mapping an environment source reads, in the direction it needs: given a
    variable, which setting is it. Built from :func:`known_keys` so that a section
    added to the model is settable from the environment in the same commit, with no
    second list to update.
    """
    return tuple((environment_variable(key), key) for key in known_keys())


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
            **section_defaults(DIAGNOSTICS_HTTP_SECTION, DiagnosticsHttpConfig),
            **section_defaults(AUTH_SECTION, AuthConfig),
            **section_defaults(CLOCK_SECTION, ClockConfig),
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
        diagnostics_http=DiagnosticsHttpConfig(),
        auth=AuthConfig(),
        clock=ClockConfig(),
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
        diagnostics_http=DiagnosticsHttpConfig(
            enabled=_flag(resolved.setting(ENDPOINT_ENABLED)),
            bind_host=_loopback(resolved.setting(ENDPOINT_BIND_HOST)),
            port=_bounded(resolved.setting(ENDPOINT_PORT), low=MINIMUM_PORT, high=MAXIMUM_PORT),
            request_timeout_seconds=_bounded(
                resolved.setting(ENDPOINT_REQUEST_TIMEOUT_SECONDS),
                low=MINIMUM_TIMEOUT_SECONDS,
                high=MAXIMUM_TIMEOUT_SECONDS,
            ),
            shutdown_timeout_seconds=_bounded(
                resolved.setting(ENDPOINT_SHUTDOWN_TIMEOUT_SECONDS),
                low=MINIMUM_TIMEOUT_SECONDS,
                high=MAXIMUM_TIMEOUT_SECONDS,
            ),
            max_concurrent_requests=_bounded(
                resolved.setting(ENDPOINT_MAX_CONCURRENT_REQUESTS),
                low=MINIMUM_CONCURRENT_REQUESTS,
                high=MAXIMUM_CONCURRENT_REQUESTS,
            ),
            max_response_bytes=_bounded(
                resolved.setting(ENDPOINT_MAX_RESPONSE_BYTES),
                low=MINIMUM_RESPONSE_BYTES,
                high=MAXIMUM_RESPONSE_BYTES,
            ),
            diagnostics_snapshot_enabled=_flag(resolved.setting(ENDPOINT_SNAPSHOT_ENABLED)),
            metrics_enabled=_flag(resolved.setting(ENDPOINT_METRICS_ENABLED)),
            health_enabled=_flag(resolved.setting(ENDPOINT_HEALTH_ENABLED)),
        ),
        auth=AuthConfig(
            key_type=_key_type(resolved.setting(AUTH_KEY_TYPE)),
            recv_window_millis=_window(resolved.setting(AUTH_RECV_WINDOW_MILLIS)),
            timestamp_unit=_timestamp_unit(resolved.setting(AUTH_TIMESTAMP_UNIT)),
            probe_enabled=_flag(resolved.setting(AUTH_PROBE_ENABLED)),
            allow_production_probe=_flag(resolved.setting(AUTH_ALLOW_PRODUCTION_PROBE)),
        ),
        clock=ClockConfig(
            sample_count=_bounded(
                resolved.setting(CLOCK_SAMPLE_COUNT),
                low=MINIMUM_CLOCK_SAMPLES,
                high=MAXIMUM_CLOCK_SAMPLES,
            ),
            freshness_ttl_millis=_interval(resolved.setting(CLOCK_FRESHNESS_TTL_MILLIS)),
            degraded_grace_millis=_interval(resolved.setting(CLOCK_DEGRADED_GRACE_MILLIS)),
            max_round_trip_millis=_interval(resolved.setting(CLOCK_MAX_ROUND_TRIP_MILLIS)),
            max_uncertainty_millis=_interval(resolved.setting(CLOCK_MAX_UNCERTAINTY_MILLIS)),
            max_offset_jump_millis=_interval(resolved.setting(CLOCK_MAX_OFFSET_JUMP_MILLIS)),
            max_wall_divergence_millis=_interval(
                resolved.setting(CLOCK_MAX_WALL_DIVERGENCE_MILLIS)
            ),
            network_budget_millis=_interval(resolved.setting(CLOCK_NETWORK_BUDGET_MILLIS)),
            require_calibration=_flag(resolved.setting(CLOCK_REQUIRE_CALIBRATION)),
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


def _loopback(setting: Setting) -> str:
    """Read a loopback address, refusing every address that is not one.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The address, exactly as written.

    Raises:
        ConfigurationError: If the value is not a string, or is not a literal
            loopback address.

    **The first setting in the register whose value is refused for what it *means*
    rather than for its type.** A port outside its range is a number in the wrong
    place; a bind address outside loopback is a decision to expose this process, and
    the error message says so rather than reporting a failed parse.

    A :class:`~globin.errors.ConfigurationError` rather than the
    :class:`~globin.errors.ValidationError`
    :class:`~globin.domain.diagnostics_http.LoopbackAddress` would raise, because at
    this point the value came out of a document an operator wrote and the taxonomy's
    axis is *who must act*. The judgement itself is not restated here — it is
    :func:`~globin.domain.diagnostics_http.address_problems`, so the value type and
    the binder cannot come to different conclusions.
    """
    value = setting.value
    if not isinstance(value, str):
        msg = (
            f"{setting.origin}: {setting.key} is {value!r}; expected a loopback "
            f"address written as a string"
        )
        raise ConfigurationError(msg)
    problems = address_problems(value)
    if problems:
        msg = f"{setting.origin}: {setting.key} is unusable: {'; '.join(problems)}"
        raise ConfigurationError(msg)
    return value


def _interval(setting: Setting) -> int:
    """Read a clock threshold in milliseconds, within the declared bounds.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The interval in milliseconds.

    Raises:
        ConfigurationError: If the value is not an integer between
            :data:`MINIMUM_CLOCK_INTERVAL_MILLIS` and
            :data:`MAXIMUM_CLOCK_INTERVAL_MILLIS`.

    A named binder rather than eight repetitions of :func:`_bounded` with the same
    two arguments, so the bounds are stated once and a ninth threshold cannot be
    added with different ones by accident.

    **This is the outer bound only.** Whether a *set* of thresholds is coherent --
    a degraded grace shorter than the freshness interval, an uncertainty limit that
    would make its own gate unreachable -- is
    :class:`globin.domain.clock_sync.ClockDiscipline`'s judgement, and it is made
    where the whole set is visible rather than one field at a time.
    """
    return _bounded(setting, low=MINIMUM_CLOCK_INTERVAL_MILLIS, high=MAXIMUM_CLOCK_INTERVAL_MILLIS)


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

    *Plain* digits, checked with :meth:`str.isdecimal` against the unstripped value.
    That refuses ``" 1 "``, ``"+1"``, ``"1_000"`` and ``"1.0"`` — the same
    spellings ``VALUE_TYPES_POLICY.md`` refuses for an amount, for the same reason:
    a value with two possible readings has none.

    **:meth:`str.isdecimal` rather than :meth:`str.isdigit`, and the difference is a
    bug rather than a nicety.** ``isdigit`` is true for characters :func:`int` refuses
    — a superscript two among them — so the pair ``isdigit`` then ``int`` raises
    :exc:`ValueError` on input it had just declared acceptable. That escapes the error
    taxonomy entirely: :func:`~globin.runtime.cli.main` catches
    :class:`~globin.errors.GlobinError` and :exc:`OSError`, so an operator would have
    got a traceback instead of a sentence naming their setting. The path was
    unreachable while every string value came from a TOML document; Phase 027's
    environment variables are strings and nothing else, which is what made it live and
    what a property test then found.

    The bound is checked here as well as in
    :class:`~globin.domain.diagnostics.RotationPolicy` deliberately. The value type
    refuses because a policy that cannot be honoured must not exist; this refuses
    because an operator who wrote a bad number deserves a message naming the file
    they wrote it in, which a :class:`ValidationError` raised deeper down cannot
    give them. Fail closed, and say where.
    """
    value = setting.value
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{setting.origin}: {setting.key} is {value!r}; expected an integer"
        raise ConfigurationError(msg)
    if not low <= value <= high:
        msg = f"{setting.origin}: {setting.key} is {value}; expected between {low} and {high}"
        raise ConfigurationError(msg)
    return value


def _key_type(setting: Setting) -> str:
    """Read a configured API key type, or the empty string meaning unconfigured.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The key type's value, or ``""``.

    Raises:
        ConfigurationError: If the value is neither empty nor a real key type.

    **Empty is accepted and every other unknown value is refused**, which is the
    distinction the whole section turns on. An operator who has configured nothing
    gets :attr:`~globin.domain.auth.AuthStatus.MISSING_CREDENTIAL` with a message
    telling them what to enrol; an operator who wrote ``ecdsa`` gets told here,
    against a document, rather than discovering at a venue that their key type does
    not exist.

    The value is compared against
    :class:`~globin.domain.api_reality.ApiKeyType` rather than against a list
    spelled here, so a key type the venue documents and this repository has not
    implemented cannot be configured, and a fourth one cannot be added to this
    module without the registry knowing about it.
    """
    value = setting.value
    if not isinstance(value, str):
        msg = f"{setting.origin}: {setting.key} is {value!r}; expected a string"
        raise ConfigurationError(msg)
    if not value:
        return ""
    names = [member.value for member in ApiKeyType]
    if value not in names:
        msg = (
            f"{setting.origin}: {setting.key} is {value!r}; expected one of {names}, "
            "or an empty string meaning no key type is configured"
        )
        raise ConfigurationError(msg)
    return value


def _window(setting: Setting) -> str:
    """Read a validity window, checking the venue would accept it.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The window as the operator wrote it.

    Raises:
        ConfigurationError: If the value is not text, or names a window outside
            what the venue documents.

    **Text in and text out**, and the round trip is deliberate. The value is parsed
    here only to be *validated*: a float would have lost the venue's documented
    third decimal place before this function saw it, so the operator's own
    characters are what is stored and what
    :func:`~globin.domain.auth_timing.parse_recv_window` reads again at the point of
    use. Validating here means a window the venue would reject fails against a
    document rather than against a request.

    **A number is refused rather than converted.** TOML has an integer type and a
    float type, and accepting either would make ``recv_window_millis = 6000.346``
    silently become a value nobody wrote. Refusing the type gives a message about
    the type, which is what the operator can act on.
    """
    value = setting.value
    if not isinstance(value, str):
        msg = (
            f"{setting.origin}: {setting.key} is {value!r}; expected a quoted string such as "
            '"5000" or "6000.346" — a TOML number cannot hold the three decimal places the '
            "venue documents"
        )
        raise ConfigurationError(msg)
    try:
        parse_recv_window(value)
    except ValidationError as fault:
        msg = f"{setting.origin}: {setting.key} is {value!r}; {fault}"
        raise ConfigurationError(msg) from fault
    return value


def _timestamp_unit(setting: Setting) -> str:
    """Read which unit a request's timestamp is expressed in.

    Args:
        setting: The resolved setting, carrying its origin for the message.

    Returns:
        The unit's value.

    Raises:
        ConfigurationError: If the value is not one the venue documents.

    Two spellings and no third, because the venue documents exactly two:
    *"the current timestamp either in milliseconds or microseconds."*
    """
    value = setting.value
    names = [member.value for member in TimestampUnit]
    if not isinstance(value, str) or value not in names:
        msg = f"{setting.origin}: {setting.key} is {value!r}; expected one of {names}"
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
