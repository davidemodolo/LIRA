"""L.I.R.A. - LIRA Is Recursive Accounting.

An AI-native, agentic personal finance and investment tracker.
"""

__version__ = "0.1.0"
__version_info__ = tuple(int(x) for x in __version__.split("."))

from lira.core.agent import Agent
from lira.core.exceptions import LiraError

__all__ = [
    "Agent",
    "LiraError",
    "__version__",
    "__version_info__",
]
