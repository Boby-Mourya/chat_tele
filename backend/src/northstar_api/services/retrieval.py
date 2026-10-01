"""Compatibility alias for feature-owned knowledge retrieval."""

import sys

from northstar_api.modules.knowledge import retrieval as _implementation

sys.modules[__name__] = _implementation
