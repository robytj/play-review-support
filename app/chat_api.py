"""Shadow chat agent API (SPEC-08 §4) -- key-gated endpoints under
/api/dashboard/chat/*, called server-to-server by the Ops Dashboard's
`_supportbot_request` proxy (play-review-responder /api/support/chat/*). Same
Bearer service-key dependency as the rest of the dashboard API; the browser never
talks to this service directly.

Kill switch: config.CHAT_ENABLED (Support Settings toggle, hot-reloaded from
config.yaml like shadow_mode). When off, POST /chat/sessions answers
503 {"error": "chat_disabled"} and the tab shows chat as down.
"""
import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import chat_engine, config
from app.dashboard_api import require_service_key, _staff_actor

router = APIRouter(prefix="/api/dashboard/chat")

MAX_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}


class MessageRequest(BaseModel):
    text: str


class EndRequest(BaseModel):
    reason: str = "manual"   # manual | timeout


def _closed(exc: chat_engine.SessionClosed) -> JSONResponse:
    return JSONResponse(status_code=409,
                        content={"error": "session_ended", "state": exc.state})


@router.get("/health", dependencies=[Depends(require_service_key)])
def health():
    """Shadow-testing diagnostics: is the game Mongo reachable from THIS deploy?
    A dead Mongo otherwise masquerades as 'SID not found' in the chat."""
    from app import player_context
    mongo_ok = False
    try:
        db = player_context._db()
        if db is not None:
            db.client.admin.command("ping")
            mongo_ok = True
    except Exception:
        mongo_ok = False
    return {"chat_enabled": bool(config.CHAT_ENABLED), "mongo": mongo_ok}


@router.post("/sessions", dependencies=[Depends(require_service_key)])
def create_session():
    if not config.CHAT_ENABLED:
        return JSONResponse(status_code=503, content={"error": "chat_disabled"})
    return chat_engine.create_session()


@router.post("/sessions/{session_id}/messages", dependencies=[Depends(require_service_key)])
def post_message(session_id: int, req: MessageRequest):
    if not (req.text or "").strip():
        raise HTTPException(400, "text required")
    try:
        return chat_engine.handle_message(session_id, req.text)
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")
    except chat_engine.SessionClosed as e:
        return _closed(e)


@router.post("/sessions/{session_id}/image", dependencies=[Depends(require_service_key)])
async def post_image(session_id: int, file: UploadFile = File(...)):
    """One screenshot per call, jpeg/png, <= 4MB; Haiku vision extracts a SID-shaped
    code which is then validated against Mongo like a typed SID. Max 2 images per
    session (enforced in the engine -> degraded mode after the second miss)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(415, "image must be jpeg or png")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image too large (max 4MB)")
    if not data:
        raise HTTPException(400, "empty upload")
    try:
        return chat_engine.handle_image(
            session_id, base64.b64encode(data).decode("ascii"), file.content_type)
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")
    except chat_engine.SessionClosed as e:
        return _closed(e)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/sessions/{session_id}/end", dependencies=[Depends(require_service_key)])
def end_session(session_id: int, req: EndRequest | None = None):
    reason = (req.reason if req else "manual") or "manual"
    if reason not in ("manual", "timeout"):
        raise HTTPException(400, "reason must be 'manual' or 'timeout'")
    try:
        return chat_engine.end_session(session_id, reason)
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")


@router.get("/sessions/{session_id}", dependencies=[Depends(require_service_key)])
def get_session(session_id: int):
    try:
        return chat_engine.get_session(session_id)
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")


@router.get("/sessions", dependencies=[Depends(require_service_key)])
def list_sessions(limit: int = 50, offset: int = 0):
    return chat_engine.list_sessions(limit=min(limit, 200), offset=max(offset, 0))


# --------------------------------------------------------- live human takeover --
# Staff attribution mirrors ticketing (SPEC-09 §6): the responder proxy forwards
# the logged-in user's Google email as X-Staff-Email; absent header -> 'system'.

@router.post("/sessions/{session_id}/takeover", dependencies=[Depends(require_service_key)])
def takeover(session_id: int, actor: str = Depends(_staff_actor)):
    try:
        return chat_engine.take_over(session_id, actor)
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")
    except chat_engine.SessionClosed as e:
        return _closed(e)


@router.post("/sessions/{session_id}/release", dependencies=[Depends(require_service_key)])
def release(session_id: int, actor: str = Depends(_staff_actor)):
    try:
        return chat_engine.release(session_id, actor)
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")
    except chat_engine.NotHumanControlled as e:
        raise HTTPException(409, str(e))


@router.post("/sessions/{session_id}/agent-message", dependencies=[Depends(require_service_key)])
def agent_message(session_id: int, req: MessageRequest, actor: str = Depends(_staff_actor)):
    if not (req.text or "").strip():
        raise HTTPException(400, "text required")
    try:
        return chat_engine.agent_message(session_id, actor, req.text.strip())
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")
    except chat_engine.SessionClosed as e:
        return _closed(e)
    except chat_engine.NotHumanControlled as e:
        raise HTTPException(409, str(e))


@router.get("/sessions/{session_id}/messages", dependencies=[Depends(require_service_key)])
def poll_messages(session_id: int, after_id: int = 0):
    """Incremental transcript fetch -- both the observing agent and the player tab
    poll this (e.g. every 2-3s) while controller='human'."""
    try:
        return chat_engine.get_messages(session_id, after_id=max(after_id, 0))
    except chat_engine.SessionNotFound:
        raise HTTPException(404, "session not found")
