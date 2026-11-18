
"""Browser UI and managed-state demo controls for an Agent Bricks agent project."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from databricks_agentkit import workspace_client
from databricks_agentkit.runtime.model_services import list_ai_gateway_model_services
from databricks_agentkit.runtime.store import runtime_store_is_persistent_environment
from runtime.document_parser import (
    extract_document_text,
    extract_locations,
)

_UI_ROOT = Path(__file__).resolve().parent.parent / "ui"
_INSTANCE_ID = uuid.uuid4().hex[:12]
_AGENTS_API = "/api/2.0/agents"

_MESSAGE_ROLES = {
    "ai",
    "assistant",
    "developer",
    "function",
    "human",
    "human_decision",
    "system",
    "tool",
    "user",
}


class MemoryEntryRequest(BaseModel):
    path: str = Field(min_length=1, pattern=r"^/")
    content: str = Field(min_length=1)
    description: str | None = None


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    actor: str | None = None


class SessionItemsRequest(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)


_USER_HEADERS = ("x-forwarded-email", "x-forwarded-user")


def _memory_store() -> str:
    from databricks_agentkit.runtime.tool_manifest import resolve_memory_store
    return (resolve_memory_store() or "").strip().strip("/")


def _session_store() -> str:
    from databricks_agentkit.runtime.tool_manifest import resolve_session_store
    return (resolve_session_store() or "").strip()


def _request_actor(request: Request) -> str:
    for header in _USER_HEADERS:
        if value := request.headers.get(header):
            return value
    return "agent"


def _request_session_id(request: Request) -> str:
    session_id = request.query_params.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    return str(session_id)


def _is_deployed() -> bool:
    app_url = os.getenv("DATABRICKS_APP_URL", "")
    is_local = app_url.startswith(("http://localhost", "http://127.0.0.1"))
    return bool(os.getenv("DATABRICKS_APP_NAME")) and not is_local


_TRACING_DESTINATION_VARS = ("MLFLOW_TRACKING_URI", "MLFLOW_TRACING_DESTINATION")


@lru_cache(maxsize=1)
def _workspace_host() -> str:
    try:
        host = workspace_client().config.host or ""
    except Exception:
        host = os.getenv("DATABRICKS_HOST", "")
    return host.rstrip("/")


def _tracing() -> dict:
    destination = ""
    for var in _TRACING_DESTINATION_VARS:
        if value := os.getenv(var):
            destination = value
            break

    experiment_id = os.getenv("MLFLOW_EXPERIMENT_ID", "").strip()
    experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "").strip()
    enabled = bool(destination) and bool(experiment_id or experiment_name)
    url: str | None = None

    if enabled:
        if destination.startswith(("http://", "https://")) and "databricks" not in destination:
            base = destination.rstrip("/")
            url = f"{base}/#/experiments/{experiment_id}" if experiment_id else base
        else:
            host = _workspace_host()
            if host:
                url = (
                    f"{host}/ml/experiments/{experiment_id}"
                    if experiment_id
                    else f"{host}/ml/experiments"
                )

    return {"enabled": enabled, "experiment_id": experiment_id or None, "url": url}


def _default_model() -> str:
    from agent.agent import MODEL
    return MODEL


def _rank_models(default: str, names: list[str]) -> list[str]:
    ordered = [default, *sorted(n for n in names if n != default)]
    seen: set[str] = set()
    return [n for n in ordered if not (n in seen or seen.add(n))]


def _discover_chat_models() -> list[str]:
    default = _default_model()
    try:
        names = list_ai_gateway_model_services(workspace_client())
    except Exception:
        names = []
    return _rank_models(default, names)


_FRAMEWORK = "langgraph"

_TOOL_LABELS = {
    "mcp": "MCP service",
    "uc_function": "UC function",
    "genie_one": "Genie One",
    "genie_agent": "Genie Agent",
    "sandbox": "Sandbox",
}

_ADD_COMMANDS = (
    {
        "kind": "mcp",
        "label": "Managed MCP service",
        "command": "agentbricks tools add mcp system.ai.web_search",
    },
    {
        "kind": "uc-function",
        "label": "Unity Catalog function",
        "command": "agentbricks tools add uc-function catalog.schema.function",
    },
    {"kind": "genie-one", "label": "Genie One", "command": "agentbricks tools add genie-one"},
    {
        "kind": "genie-agent",
        "label": "Genie Agent",
        "command": "agentbricks tools add genie-agent SPACE_ID",
    },
    {
        "kind": "sandbox",
        "label": "Sandbox",
        "command": "agentbricks tools add sandbox",
    },
    {
        "kind": "discover",
        "label": "Find more MCP services",
        "command": "agentbricks tools list --kind mcp",
    },
)


def _connected_tools() -> list[dict[str, str]]:
    from databricks_agentkit.runtime.tool_manifest import load_tools

    connected = []
    for tool in load_tools(expected_framework=_FRAMEWORK):
        if tool.kind == "sandbox":
            source = ", ".join(f"{scope.kind}:{scope.value}" for scope in tool.downscope)
            source = source or tool.service or ""
        else:
            source = tool.service or tool.function or tool.space_id or ""

        connected.append(
            {
                "id": tool.id,
                "kind": tool.kind,
                "label": _TOOL_LABELS.get(tool.kind, tool.kind),
                "source": source,
                "auth": tool.auth or "app",
            }
        )
    return connected


def _local_tools() -> list[dict[str, str]]:
    from agent.tools import all_tools

    local = []
    for tool in all_tools():
        lines = (getattr(tool, "description", "") or "").strip().splitlines()
        local.append({"name": tool.name, "description": lines[0].strip() if lines else ""})
    return local


def _tools() -> dict[str, Any]:
    errors: list[dict[str, str]] = []

    try:
        connected = _connected_tools()
    except Exception as exc:
        connected = []
        errors.append({"section": "connected", "message": str(exc)})

    try:
        local = _local_tools()
    except Exception as exc:
        local = []
        errors.append({"section": "local", "message": f"Could not load agent.tools: {exc}"})

    return {
        "connected": connected,
        "local": local,
        "add_commands": [dict(command) for command in _ADD_COMMANDS],
        "errors": errors,
    }


class _ManagedStateClient:
    def __init__(self) -> None:
        self._workspace = workspace_client()

    def _do(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict:
        result = self._workspace.api_client.do(method, path, query=query, body=body)
        if not isinstance(result, dict):
            raise RuntimeError(
                f"Expected an object response from {path}, got {type(result).__name__}"
            )
        return result

    def create_memory_entry(self, actor: str, request: MemoryEntryRequest, session_id: str) -> dict:
        body = {
            "actor_id": actor,
            "path": request.path,
            "content": request.content,
            "session_id": session_id,
        }
        if request.description:
            body["description"] = request.description
        return self._do("POST", f"{_AGENTS_API}/memory-stores/{_memory_store()}/entries", body=body)

    def list_memory_entries(self, actor: str, path_prefix: str | None = None) -> dict:
        query = {"actor_id": actor, "page_size": 100}
        if path_prefix:
            query["path_prefix"] = path_prefix
        return self._do(
            "GET", f"{_AGENTS_API}/memory-stores/{_memory_store()}/entries", query=query
        )

    def search_memory_entries(self, actor: str, request: MemorySearchRequest) -> dict:
        return self._do(
            "POST",
            f"{_AGENTS_API}/memory-stores/{_memory_store()}/entries:search",
            body={
                "actor_id": actor,
                "query": request.query,
                "limit": request.limit,
            },
        )

    def ensure_session(self, actor: str, session_id: str) -> dict:
        try:
            return self._do(
                "POST",
                f"{_AGENTS_API}/session-stores/{_session_store()}/sessions",
                query={"session_id": session_id},
                body={
                    "actor_id": actor,
                    "metadata": {"client": "agentbricks-demo-ui"},
                },
            )
        except Exception as exc:
            code = str(getattr(exc, "error_code", "")).upper()
            already_exists = code in {"ALREADY_EXISTS", "RESOURCE_ALREADY_EXISTS"}
            if not already_exists and "already exists" not in str(exc).lower():
                raise
            return self._do(
                "GET",
                f"{_AGENTS_API}/session-stores/{_session_store()}/sessions/{session_id}",
            )

    def get_session(self, session_id: str) -> dict:
        return self._do(
            "GET",
            f"{_AGENTS_API}/session-stores/{_session_store()}/sessions/{session_id}",
        )

    def list_sessions(self, actor: str) -> dict:
        return self._do(
            "GET",
            f"{_AGENTS_API}/session-stores/{_session_store()}/sessions",
            query={
                "filter": f"actor_id = {json.dumps(actor)}",
                "order_by": "last_activity_time desc",
                "page_size": 50,
            },
        )

    def append_session_items(self, session_id: str, items: list[dict[str, Any]]) -> dict:
        return self._do(
            "POST",
            f"{_AGENTS_API}/session-stores/{_session_store()}/sessions/{session_id}/items:append",
            body={"items": [{"data": item} for item in items]},
        )

    def list_session_items(self, session_id: str) -> dict:
        return self._do(
            "GET",
            f"{_AGENTS_API}/session-stores/{_session_store()}/sessions/{session_id}/items",
            query={"order_by": "create_time asc", "page_size": 100},
        )


@lru_cache(maxsize=1)
def _state_client() -> _ManagedStateClient:
    return _ManagedStateClient()


async def _managed_call(operation, *args):
    try:
        return await asyncio.to_thread(operation, *args)
    except HTTPException:
        raise
    except Exception as exc:
        code = getattr(exc, "error_code", None)
        detail = f"{code}: {exc}" if code else str(exc)
        raise HTTPException(status_code=502, detail=detail) from exc


def _require_memory() -> None:
    if not _memory_store():
        raise HTTPException(
            status_code=503,
            detail="No memory store configured. Run `agentbricks memory bind <store>`.",
        )


def _require_session() -> None:
    if not _session_store():
        raise HTTPException(
            status_code=503,
            detail="No session store configured. Run `agentbricks sessions bind <store>`.",
        )


async def _checkpoint_history(session_id: str, actor: str) -> dict[str, Any]:
    from databricks_agentkit.langgraph import read_history
    return await read_history(session_id, actor)


def _chat_sessions(result: dict[str, Any]) -> list[dict[str, Any]]:
    sessions = []
    for session in result.get("sessions", []):
        if not isinstance(session, dict):
            continue
        metadata = session.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("public_session_id"):
            continue
        sessions.append(session)
    return sessions


def _chat_session_items(result: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in result.get("session_items", []):
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        if not isinstance(data, dict) or data.get("event_type") or "content" not in data:
            continue
        role = str(data.get("role") or data.get("type") or "").lower()
        if role in _MESSAGE_ROLES:
            items.append(item)
    return {**result, "session_items": items}


def install_ui(app: FastAPI) -> None:
    """Mount the Agent Bricks UI and its runtime control endpoints."""

    app.mount("/ui-assets", StaticFiles(directory=_UI_ROOT), name="agentbricks-demo-ui-assets")

    @app.middleware("http")
    async def disable_ui_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/ui-assets/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_UI_ROOT / "index.html")

    @app.get("/api/ui/config", include_in_schema=False)
    async def ui_config(request: Request) -> dict:
        actor = _request_actor(request)
        memory_store = _memory_store()
        session_store = _session_store()
        default_model = _default_model()
        runtime_store_persistent = runtime_store_is_persistent_environment()
        runtime_store_mode = (
            "Runtime Store" if runtime_store_persistent else "In-process Runtime Store"
        )

        return {
            "session_id": _request_session_id(request),
            "instance_id": _INSTANCE_ID,
            "viewer": actor if actor != "agent" else "Local developer",
            "deployed": _is_deployed(),
            "models": {"default": default_model, "available": [default_model]},
            "streaming": {
                "enabled": True,
                "transport": "Server-sent events",
                "persistent": runtime_store_persistent,
                "mode": runtime_store_mode,
            },
            "background": {
                "enabled": True,
                "persistent": runtime_store_persistent,
                "mode": runtime_store_mode,
            },
            "session": {
                "durable": bool(session_store),
                "managed": bool(session_store),
                "history": True,
                "mode": "Managed Session Store" if session_store else "In-process checkpointer",
                "store": session_store or None,
                "actor": actor,
            },
            "memory": {
                "enabled": bool(memory_store),
                "store": f"memory-stores/{memory_store}" if memory_store else None,
                "actor": actor,
            },
            "tracing": _tracing(),
        }

    @app.get("/api/demo/models", include_in_schema=False)
    async def demo_models() -> dict:
        available_models = await asyncio.to_thread(_discover_chat_models)
        return {"default": _default_model(), "available": available_models}

    @app.get("/api/demo/tools", include_in_schema=False)
    async def demo_tools() -> dict:
        return await asyncio.to_thread(_tools)

    @app.post("/api/demo/memory/entries", include_in_schema=False)
    async def create_memory_entry(request: Request, payload: MemoryEntryRequest) -> dict:
        _require_memory()
        return await _managed_call(
            _state_client().create_memory_entry,
            _request_actor(request),
            payload,
            _request_session_id(request),
        )

    @app.get("/api/demo/memory/entries", include_in_schema=False)
    async def list_memory_entries(
        request: Request,
        path_prefix: str | None = Query(default=None),
        actor: str | None = Query(default=None),
    ) -> dict:
        _require_memory()
        return await _managed_call(
            _state_client().list_memory_entries,
            actor or _request_actor(request),
            path_prefix,
        )

    @app.post("/api/demo/memory/search", include_in_schema=False)
    async def search_memory_entries(request: Request, payload: MemorySearchRequest) -> dict:
        _require_memory()
        return await _managed_call(
            _state_client().search_memory_entries,
            payload.actor or _request_actor(request),
            payload,
        )

    @app.post("/api/demo/sessions", include_in_schema=False)
    async def ensure_session(request: Request) -> dict:
        _require_session()
        return await _managed_call(
            _state_client().ensure_session,
            _request_actor(request),
            _request_session_id(request),
        )


    # Document upload endpoint
    @app.post("/api/demo/documents/upload", include_in_schema=False)
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
    ) -> dict:
        session_id = _request_session_id(request)
        actor = _request_actor(request)

        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="Please select a document.",
            )

        max_file_size = 15 * 1024 * 1024
        content = await file.read(max_file_size + 1)

        if len(content) > max_file_size:
            raise HTTPException(
                status_code=413,
                detail="File is too large. Maximum size is 15 MB.",
            )

        try:
            extracted_text = extract_document_text(
                file.filename,
                content,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        # Detect locations from extracted document text.
        locations = extract_locations(extracted_text)

        # Local development uses the in-process checkpointer.
        # Managed Session Store persistence is used when deployed.
        persisted = False

        if _is_deployed():
            _require_session()

            await _managed_call(
                _state_client().ensure_session,
                actor,
                session_id,
            )

            session = await _managed_call(
                _state_client().get_session,
                session_id,
            )

            if session.get("actor_id") != actor:
                raise HTTPException(
                    status_code=403,
                    detail="Session belongs to another actor.",
                )

            await _managed_call(
                _state_client().append_session_items,
                session_id,
                [
                    {
                        "kind": "uploaded_document",
                        "filename": file.filename,
                        "text": extracted_text,
                        "locations": locations,
                    }
                ],
            )

            persisted = True

        return {
            "success": True,
            "filename": file.filename,
            "characters_extracted": len(extracted_text),
            "session_id": session_id,
            "document_text": extracted_text,
            "locations": locations,
            "persisted": persisted,
            "message": (
                "Document uploaded and saved to this session."
                if persisted
                else "Document uploaded and extracted successfully."
            ),
        }


    @app.get("/api/demo/sessions", include_in_schema=False)
    async def list_sessions(request: Request) -> dict:
        session_id = _request_session_id(request)
        actor = _request_actor(request)

        if not _session_store():
            return {
                "sessions": [
                    {
                        "session_id": session_id,
                        "actor_id": actor,
                        "metadata": {"client": "agentbricks-demo-ui-local"},
                    }
                ],
                "current_session_id": session_id,
                "managed": False,
            }

        result = await _managed_call(_state_client().list_sessions, actor)

        return {
            **result,
            "sessions": _chat_sessions(result),
            "current_session_id": session_id,
            "managed": True,
        }

    @app.post("/api/demo/sessions/{session_id}/open", include_in_schema=False)
    async def open_session(request: Request, session_id: str) -> JSONResponse:
        _require_session()
        session = await _managed_call(_state_client().get_session, session_id)

        if session.get("actor_id") != _request_actor(request):
            raise HTTPException(status_code=403, detail="Session belongs to another actor.")

        return JSONResponse(
            {
                "session_id": session_id,
                "previous_session_id": _request_session_id(request),
                "managed": True,
            }
        )

    @app.get("/api/demo/session", include_in_schema=False)
    async def get_session(request: Request) -> dict:
        _require_session()
        return await _managed_call(
            _state_client().get_session,
            _request_session_id(request),
        )

    @app.post("/api/demo/session/items", include_in_schema=False)
    async def append_session_items(request: Request, payload: SessionItemsRequest) -> dict:
        _require_session()
        return await _managed_call(
            _state_client().append_session_items,
            _request_session_id(request),
            payload.items,
        )

    @app.get("/api/demo/session/items", include_in_schema=False)
    async def list_session_items(request: Request) -> dict:
        session_id = _request_session_id(request)
        actor = _request_actor(request)

        if not app.auth_policy.requires_user:
            return await _checkpoint_history(session_id, actor)

        from databricks_agentkit.runtime.auth import RequestAuthContext

        auth = RequestAuthContext.from_headers(request.headers)
        try:
            result = await _checkpoint_history(
                auth.namespace("session", session_id),
                auth.namespace("actor", actor),
            )
            return {**result, "session_id": session_id}
        finally:
            auth.close()
