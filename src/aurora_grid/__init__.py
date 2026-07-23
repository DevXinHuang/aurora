"""Aurora experiment runners.

The repository also contains the established sub-Neptune grid package under
``roadrunner_egp/aurora_subneptune_grid/src``.  Extend the package search path
so the portable Tint module and the existing grid modules can be imported in
the same Python process when both source roots are on ``PYTHONPATH``.
"""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
