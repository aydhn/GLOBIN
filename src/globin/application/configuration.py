"""The use case that turns configuration sources into a validated model.

Small on purpose, and the same shape as
:class:`~globin.application.architecture_review.ArchitectureReview`: it collects
what its ports supply, then asks the domain model to judge it. There is no
parsing here, no file access, and no knowledge of TOML or of environment
variables.

The one rule this service owns is **where the defaults go**: underneath
everything. That is a policy about composition rather than about any particular
source, which is why it lives here rather than in the composition root — a
caller that assembled the sequence itself could forget the defaults layer, and
would then get an :exc:`~globin.errors.InternalError` complaining about a
setting it never touched.
"""

from dataclasses import dataclass

from globin.domain.configuration import (
    GlobinConfig,
    ResolvedConfig,
    as_config,
    default_layer,
    resolve,
)
from globin.ports.configuration import ConfigurationSource


@dataclass(frozen=True, slots=True)
class ConfigurationResolution:
    """Resolves configuration from the declared defaults plus zero or more sources.

    Args:
        sources: Weakest first, strongest last. Which sources exist and in what
            order they are consulted is
            :func:`~globin.runtime.composition.build_config_sources`'s decision;
            this service folds whatever it is given on top of the defaults.
    """

    sources: tuple[ConfigurationSource, ...]

    def resolved(self) -> ResolvedConfig:
        """Consult every source and fold the layers, without validating.

        Returns:
            The winning :class:`~globin.domain.configuration.Setting` for every key
            any layer mentioned, each still carrying the origin that set it.

        Raises:
            ConfigurationError: If a source could not produce a layer at all — an
                unreadable document, an unflattenable key, an unrecognised
                environment variable.

        **This exists so that the fingerprint and the model describe the same
        resolution.** A health snapshot records ``config_fingerprint``, and until
        Phase 027 the only caller computed it over the defaults layer alone, because
        that was the only layer there was. With real sources folded in, a fingerprint
        taken from a second, separate resolution could differ from the configuration
        the process is actually running on — and a fingerprint whose job is "were
        these two runs configured the same way" is worthless if it describes
        something other than the run.

        :meth:`run` is built on this rather than beside it, so the two cannot drift.
        """
        layers = (default_layer(), *(source.layer() for source in self.sources))
        return resolve(layers)

    def run(self) -> GlobinConfig:
        """Consult every source, fold the layers, and validate the result.

        Returns:
            The validated :class:`~globin.domain.configuration.GlobinConfig`.

        Raises:
            ConfigurationError: If any source supplied an unknown key or a value
                its setting cannot read.

        Every source is consulted, even one whose values a later source
        overrides. So a document that cannot be read, or whose keys cannot be
        flattened, is reported wherever it sits in the order — a file silently
        skipped because something stronger set the same key is exactly the
        configuration an operator later swears was applied. An unknown key is
        reported for the same reason: nothing overrides a key that is not a
        setting, so it survives the fold and is refused at binding.

        What is deliberately *not* checked is the value a losing layer supplied.
        Values are validated once, on the winner, which is what keeps
        :func:`~globin.domain.configuration.resolve` total and refusal
        single-sited. The consequence is worth stating rather than discovering: a
        layer exists precisely so that a stronger one may replace what it said,
        and a value that has been replaced has no effect to be wrong about.
        ``tests/integration/test_configuration_end_to_end.py`` holds this
        behaviour in place so that a future change to it is a decision rather
        than a regression.
        """
        return as_config(self.resolved())
