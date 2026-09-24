"""FastAPI application providing REST endpoints and SSE streaming."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ml_mon.config import AntigravityConfig
from ml_mon.core.parser import ConversationParser
from ml_mon.core.scanner import ConversationScanner
from ml_mon.core.tailer import ConversationTailer


def create_app(config: Optional[AntigravityConfig] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    cfg = config or AntigravityConfig.discover()
    scanner = ConversationScanner(cfg)
    parser = ConversationParser(cfg)

    app = FastAPI(
        title="gmon API",
        description="Antigravity IDE Conversation & Chain of Thought Monitor",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/conversations")
    async def list_conversations():
        """List all discovered conversations."""
        summaries = scanner.scan_all()
        return [s.model_dump() for s in summaries]

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str):
        """Get complete conversation detail, steps, CoTs, and plan."""
        # Allow "latest" alias
        if conversation_id.lower() == "latest":
            summaries = scanner.scan_all()
            if not summaries:
                raise HTTPException(status_code=404, detail="No conversations found")
            conversation_id = summaries[0].id

        detail = parser.parse_conversation(conversation_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        return detail.model_dump()

    @app.get("/api/conversations/{conversation_id}/plan")
    async def get_plan(conversation_id: str):
        """Get the current implementation plan and walkthrough."""
        if conversation_id.lower() == "latest":
            summaries = scanner.scan_all()
            if not summaries:
                raise HTTPException(status_code=404, detail="No conversations found")
            conversation_id = summaries[0].id

        plan = parser.parse_plan_asset(conversation_id)
        if not plan:
            return {"plan_content": None, "walkthrough_content": None}
        return plan.model_dump()

    @app.get("/api/conversations/{conversation_id}/context")
    async def get_context_window(conversation_id: str):
        """Get the full context window frames, compaction boundary, and token usage breakdown."""
        if conversation_id.lower() == "latest":
            summaries = scanner.scan_all()
            if not summaries:
                raise HTTPException(status_code=404, detail="No conversations found")
            conversation_id = summaries[0].id

        report = parser.extract_context_window(conversation_id)
        if not report:
            raise HTTPException(status_code=404, detail=f"Context for conversation {conversation_id} not found")
        return report.model_dump()

    @app.get("/api/conversations/{conversation_id}/evolution")
    async def get_context_evolution(conversation_id: str):
        """Get the step-by-step context window and prompt evolution series."""
        if conversation_id.lower() == "latest":
            summaries = scanner.scan_all()
            if not summaries:
                raise HTTPException(status_code=404, detail="No conversations found")
            conversation_id = summaries[0].id

        report = parser.extract_context_window(conversation_id)
        if not report or not report.evolution:
            raise HTTPException(status_code=404, detail=f"Evolution for conversation {conversation_id} not found")
        return report.evolution.model_dump()

    @app.get("/api/conversations/{conversation_id}/prompt")
    async def get_conversation_prompt(conversation_id: str):
        """Return the reconstructed full prompt and semantic sections."""
        if conversation_id.lower() == "latest":
            summaries = scanner.scan_all()
            if not summaries:
                raise HTTPException(status_code=404, detail="No conversations found")
            conversation_id = summaries[0].id

        from ml_mon.core.prompt_reconstructor import PromptReconstructor
        reconstructor = PromptReconstructor(cfg)
        prompt = reconstructor.reconstruct(conversation_id)
        if not prompt:
            raise HTTPException(status_code=404, detail=f"Unable to reconstruct prompt for {conversation_id}")
        return prompt.model_dump()

    @app.get("/api/conversations/{conversation_id}/prompt/raw", response_class=PlainTextResponse)
    async def get_conversation_prompt_raw(conversation_id: str, download: bool = False):
        """Return the raw reconstructed prompt text."""
        if conversation_id.lower() == "latest":
            summaries = scanner.scan_all()
            if not summaries:
                raise HTTPException(status_code=404, detail="No conversations found")
            conversation_id = summaries[0].id

        from ml_mon.core.prompt_reconstructor import PromptReconstructor
        reconstructor = PromptReconstructor(cfg)
        prompt = reconstructor.reconstruct(conversation_id)
        if not prompt:
            raise HTTPException(status_code=404, detail=f"Unable to reconstruct prompt for {conversation_id}")
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="prompt_{conversation_id[:8]}.txt"'
        return PlainTextResponse(content=prompt.raw_prompt_text, headers=headers)

    @app.get("/api/conversations/{conversation_id}/stream")
    async def stream_conversation(conversation_id: str):
        """SSE stream broadcasting real-time step events and plan updates."""
        if conversation_id.lower() == "latest":
            summaries = scanner.scan_all()
            if not summaries:
                raise HTTPException(status_code=404, detail="No conversations found")
            conversation_id = summaries[0].id

        tailer = ConversationTailer(conversation_id, cfg)

        async def event_generator():
            try:
                async for event in tailer.stream_events(poll_interval=0.4):
                    payload = json.dumps(event["data"])
                    yield f"event: {event['event']}\ndata: {payload}\n\n"
            except Exception:
                pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/artifacts/{conversation_id}/{filename}")
    async def get_artifact(conversation_id: str, filename: str):
        """Serve media file (screenshot, video) from brain directory."""
        from fastapi.responses import FileResponse
        file_path = cfg.get_brain_dir(conversation_id) / filename
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")
        return FileResponse(path=str(file_path))

    @app.get("/api/artifacts/{conversation_id}/tasks/{filename}")
    async def get_task_log(conversation_id: str, filename: str):
        """Serve task log file."""
        from fastapi.responses import FileResponse
        log_path = cfg.get_brain_dir(conversation_id) / ".system_generated" / "tasks" / filename
        if not log_path.exists() or not log_path.is_file():
            raise HTTPException(status_code=404, detail="Task log not found")
        return FileResponse(path=str(log_path), media_type="text/plain")
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def root():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>gmon</h1><p>Dashboard loaded.</p>")

    return app
