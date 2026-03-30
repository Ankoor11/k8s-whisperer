import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse

app = FastAPI(title="K8sWhisperer HITL Webhook")

AUDIT_LOG_PATH = Path("audit_log.json")

# In-memory store mapping thread_id → pending incident info
_pending_approvals: dict[str, dict] = {}


@app.get("/api/audit-log")
async def get_audit_log():
    """Serves the audit log JSON for the frontend dashboard."""
    try:
        if AUDIT_LOG_PATH.exists():
            data = json.loads(AUDIT_LOG_PATH.read_text())
            return JSONResponse(content=data)
        return JSONResponse(content=[])
    except Exception:
        return JSONResponse(content=[])




def register_pending(thread_id: str, info: dict):
    """Called by hitl_node when an incident requires human approval."""
    _pending_approvals[thread_id] = {
        "info": info,
        "ts": time.time(),
        "status": "pending"
    }
    print(f"[webhook] Registered pending approval: {thread_id[:12]}...")
    print(f"[webhook] → Open http://localhost:8002/pending to approve/reject")


# ── LOCAL WEB UI (no ngrok needed) ─────────────────────────────────

@app.get("/pending", response_class=HTMLResponse)
async def pending_page():
    """Local approval dashboard — judges can use this instead of Slack buttons."""
    rows = ""
    for tid, data in _pending_approvals.items():
        info = data.get("info", {})
        status = data.get("status", "pending")
        age = int(time.time() - data.get("ts", 0))

        icon = "⏳" if status == "pending" else ("✅" if status == "approved" else "❌")
        buttons = ""
        if status == "pending":
            buttons = f'''
                <a href="/approve/{tid}" style="background:#22c55e;color:#fff;padding:8px 20px;border-radius:6px;text-decoration:none;margin-right:8px;font-weight:bold">✅ Approve</a>
                <a href="/reject/{tid}" style="background:#ef4444;color:#fff;padding:8px 20px;border-radius:6px;text-decoration:none;font-weight:bold">❌ Reject</a>
            '''
        else:
            buttons = f'<span style="color:#888">{status}</span>'

        rows += f'''
        <tr style="border-bottom:1px solid #333">
            <td style="padding:12px">{icon}</td>
            <td style="padding:12px"><code>{tid[:12]}...</code></td>
            <td style="padding:12px">{info.get("anomaly_type", "—")}</td>
            <td style="padding:12px"><code>{info.get("affected_resource", "—")}</code></td>
            <td style="padding:12px">{info.get("blast_radius", "—")}</td>
            <td style="padding:12px">{info.get("action", "—")}</td>
            <td style="padding:12px">{info.get("confidence", "—")}</td>
            <td style="padding:12px">{age}s ago</td>
            <td style="padding:12px">{buttons}</td>
        </tr>
        '''

    if not rows:
        rows = '<tr><td colspan="9" style="padding:30px;text-align:center;color:#888">No pending approvals. Deploy a test scenario to trigger HITL.</td></tr>'

    html = f'''<!DOCTYPE html>
    <html>
    <head>
        <title>K8sWhisperer — HITL Approval Dashboard</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body {{ font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 20px }}
            h1 {{ color: #38bdf8; margin-bottom: 4px }}
            .subtitle {{ color: #64748b; margin-bottom: 24px }}
            table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden }}
            th {{ background: #334155; padding: 12px; text-align: left; color: #94a3b8; font-size: 12px; text-transform: uppercase }}
            code {{ background: #334155; padding: 2px 6px; border-radius: 4px; font-size: 13px }}
        </style>
    </head>
    <body>
        <h1>🛡️ K8sWhisperer — Human-in-the-Loop Dashboard</h1>
        <p class="subtitle">Auto-refreshes every 5 seconds. No ngrok required.</p>
        <table>
            <tr>
                <th></th><th>Thread</th><th>Anomaly</th><th>Resource</th>
                <th>Blast Radius</th><th>Action</th><th>Confidence</th><th>Age</th><th>Decision</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>'''
    return HTMLResponse(content=html)


@app.get("/approve/{thread_id}", response_class=HTMLResponse)
async def approve_action(thread_id: str):
    """Approve a pending HITL action via browser click."""
    if thread_id in _pending_approvals:
        _pending_approvals[thread_id]["status"] = "approved"
    await _resume_graph(thread_id, "approved")
    return HTMLResponse(content=f'''
        <html><body style="font-family:sans-serif;background:#0f172a;color:#e2e8f0;text-align:center;padding:60px">
        <h1>✅ Approved</h1>
        <p>Thread <code>{thread_id[:12]}...</code> — executing remediation now.</p>
        <a href="/pending" style="color:#38bdf8">← Back to dashboard</a>
        </body></html>
    ''')


@app.get("/reject/{thread_id}", response_class=HTMLResponse)
async def reject_action(thread_id: str):
    """Reject a pending HITL action via browser click."""
    if thread_id in _pending_approvals:
        _pending_approvals[thread_id]["status"] = "rejected"
    await _resume_graph(thread_id, "rejected")
    return HTMLResponse(content=f'''
        <html><body style="font-family:sans-serif;background:#0f172a;color:#e2e8f0;text-align:center;padding:60px">
        <h1>❌ Rejected</h1>
        <p>Thread <code>{thread_id[:12]}...</code> — action skipped.</p>
        <a href="/pending" style="color:#38bdf8">← Back to dashboard</a>
        </body></html>
    ''')


# ── SLACK WEBHOOK (works with ngrok when available) ─────────────────

def _verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    secret = os.getenv("SLACK_SIGNING_SECRET", "")
    if not secret or secret == "...":
        return True
    base = f"v0:{timestamp}:{request_body.decode()}"
    expected = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/slack/actions")
async def slack_actions(request: Request):
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

    if thread_id in _pending_approvals:
        _pending_approvals[thread_id]["status"] = decision

    await _resume_graph(thread_id, decision)

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


# ── GRAPH RESUME ────────────────────────────────────────────────────

async def _resume_graph(thread_id: str, decision: str):
    """Resumes the suspended LangGraph graph with the human's decision."""
    from agent.graph import graph, get_config
    from langgraph.types import Command

    config = get_config(thread_id)
    try:
        await graph.ainvoke(
            Command(resume={"decision": decision}),
            config=config
        )
        print(f"[webhook] Graph resumed: thread={thread_id[:12]}, decision={decision}")
    except Exception as e:
        print(f"[webhook] Failed to resume graph: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "k8swhisperer-webhook",
            "pending_approvals": len([p for p in _pending_approvals.values() if p["status"] == "pending"])}
