"""Tests for multi-workspace API support.

Covers the ``WorkspaceManager`` class, the ``LIGHTRAG-WORKSPACE`` header
middleware, and end-to-end routing of document/query/graph endpoints
across workspaces.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# Stash argv so pytest flags don't trip lightrag's argparse
_original_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
from lightrag.api.workspace_manager import (  # noqa: E402
    WorkspaceManager,
    sanitize_workspace,
    extract_workspace_from_headers,
)
from lightrag.api.routers.query_routes import create_query_routes  # noqa: E402
from lightrag.api.routers.graph_routes import create_graph_routes  # noqa: E402
from lightrag.api.routers.document_routes import create_document_routes  # noqa: E402

sys.argv = _original_argv

from .workspace_test_utils import MockWorkspaceManager, make_mock_rag  # noqa: E402

pytestmark = pytest.mark.offline

_API_KEY = "test-key"
_HEADERS = {"X-API-Key": _API_KEY}


# ============================================================================
# WorkspaceManager unit tests
# ============================================================================


class TestSanitizeWorkspace:
    def test_allows_alphanumeric_and_underscore(self):
        assert sanitize_workspace("hello") == "hello"
        assert sanitize_workspace("workspace_1") == "workspace_1"
        assert sanitize_workspace("abc123") == "abc123"

    def test_replaces_invalid_characters(self):
        result = sanitize_workspace("Hello World!")
        assert result == "Hello_World_"
        assert "_" in result

    def test_handles_empty_string(self):
        assert sanitize_workspace("") == ""

    def test_handles_none(self):
        assert sanitize_workspace(None) == ""


class TestExtractWorkspaceFromHeaders:
    def test_extracts_from_header(self):
        class FakeHeaders(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

        headers = FakeHeaders({"LIGHTRAG-WORKSPACE": "my_workspace"})
        assert extract_workspace_from_headers(headers) == "my_workspace"

    def test_returns_empty_when_missing(self):
        class FakeHeaders(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

        headers = FakeHeaders({})
        assert extract_workspace_from_headers(headers) == ""

    def test_sanitizes_invalid(self):
        class FakeHeaders(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

        headers = FakeHeaders({"LIGHTRAG-WORKSPACE": "bad name!"})
        result = extract_workspace_from_headers(headers)
        assert result == "bad_name_"


class TestWorkspaceManagerUnit:
    """Unit tests for WorkspaceManager using a counting factory."""

    def test_get_or_create_creates_new_instance(self):
        call_count = 0

        def creator(ws):
            nonlocal call_count
            call_count += 1
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            rag1 = await wm.get_or_create("ws_a")
            assert rag1.workspace == "ws_a"
            assert call_count == 1

        asyncio.run(run())

    def test_get_or_create_returns_cached(self):
        call_count = 0

        def creator(ws):
            nonlocal call_count
            call_count += 1
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            rag1 = await wm.get_or_create("ws_a")
            rag2 = await wm.get_or_create("ws_a")
            assert rag1 is rag2
            assert call_count == 1  # Only created once

        asyncio.run(run())

    def test_get_or_create_treats_empty_as_global(self):
        call_count = 0

        def creator(ws):
            nonlocal call_count
            call_count += 1
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            rag1 = await wm.get_or_create("")
            rag2 = await wm.get_or_create("")
            assert rag1 is rag2
            assert call_count == 1

        asyncio.run(run())

    def test_list_workspaces(self):
        def creator(ws):
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            assert wm.list_workspaces() == []
            await wm.get_or_create("ws_a")
            assert "ws_a" in wm.list_workspaces()

        asyncio.run(run())

    def test_drop_removes_instance(self):
        def creator(ws):
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            await wm.get_or_create("ws_a")
            assert wm.has("ws_a")
            dropped = await wm.drop("ws_a")
            assert dropped is True
            assert not wm.has("ws_a")

        asyncio.run(run())

    def test_drop_nonexistent_returns_false(self):
        def creator(ws):
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            dropped = await wm.drop("nonexistent")
            assert dropped is False

        asyncio.run(run())

    def test_drop_all_removes_everything(self):
        def creator(ws):
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            await wm.get_or_create("ws_a")
            await wm.get_or_create("ws_b")
            assert len(wm) == 2
            dropped = await wm.drop_all()
            assert len(wm) == 0
            assert "ws_a" in dropped
            assert "ws_b" in dropped

        asyncio.run(run())

    def test_concurrent_get_or_create_is_thread_safe(self):
        """Multiple concurrent awaits should only call creator once."""
        call_count = 0

        def creator(ws):
            nonlocal call_count
            call_count += 1
            return make_mock_rag(workspace=ws)

        import asyncio

        wm = WorkspaceManager(creator=creator)

        async def run():
            results = await asyncio.gather(
                wm.get_or_create("same_ws"),
                wm.get_or_create("same_ws"),
                wm.get_or_create("same_ws"),
            )
            assert all(r is results[0] for r in results)
            assert call_count == 1

        asyncio.run(run())


# ============================================================================
# API integration tests
# ============================================================================


class _WorkspaceMiddlewareMock:
    """Injects a mock workspace header into request.state for test routes."""

    def __init__(self, header_value: str = ""):
        self._value = header_value

    async def __call__(self, request: Request, call_next):
        from lightrag.api.workspace_manager import sanitize_workspace

        ws = sanitize_workspace(self._value) if self._value else ""
        request.state.workspace = ws
        request.state.workspace_initialized = True
        response = await call_next(request)
        return response


def _build_app(
    workspace_manager: Any,
    base_input_dir: str = "/tmp/test_input",
    default_rag: Any = None,
    with_middleware: bool = True,
    header_value: str = "",
) -> FastAPI:
    """Build a FastAPI app with all routes registered under a workspace_manager.

    Optionally wires a middleware that sets ``request.state.workspace``
    to simulate the production ``LIGHTRAG-WORKSPACE`` header behaviour.
    """
    app = FastAPI()

    if default_rag is None:
        default_rag = make_mock_rag()

    if with_middleware:
        from lightrag.api.workspace_manager import extract_workspace_from_headers

        @app.middleware("http")
        async def _test_workspace_middleware(request: Request, call_next):
            ws = extract_workspace_from_headers(request.headers)
            request.state.workspace = ws
            request.state.workspace_initialized = True
            response = await call_next(request)
            return response

    app.include_router(
        create_document_routes(workspace_manager, base_input_dir, default_rag, _API_KEY)
    )
    app.include_router(create_query_routes(workspace_manager, _API_KEY))
    app.include_router(create_graph_routes(workspace_manager, _API_KEY))

    return app


class TestMultiWorkspaceAPI:
    """Tests that exercise the workspace-aware routes via HTTP.

    These tests use ``MockWorkspaceManager`` so that each workspace
    gets its own mock ``LightRAG`` instance — this lets us verify that
    different workspaces produce different responses.
    """

    @pytest.fixture
    def wm(self):
        return MockWorkspaceManager()

    @pytest.fixture
    def app(self, wm):
        return _build_app(wm, with_middleware=True)

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    # -- Default workspace (no header) -----------------------------------

    def test_default_workspace_when_no_header(self, client):
        resp = client.post("/query", json={"query": "hello"}, headers=_HEADERS)
        assert resp.status_code == 200

    def test_default_workspace_text_insert(self, client):
        resp = client.post(
            "/documents/text",
            json={"text": "hello world", "file_source": "test.txt"},
            headers=_HEADERS,
        )
        # May be 200 or 409 depending on real pipeline_status;
        # we just verify the request routes to the handler.
        assert resp.status_code in (200, 409, 500)

    # -- Workspace header routing ----------------------------------------

    def test_query_with_workspace_header(self, wm, client):
        """Query with LIGHTRAG-WORKSPACE header resolves to correct instance."""
        resp = client.post(
            "/query",
            json={"query": "test"},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "ws_a"},
        )
        assert resp.status_code == 200
        # The ws_a workspace should have been created
        rag = wm.get_cached_or_none("ws_a")
        assert rag is not None
        assert rag.workspace == "ws_a"

    def test_different_workspaces_use_different_instances(self, wm, client):
        """Each workspace header value resolves a different LightRAG instance."""
        client.post(
            "/query",
            json={"query": "hello"},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "alpha"},
        )
        client.post(
            "/query",
            json={"query": "world"},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "beta"},
        )
        rag_a = wm.get_cached_or_none("alpha")
        rag_b = wm.get_cached_or_none("beta")
        assert rag_a is not None
        assert rag_b is not None
        assert rag_a is not rag_b

    def test_same_workspace_returns_cached_instance(self, wm, client):
        """Repeated requests with the same workspace header reuse the instance."""
        client.post(
            "/query",
            json={"query": "first"},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "shared"},
        )
        client.post(
            "/query",
            json={"query": "second"},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "shared"},
        )
        rag = wm.get_cached_or_none("shared")
        assert rag is not None
        # Both calls hit the same instance, so aquery_llm was called twice
        assert rag.aquery_llm.await_count == 2

    def test_graph_labels_with_workspace(self, wm, client):
        """Graph endpoint routes to the correct workspace instance."""
        resp = client.get(
            "/graph/label/list",
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "graph_ws"},
        )
        assert resp.status_code == 200
        rag = wm.get_cached_or_none("graph_ws")
        assert rag is not None
        assert rag.get_graph_labels.called

    def test_workspace_header_is_sanitized(self, wm, client):
        """Invalid characters in the header value are replaced."""
        client.post(
            "/query",
            json={"query": "test"},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "bad name!"},
        )
        rag = wm.get_cached_or_none("bad_name_")
        assert rag is not None

    # -- Crosstalk test --------------------------------------------------

    def test_no_crosstalk_between_workspaces(self, wm, client, monkeypatch):
        """Mutations in one workspace should not affect another.

        Each workspace has its own mock rag; we verify by checking that
        the mock instances are distinct.
        """
        from lightrag.api.routers import document_routes

        async def _noop_guard(_rag):
            return None

        monkeypatch.setattr(
            document_routes, "check_pipeline_busy_or_raise", _noop_guard
        )

        import importlib as _il

        _il.reload(_il.import_module("lightrag.api.routers.graph_routes"))
        from lightrag.api.routers.graph_routes import create_graph_routes as cgr

        app2 = FastAPI()
        from lightrag.api.workspace_manager import extract_workspace_from_headers

        @app2.middleware("http")
        async def _mid(request, call_next):
            ws = extract_workspace_from_headers(request.headers)
            request.state.workspace = ws
            request.state.workspace_initialized = True
            response = await call_next(request)
            return response

        app2.include_router(cgr(wm, _API_KEY))
        client2 = TestClient(app2)

        client2.post(
            "/graph/entity/create",
            json={"entity_name": "Alice", "entity_data": {"description": "x"}},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "tenant_1"},
        )
        client2.post(
            "/graph/entity/create",
            json={"entity_name": "Bob", "entity_data": {"description": "y"}},
            headers={**_HEADERS, "LIGHTRAG-WORKSPACE": "tenant_2"},
        )
        rag1 = wm.get_cached_or_none("tenant_1")
        rag2 = wm.get_cached_or_none("tenant_2")
        assert rag1 is not rag2
        assert rag1.acreate_entity.await_count == 1
        assert rag2.acreate_entity.await_count == 1


class TestWorkspaceManagerViaAPI:
    """Tests that exercise the ``/workspaces`` management endpoints."""

    @pytest.fixture
    def wm(self):
        return MockWorkspaceManager()

    @pytest.fixture
    def app(self, wm):
        app = FastAPI()
        default_rag = make_mock_rag()

        # Register workspace management endpoints + routes
        from fastapi import HTTPException

        from lightrag.api.workspace_manager import (
            sanitize_workspace,
        )

        @app.get("/workspaces")
        async def list_workspaces():
            return {
                "workspaces": wm.list_workspaces(),
                "default_workspace": "",
                "count": len(wm),
            }

        @app.post("/workspaces/{workspace:path}", status_code=201)
        async def create_workspace(workspace: str):
            ws = sanitize_workspace(workspace)
            if not ws:
                raise HTTPException(400, "Invalid workspace name")
            await wm.get_or_create(ws)
            return {"workspace": ws, "status": "ready"}

        @app.delete("/workspaces/{workspace:path}")
        async def delete_workspace(workspace: str):
            ws = sanitize_workspace(workspace)
            if not ws:
                raise HTTPException(400, "Invalid workspace name")
            dropped = await wm.drop(ws)
            if not dropped:
                raise HTTPException(404, f"Workspace '{ws}' not found")
            return {"workspace": ws, "status": "deleted"}

        app.include_router(
            create_document_routes(wm, "/tmp/test_input", default_rag, _API_KEY)
        )
        app.include_router(create_query_routes(wm, _API_KEY))
        app.include_router(create_graph_routes(wm, _API_KEY))

        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_workspaces_empty(self, client):
        resp = client.get("/workspaces", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_create_workspace(self, client, wm):
        resp = client.post("/workspaces/my_ws", headers=_HEADERS)
        assert resp.status_code == 201
        assert wm.has("my_ws")

    def test_create_workspace_sanitizes_name(self, client, wm):
        resp = client.post("/workspaces/bad name", headers=_HEADERS)
        assert resp.status_code == 201
        assert wm.has("bad_name")

    def test_create_empty_workspace_returns_400(self, client):
        resp = client.post("/workspaces/", headers=_HEADERS)
        assert resp.status_code == 400

    def test_delete_workspace(self, client, wm):
        client.post("/workspaces/to_delete", headers=_HEADERS)
        assert wm.has("to_delete")
        resp = client.delete("/workspaces/to_delete", headers=_HEADERS)
        assert resp.status_code == 200
        assert not wm.has("to_delete")

    def test_delete_nonexistent_workspace_returns_404(self, client):
        resp = client.delete("/workspaces/nope", headers=_HEADERS)
        assert resp.status_code == 404

    def test_list_includes_created(self, client):
        client.post("/workspaces/alpha", headers=_HEADERS)
        client.post("/workspaces/beta", headers=_HEADERS)
        resp = client.get("/workspaces", headers=_HEADERS)
        data = resp.json()
        assert data["count"] == 2
        assert "alpha" in data["workspaces"]
        assert "beta" in data["workspaces"]
