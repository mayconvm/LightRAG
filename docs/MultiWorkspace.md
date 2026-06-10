# Multi-Workspace Support

LightRAG supports **multiple isolated workspaces** within a single server instance. Each workspace has its own storage backends, document index, knowledge graph, and pipeline state — all served from one process.

> **Comparison with Multi-Site Deployment** (`MultiSiteDeployment.md`):  
> Multi-site runs separate backend *processes* (containers) behind a reverse proxy.  
> Multi-workspace runs a single process that serves many logically isolated data
> partitions simultaneously. Choose multi-site when you need process-level
> isolation or different LLM/storage backends per tenant; choose multi-workspace
> when a shared backend config suffices and you want zero extra operational
> overhead per tenant.

---

## How it works

When the `LIGHTRAG-WORKSPACE` HTTP header is present on a request, the backend
extracts it and resolves a dedicated `LightRAG` instance for that workspace.
Instances are created lazily on first access and cached for subsequent requests.
Requests **without** the header use the default workspace (empty string),
preserving backward compatibility.

Each `LightRAG` instance is configured with the same LLM, embedding, and storage
settings, but receives a different `workspace` parameter. The storage backends
use this parameter for isolation:

| Backend | Isolation mechanism |
|---|---|
| **JSON** / **NetworkX** / **NanoVectorDB** / **Faiss** | Subdirectory `{working_dir}/{workspace}/` |
| **PostgreSQL** | `workspace` column in every table |
| **MongoDB** | Collection prefix `{workspace}_{namespace}` |
| **Redis** | Key prefix `{workspace}_{namespace}:*` |
| **Qdrant** | Payload field `workspace_id` filter |
| **Milvus** | Collection prefix `{workspace}_{namespace}` |
| **OpenSearch** | Index name prefix `{workspace}_{namespace}` |
| **Neo4j** / **Memgraph** | Cypher node label `` `{workspace}` `` |

---

## API Reference

### HTTP Header

All workspace-aware endpoints accept the `LIGHTRAG-WORKSPACE` header:

```
LIGHTRAG-WORKSPACE: my_workspace
```

The value must match `[a-zA-Z0-9_]+`; invalid characters are replaced with `_`.

### Workspace Management Endpoints

All endpoints require authentication (API key or JWT token).

#### `GET /workspaces`

List all active (cached) workspaces.

```bash
curl http://localhost:9621/workspaces -H "X-API-Key: your-key"
```

Response:
```json
{
  "workspaces": ["client_a", "client_b"],
  "default_workspace": "",
  "count": 2
}
```

#### `POST /workspaces/{name}`

Ensure a workspace exists (creates the `LightRAG` instance lazily on first use).

```bash
curl -X POST http://localhost:9621/workspaces/client_a \
  -H "X-API-Key: your-key"
```

Response `201`:
```json
{ "workspace": "client_a", "status": "ready" }
```

Invalid names (empty after sanitisation) return `400`.

#### `DELETE /workspaces/{name}`

Drop a workspace and finalise all its storage backends. Returns `404` if the
workspace does not exist.

```bash
curl -X DELETE http://localhost:9621/workspaces/client_a \
  -H "X-API-Key: your-key"
```

Response:
```json
{ "workspace": "client_a", "status": "deleted" }
```

**Cascade**: the underlying storage backends delete only the data belonging to
that workspace (see isolation table above). Input files under
`inputs/{workspace}/` are **not** automatically removed.

---

## Usage Examples

### Insert data into a workspace

```bash
curl -X POST http://localhost:9621/documents/text \
  -H "LIGHTRAG-WORKSPACE: client_a" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"text": "Confidential document for client A", "file_source": "doc_a.txt"}'
```

### Query a workspace

```bash
curl http://localhost:9621/query \
  -H "LIGHTRAG-WORKSPACE: client_a" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"query": "What does this document say?"}'
```

### Different workspaces, same server

```bash
# Insert into workspace "alpha"
curl -X POST ... -H "LIGHTRAG-WORKSPACE: alpha" -d '{"text": "Alpha data"}'
# Insert into workspace "beta"
curl -X POST ... -H "LIGHTRAG-WORKSPACE: beta"  -d '{"text": "Beta data"}'
# Query alpha — only alpha's documents are visible
curl ... -H "LIGHTRAG-WORKSPACE: alpha"   -d '{"query": "summary"}'
# Query beta  — only beta's documents are visible
curl ... -H "LIGHTRAG-WORKSPACE: beta"    -d '{"query": "summary"}'
```

### Default workspace (no header)

Requests without the header behave exactly as before — they use the workspace
configured via the `WORKSPACE` environment variable (or empty string, which is
the global namespace).

```bash
curl http://localhost:9621/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"query": "default workspace query"}'
```

### Via the WebUI

The WebUI header includes a workspace selector dropdown (next to the version
display). You can:

- **Switch** between existing workspaces
- **Create** a new workspace (opens a dialog)
- **Delete** a workspace (× button next to each workspace name)

The selected workspace is sent as the `LIGHTRAG-WORKSPACE` header in every API
call made by the WebUI.

---

## Configuration

The default workspace for the server is set via the `WORKSPACE` environment
variable (or the `--workspace` CLI argument):

```bash
lightrag-server --workspace my_default
```

Individual storage backends also accept backend-specific workspace overrides
(e.g. `NEO4J_WORKSPACE`, `MONGODB_WORKSPACE`). These are site-administrator
overrides and **not** intended for per-request routing — they force every
`LightRAG` instance in that process to use the same backend workspace.

---

## Behaviour & Guarantees

- **Lazy initialisation**: the first request to a workspace creates its
  `LightRAG` instance and initialises all storage backends. Subsequent requests
  reuse the cached instance.
- **No cross-talk**: data inserted into workspace A is invisible to queries
  against workspace B (enforced at the storage level).
- **Backward compatible**: existing clients that do not send the
  `LIGHTRAG-WORKSPACE` header continue to work unchanged.
- **Server shutdown**: all cached workspace instances are finalised on graceful
  shutdown (`SIGTERM` / `SIGINT`).

---

## Limitations

- **Per-backend workspace env vars** (`NEO4J_WORKSPACE` etc.) override the
  per-request workspace at the storage level. When set, all workspaces share the
  same backend namespace — only the process-level (in-memory) pipeline status
  remains isolated.
- **Input files** are **not** cleaned up when a workspace is deleted via the
  API. The directory `inputs/{workspace}/` must be removed manually or by an
  external cleanup process.
- **Ollama-compatible API** endpoints use the default workspace rag instance
  (they are not workspace-routed).
