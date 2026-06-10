"""
Workspace Manager for LightRAG Multi-Workspace Support.

Manages per-workspace LightRAG instances with lazy initialization,
enabling a single API server to serve multiple isolated workspaces.
"""

import asyncio
import re
from typing import Callable, Optional

from lightrag import LightRAG
from lightrag.utils import logger


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def sanitize_workspace(workspace: str) -> str:
    """Sanitize workspace name: only alphanumeric and underscores allowed."""
    if not workspace:
        return ""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", workspace)
    if sanitized != workspace:
        logger.warning(
            "Workspace '%s' contains invalid characters. Sanitized to '%s'.",
            workspace,
            sanitized,
        )
    return sanitized


def extract_workspace_from_headers(headers) -> str:
    """Extract and sanitize workspace from a dict-like headers object.

    Looks for the ``LIGHTRAG-WORKSPACE`` header.
    Returns the empty string (global workspace) when the header is absent
    or blank.
    """
    raw = headers.get("LIGHTRAG-WORKSPACE", "").strip()
    return sanitize_workspace(raw)


# ---------------------------------------------------------------------------
# WorkspaceManager
# ---------------------------------------------------------------------------


class WorkspaceManager:
    """Manages a pool of per-workspace :class:`LightRAG` instances.

    Instances are created lazily on first access and cached until
    explicitly dropped.  The creator callable receives the workspace
    string and must return a fully configured (but **not** yet
    initialized) ``LightRAG``.

    Thread-safe for async use via :class:`asyncio.Lock`.
    """

    def __init__(
        self,
        creator: Callable[[str], LightRAG],
    ) -> None:
        self._creator = creator
        self._instances: dict[str, LightRAG] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_create(self, workspace: str) -> LightRAG:
        """Return the ``LightRAG`` instance for *workspace*.

        Creates and initialises a new instance on first access.
        The empty string is treated as the **global** workspace.
        """
        workspace = workspace or ""

        if workspace in self._instances:
            return self._instances[workspace]

        async with self._lock:
            # Double-check after acquiring the lock
            if workspace in self._instances:
                return self._instances[workspace]

            logger.info("Creating LightRAG instance for workspace='%s'", workspace)
            rag = self._creator(workspace)
            await rag.initialize_storages()
            self._instances[workspace] = rag
            return rag

    async def get(self, workspace: str) -> Optional[LightRAG]:
        """Return the cached instance for *workspace*, or ``None``."""
        return self._instances.get(workspace or "")

    def get_cached_or_none(self, workspace: str) -> Optional[LightRAG]:
        """Non-async variant — returns ``None`` if the instance was not yet
        created (no I/O).  Useful in synchronous code paths such as
        startup splash."""
        return self._instances.get(workspace or "")

    async def drop(self, workspace: str) -> bool:
        """Finalise and remove the instance for *workspace*.

        Returns ``True`` if the workspace existed, ``False`` otherwise.
        """
        workspace = workspace or ""

        async with self._lock:
            rag = self._instances.pop(workspace, None)
        if rag is None:
            return False

        logger.info("Dropping LightRAG instance for workspace='%s'", workspace)
        await rag.finalize_storages()
        return True

    async def drop_all(self) -> list[str]:
        """Finalise and remove **all** cached instances.

        Returns the list of workspace names that were dropped.
        """
        async with self._lock:
            keys = list(self._instances.keys())
            instances = [self._instances.pop(k) for k in keys]
        for ws, rag in zip(keys, instances):
            logger.info("Dropping LightRAG instance for workspace='%s'", ws)
            await rag.finalize_storages()
        return keys

    def list_workspaces(self) -> list[str]:
        """Return the list of cached (active) workspace names."""
        return list(self._instances.keys())

    def has(self, workspace: str) -> bool:
        """Return ``True`` if *workspace* is already cached."""
        return (workspace or "") in self._instances

    def __len__(self) -> int:
        return len(self._instances)
