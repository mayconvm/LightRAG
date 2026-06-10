"""Shared test utilities for multi-workspace tests.

Provides mock objects that stand in for ``WorkspaceManager`` and
``LightRAG`` so route-factory functions can be exercised without a
real storage backend.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock


def make_mock_rag(**overrides: Any) -> SimpleNamespace:
    """Build a minimal LightRAG stand-in with async methods stubbed.

    The returned object exposes enough attributes to keep the
    workspace-aware route handlers working:

    - ``workspace`` (str)
    - ``get_graph_labels``, ``aquery_llm``, ``ainsert``, etc. (AsyncMock)
    """
    defaults = {
        "workspace": "",
        "get_graph_labels": AsyncMock(return_value=[]),
        "aquery_llm": AsyncMock(
            return_value={
                "llm_response": {"content": "mock answer"},
                "data": {"references": [], "chunks": []},
            }
        ),
        "aquery_data": AsyncMock(
            return_value={
                "status": "success",
                "message": "mock data",
                "data": {},
                "metadata": {},
            }
        ),
        "ainsert": AsyncMock(return_value="mock-track-id"),
        "ainsert_data": AsyncMock(return_value=None),
        "adelete_by_entity": AsyncMock(
            return_value=SimpleNamespace(status="success", message="deleted", doc_id="")
        ),
        "adelete_by_relation": AsyncMock(
            return_value=SimpleNamespace(status="success", message="deleted", doc_id="")
        ),
        "adelete_by_doc_id": AsyncMock(
            return_value=SimpleNamespace(
                status="success", message="deleted", doc_id="doc-1"
            )
        ),
        "aclear_documents": AsyncMock(
            return_value=SimpleNamespace(status="success", message="cleared", doc_id="")
        ),
        "aedit_entity": AsyncMock(
            return_value={
                "entity_name": "Alice",
                "description": "updated",
                "operation_summary": {
                    "merged": False,
                    "merge_status": "not_attempted",
                    "merge_error": None,
                    "operation_status": "success",
                    "target_entity": None,
                    "final_entity": "Alice",
                    "renamed": False,
                },
            }
        ),
        "aedit_relation": AsyncMock(return_value={"description": "updated"}),
        "acreate_entity": AsyncMock(return_value={"entity_name": "Alice"}),
        "acreate_relation": AsyncMock(return_value={"src_id": "a", "tgt_id": "b"}),
        "amerge_entities": AsyncMock(return_value={"merged_entity": "Alice"}),
        "initialize_storages": AsyncMock(),
        "check_and_migrate_data": AsyncMock(),
        "finalize_storages": AsyncMock(),
        "chunk_entity_relation_graph": SimpleNamespace(
            get_graph_labels=AsyncMock(return_value=[]),
            get_popular_labels=AsyncMock(return_value=[]),
            search_labels=AsyncMock(return_value=[]),
            has_node=AsyncMock(return_value=False),
            get_knowledge_graph=AsyncMock(
                return_value=SimpleNamespace(nodes=[], edges=[])
            ),
        ),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class MockWorkspaceManager:
    """In-memory WorkspaceManager stand-in that returns mock LightRAG instances.

    Usage::

        wm = MockWorkspaceManager()
        wm.set_default_rag(my_rag)         # optional: inject a specific mock
        rag = await wm.get_or_create("ws")  # returns a mock
    """

    def __init__(self) -> None:
        self._instances: dict[str, SimpleNamespace] = {}

    def set_default_rag(self, rag: Any) -> None:
        """Pre-register the instance for the global (empty) workspace."""
        self._instances[""] = rag

    async def get_or_create(self, workspace: str) -> Any:
        ws = workspace or ""
        if ws not in self._instances:
            self._instances[ws] = make_mock_rag(workspace=ws)
        return self._instances[ws]

    async def get(self, workspace: str) -> Optional[Any]:
        return self._instances.get(workspace or "")

    def get_cached_or_none(self, workspace: str) -> Optional[Any]:
        return self._instances.get(workspace or "")

    async def drop(self, workspace: str) -> bool:
        return self._instances.pop(workspace or "", None) is not None

    async def drop_all(self) -> list[str]:
        keys = list(self._instances.keys())
        self._instances.clear()
        return keys

    def list_workspaces(self) -> list[str]:
        return list(self._instances.keys())

    def has(self, workspace: str) -> bool:
        return (workspace or "") in self._instances

    def __len__(self) -> int:
        return len(self._instances)
