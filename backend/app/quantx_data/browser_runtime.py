"""Browser launcher for the self-contained QuantX source adapters."""
from __future__ import annotations

import sys
from typing import Any


def launch_chromium(playwright: Any, **kwargs: Any) -> Any:
    """Launch the installed Edge channel on Windows, bundled Chromium elsewhere.

    The Windows development environment already provides Microsoft Edge. Using
    that channel keeps a fresh checkout operational without a separate 190 MB
    Playwright browser download.
    """

    if sys.platform == "win32":
        kwargs.setdefault("channel", "msedge")
    return playwright.chromium.launch(**kwargs)
