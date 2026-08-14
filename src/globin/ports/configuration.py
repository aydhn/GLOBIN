"""The port through which configuration values enter GLOBIN.

One contract, with one method. A source produces a
:class:`~globin.domain.configuration.ConfigLayer` — a flat set of dotted keys and
the name of where they came from — and knows nothing about what any of them mean.
Validation is the domain's job, so a new source cannot arrive with its own idea
of what ``"WARNING"`` parses to.

The port is what makes Phase 027 an addition rather than a rewrite. Environment
variables, a launcher's selection and a profile file are each a
:class:`ConfigurationSource`; deciding which of them exist and in what order they
are consulted is that phase's work, and nothing here or in the application layer
has to change to accommodate it.
"""

from typing import Protocol

from globin.domain.configuration import ConfigLayer


class ConfigurationSource(Protocol):
    """Supplies one layer of configuration values."""

    def layer(self) -> ConfigLayer:
        """Return this source's contribution.

        Returns:
            A :class:`~globin.domain.configuration.ConfigLayer` whose origin
            identifies this source in words an operator would recognise.

        A source that has nothing to say returns a layer with no values rather
        than ``None``. An empty layer is the identity element of the fold, so
        the caller needs no special case, and the origin still records that the
        source was consulted.
        """
        ...
