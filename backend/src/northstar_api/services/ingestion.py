"""Compatibility alias for feature-owned knowledge ingestion."""

import sys

from northstar_api.modules.knowledge import ingestion as _implementation

sys.modules[__name__] = _implementation
