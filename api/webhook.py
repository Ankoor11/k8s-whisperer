"""
FastAPI webhook server — receives Slack Approve/Reject button callbacks.
Resumes the suspended LangGraph graph by calling graph.invoke() with updated state.
Start with: uvicorn api.webhook:app --port 8002
"""
import hashlib
import hmac
import json
import os
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="K8sWhisperer HITL Webhook")

# In-memory store mapping thread_id → pending state
# In production use Redis; for hackathon an in-process dict is fine
_pending_approvals: dict[str, dict] = {}


def register_pending(thread_id: str, state: dict):
    """Called by hitl_node before posting to Slack."""
    _pending_approvals[thread_id] = {"state": state, "ts": time.time()}


def _verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature to prevent spoofing."""
    secret = os.getenv("SLACK_SIGNING_SECRET", "")
    if not secret:
        return True  # skip in dev mode
    base = f"v0:{timestamp}:{request_body.decode()}"
    expected = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/slack/actions")
async def slack_actions(request: Request):
    """
    Receives Slack interactive component payloads (button clicks).
    Parses the action and resumes the correct LangGraph thread.
    """
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    form_data = await request.form()
    payload = json.loads(form_data.get("payload", "{}"))

    actions = payload.get("actions", [])
    if not actions:
        return JSONResponse({"ok": True})

    action = actions[0]
    action_id = action.get("action_id")
    thread_id = action.get("value", "")

    decision = "approved" if action_id == "approve_action" else "rejected"

    print(f"[webhook] Received {decision} for thread {thread_id[:12]}...")

    # Resume the LangGraph graph
    await _resume_graph(thread_id, decision)

    # Acknowledge to Slack (must respond within 3s)
    icon = "✅" if decision == "approved" else "❌"
    return JSONResponse({
        "response_action": "update",
        "view": {
            "type": "modal",
            "title": {"type": "plain_text", "text": "Response recorded"},
            "blocks": [{"type": "section", "text": {"type": "mrkdwn",
                "text": f"{icon} Action *{decision}* — K8sWhisperer is processing."}}]
        }
    })


async def _resume_graph(thread_id: str, decision: str):
    """
    Resumes the suspended LangGraph graph with the human's decision.
    Uses Command(resume=...) to properly resume from interrupt().
    """
    from agent.graph import graph, get_config
    from langgraph.types import Command

    config = get_config(thread_id)
    try:
        await graph.ainvoke(
            Command(resume={"decision": decision}),
            config=config
        )
        print(f"[webhook] Graph resumed for thread {thread_id[:12]}, decision={decision}")
    except Exception as e:
        print(f"[webhook] Failed to resume graph: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "k8swhisperer-webhook"}
