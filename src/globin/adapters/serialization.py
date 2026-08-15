"""JSON, rendered so that reading it back returns what was written.

The representation GLOBIN persists in, and the only implementation of
:class:`globin.ports.serialization.Codec` there is. JSON is chosen because it is
readable by a person with no tooling, is in the standard library so ADR-0003 has
nothing to weigh, and is what the quality evidence has already been written in
for two phases.

**The standard library will not give round-trip identity on its own.** Three of
its defaults quietly break it, and each is closed below rather than documented as
a caveat:

*Non-string keys are coerced.* ``json.dumps({1: "a"})`` returns ``{"1": "a"}``
without complaint, so a document read back is not the document written. The key
type is checked before rendering.

*Non-finite numbers are invented.* ``json.dumps(float("nan"))`` emits the bare
word ``NaN``, and ``json.loads`` accepts it — neither appears in RFC 8259, so the
result is a file only Python can read. ``allow_nan=False`` closes the writing
half and ``parse_constant`` closes the reading half.

*Floats are native, so nothing stops one.* :mod:`globin.domain.values` refuses to
build a magnitude from a float, and a codec that accepted one would reintroduce
at the storage boundary exactly what that module refuses at the construction
boundary. Both directions refuse: ``parse_float`` on the way in, an explicit walk
on the way out.

Rendering is deterministic. ``sort_keys`` puts the keys in one order whatever
order they were built in, which is what makes two runs of the same work produce
the same bytes — ``ENGINEERING_CONTRACT.md`` invariant 3 — and what lets a digest
over the result mean anything. ``ensure_ascii`` keeps the output to characters
every console and diff tool on this project's platform can render, which is the
same rule the quality tooling holds itself to.

This module performs no I/O, which is unusual for an adapter and is explained in
:mod:`globin.ports.serialization`: it implements a choice about the outside world
rather than a conversation with it. It therefore imports nothing from the
I/O-capable list, and ``tests/architecture`` holds it to that like any other
module.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Final

from globin.errors import ValidationError

SEPARATORS: Final[tuple[str, str]] = (",", ":")
"""How ``json.dumps`` joins items and pairs.

Compact, with no cosmetic whitespace. A stored record is read by a program;
somebody reading one by eye can pipe it through a formatter, and paying for the
indentation in every stored byte to save them that is the wrong trade. The
quality manifest is rendered the same way for the same reason.
"""


class JsonCodec:
    """Renders a document as deterministic, RFC 8259-conformant JSON.

    Holds no state and takes no arguments, so every instance behaves identically.
    It is still a class rather than two functions because it is the implementation
    of a :class:`~typing.Protocol`, and a second representation would arrive as a
    sibling class rather than as a second pair of module-level names.
    """

    def encode(self, document: Mapping[str, object]) -> str:
        """Render a document as JSON text.

        Args:
            document: A mapping with :class:`str` keys.

        Returns:
            The JSON text, keys sorted, with no trailing newline.

        Raises:
            ValidationError: If ``document`` is not a mapping, holds a key that
                is not a :class:`str`, holds a :class:`float` anywhere, or holds
                a value JSON cannot represent.

        The document is walked before it is rendered rather than relying on
        :func:`json.dumps` to complain, because the two failures this catches are
        precisely the ones it does *not* complain about.
        """
        _check(document, path="document")
        try:
            return json.dumps(
                document,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
                separators=SEPARATORS,
            )
        except (TypeError, ValueError) as fault:
            msg = f"document cannot be rendered as JSON: {type(fault).__name__} ({fault})"
            raise ValidationError(msg) from fault

    def decode(self, text: str) -> Mapping[str, object]:
        """Read a document back from JSON text.

        Args:
            text: The JSON text.

        Returns:
            The document.

        Raises:
            ValidationError: If ``text`` is not a :class:`str`, is not valid
                JSON, does not hold an object at its top level, or holds a
                number this codec would never have written.

        The top level must be an object. Every document GLOBIN persists carries
        the two envelope keys, so an array or a bare string at the top is a file
        that was not written by this codec — and saying so here is more useful
        than a missing-key error two calls later.
        """
        try:
            document = json.loads(
                _require_text(text), parse_float=_no_float, parse_constant=_no_constant
            )
        except json.JSONDecodeError as fault:
            msg = f"document is not valid JSON: {fault}"
            raise ValidationError(msg) from fault
        if not isinstance(document, dict):
            msg = (
                f"document must be a JSON object, got {type(document).__name__}: "
                f"every GLOBIN record carries its schema and version at the top level"
            )
            raise ValidationError(msg)
        return document


def _require_text(value: object) -> str:
    """Refuse anything that is not text, and narrow what is.

    Args:
        value: What was handed to :meth:`JsonCodec.decode`. Typed as
            :class:`object` so the check is a real one — a parameter typed as
            :class:`str` would make it redundant to mypy, which is configured to
            report a guard that cannot fire. The same trade
            :mod:`globin.domain.values` makes with its comparison helpers.

    Returns:
        The text.

    Raises:
        ValidationError: If ``value`` is not a :class:`str`.

    Bytes are refused rather than decoded. Guessing an encoding is exactly the
    kind of invention ``docs/SERIALIZATION_POLICY.md`` rules out, and whoever
    opened the file knows which one it used.
    """
    if not isinstance(value, str):
        msg = (
            f"decode() needs a str, got {type(value).__name__}: decode the bytes with the "
            f"encoding they were written in before handing them here"
        )
        raise ValidationError(msg)
    return value


def _check(value: object, *, path: str) -> None:
    """Refuse anything JSON would carry back as something else.

    Args:
        value: The value or container to inspect.
        path: Where it sits in the document, for the message.

    Raises:
        ValidationError: If a mapping key is not a :class:`str`, or a
            :class:`float` appears anywhere.

    Recursive over mappings and sequences, because a float six levels down is
    still a float. :class:`str` and :class:`bytes` are excluded from the sequence
    case explicitly: both are sequences, and walking a string character by
    character would recurse until the characters ran out.

    :class:`bool` is not refused. It is a JSON literal that reads back as itself,
    which is the only property this function is protecting — unlike
    :mod:`globin.domain.values`, which refuses it because a flag is not a
    magnitude.
    """
    if isinstance(value, float):
        msg = (
            f"{path} holds the float {value!r}: GLOBIN writes exact magnitudes as text "
            f"(globin.domain.serialization.encode_decimal), because a float read back "
            f"is not always the number written"
        )
        raise ValidationError(msg)
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                msg = (
                    f"{path} holds the key {key!r} of type {type(key).__name__}: JSON "
                    f"would render it as a string and read it back as one, so the "
                    f"document would not survive the round trip"
                )
                raise ValidationError(msg)
            _check(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, item in enumerate(value):
            _check(item, path=f"{path}[{index}]")


def _no_float(text: str) -> float:
    """Refuse a JSON number written with a decimal point or an exponent.

    Args:
        text: The literal as it appeared.

    Returns:
        Never. The annotation is :class:`float` because that is the type
        :func:`json.loads` expects this hook to produce, and mypy checks the
        signature against it.

    Raises:
        ValidationError: Always.

    An exact magnitude is stored as text, so a JSON number with a fractional part
    is either a document this codec did not write or a caller who bypassed
    :func:`globin.domain.serialization.encode_decimal`. Both are worth stopping.

    Integers are unaffected: :func:`json.loads` routes those through
    ``parse_int``, which is left at its default. A version, a count and an epoch
    millisecond are all integers, and all read back exactly.
    """
    msg = (
        f"document holds the JSON number {text}: a fractional number is stored as text "
        f"in GLOBIN, because a float read back is not always the number written"
    )
    raise ValidationError(msg)


def _no_constant(text: str) -> float:
    """Refuse ``NaN``, ``Infinity`` and ``-Infinity``.

    Args:
        text: The bare word as it appeared.

    Returns:
        Never, for the reason :func:`_no_float` gives.

    Raises:
        ValidationError: Always.

    :mod:`json` accepts all three by default and RFC 8259 defines none of them.
    A file containing one is readable by Python and by little else, which is the
    opposite of what a persisted record is for.
    """
    msg = (
        f"document holds {text}, which is not JSON: RFC 8259 has no literal for it, so "
        f"the file would be readable by Python and by almost nothing else"
    )
    raise ValidationError(msg)
