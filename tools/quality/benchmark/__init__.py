"""Which workloads actually benefit from GPU execution on this host.

Phase 023 asked whether a device exists and recorded the answer as a state. This
asks the question that one deliberately refused: for a workload GLOBIN actually
schedules, does moving it to the device pay? It is the harness ``ROADMAP.md`` row
024 names, and it reaches no network.

**It measures rather than assumes, and it records rather than concludes.**
``docs/engineering/benchmark-contract.toml`` declares the workloads, the method
and the thresholds; this package runs what it can, records the nanoseconds, and
recomputes every verdict from those numbers on each run. A contract entry claiming
a workload benefits whose own figures do not support it fails without anybody
having to notice.

**Almost everything is `UNAVAILABLE` today, and that is the honest answer rather
than a hole.** ``wheel-survey.toml`` files no library under phase 24 and ``torch``
is Phase 183, so nothing installed here can reach a CUDA device. The harness
exists so that Phase 183 has somewhere to put its answer and so that the answer
will be a measurement. Recording *why* a question could not be answered is the
whole of ADR-0045, and it is what distinguishes this from an empty file.

**A timing is not reproducible; a verdict is.** Two runs on one host produce
different nanoseconds, so the manifest separates ``run.observed`` — measurements,
which move — from ``findings``, which are a function of the contract and those
measurements and are recomputed every time. Nothing here claims byte-identical
evidence across runs, and the documentation says so rather than leaving a reader
to discover it.
"""
