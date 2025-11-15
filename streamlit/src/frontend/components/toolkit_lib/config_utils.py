from __future__ import annotations

import os
from typing import Optional, Tuple

from ..cctp_bridge import guess_default_lending_pool_abi_path


def resolve_lending_pool_abi_path(env_value: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve the LendingPool ABI path, mirroring the MCP Tools page logic.

    Args:
        env_value: Value provided via `LENDING_POOL_ABI_PATH`; may be None.

    Returns:
        Tuple of (resolved_path, source_label, invalid_path). The third element is non-None when the provided path
        does not exist on disk.
    """

    if env_value:
        candidate = os.path.expanduser(env_value)
        if os.path.exists(candidate):
            return candidate, "env", None
        return None, None, candidate
    guessed = guess_default_lending_pool_abi_path()
    if guessed:
        return guessed, "foundry artifact", None
    return None, None, None



