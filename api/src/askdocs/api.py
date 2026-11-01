import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from askdocs import config, db, helpcenter
from askdocs.answer import answer_stream
from askdocs.embed import embed_query


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Message] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = db.pool()
    db.init_logs(app.state.pool)
    # Load local models (or open the embedding API connection) now, so the first user doesn't wait.
    embed_query("warm up")
    if config.RERANK == "local":
        from askdocs.rerank import model as rerank_model

        rerank_model()
    yield
    app.state.pool.close()


app = FastAPI(title="askdocs", lifespan=lifespan)
# The widget is embedded on other sites, so any origin may call the API.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _events(req: ChatRequest) -> Iterator[dict]:
    pool = app.state.pool
    with pool.connection() as conn:
        for event in answer_stream(conn, req.question, [m.model_dump() for m in req.history]):
            if event["type"] == "done":
                db.log_answer(conn, req.question, event)
            yield event


STATIC = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def demo() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/widget.js", include_in_schema=False)
def widget() -> FileResponse:
    return FileResponse(STATIC / "widget.js", media_type="text/javascript", headers={"Cache-Control": "public, max-age=300"})


@app.get("/help", include_in_schema=False)
def help_index() -> HTMLResponse:
    return HTMLResponse(helpcenter.index_html())


@app.get("/help/{slug}", include_in_schema=False)
def help_page(slug: str) -> HTMLResponse:
    html = helpcenter.page_html(slug)
    if html is None:
        raise HTTPException(404, "No such help page")
    return HTMLResponse(html)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    """Non-streaming: returns the final answer with its sources."""
    sources: list = []
    for event in _events(req):
        if event["type"] == "sources":
            sources = event["sources"]
        elif event["type"] == "done":
            return {**{k: v for k, v in event.items() if k != "type"}, "sources": sources}
    raise RuntimeError("answer stream ended without a done event")


@app.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-sent events: `sources`, then `token`s, then `done`."""

    def sse() -> Iterator[str]:
        for event in _events(req):
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
