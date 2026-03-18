"""CLI introspection engine — discovers tool capabilities from help, man, and completions.

This subpackage contains parsers for three introspection sources:

- :mod:`~mclip.introspect.help` — ``--help`` / ``-h`` output parsing
- :mod:`~mclip.introspect.man` — ``man`` page parsing
- :mod:`~mclip.introspect.completions` — Shell completion script parsing

The :func:`introspect_cli` function orchestrates all three and merges results.
"""

from mclip.introspect.engine import introspect_cli

__all__ = ["introspect_cli"]
