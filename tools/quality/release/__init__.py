"""The release gate: what a version is, and whether the foundation may be frozen.

Four modules, on the division ``tools/quality/governance`` established:
:mod:`~tools.quality.release.plan` holds every judgement and reads nothing,
:mod:`~tools.quality.release.manifest` is the document and its digest,
:mod:`~tools.quality.release.assets` is the published set and its checksums, and
:mod:`~tools.quality.release.gate` is the only module here that touches a disk or
starts a process.
"""
