"""Compatibility alias for feature-owned knowledge grounding."""

import sys

from northstar_api.modules.knowledge import grounding as _implementation

sys.modules[__name__] = _implementation
