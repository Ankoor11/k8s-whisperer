"""
Explain Node — writes plain-English summary and appends to audit_log.json.
Also posts Slack summary message.
"""
import json
import os
import uuid
import time
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm_helper import get_llm, invoke_with_retry
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from agent.state import ClusterState
from agent.models import LogEntry


EXPLAIN_PROMPT = """You are writing a plain-English incident summary for a non-technical stakeholder.

Given an incident's diagnosis, the remediation plan, and the execution result:
Write 2-3 sentences that explain:
1. What went wrong (in plain English — no Kubernetes jargon)
2. What the agent did about it (or what it's recommending)
3. Whether the issue was resolved

Rules:
- No Kubernetes acronyms (say "memory limit" not "OOMKilled")
- No YAML or code
- Suitable for a Slack message to a non-engineer
- Max 60 words
"""

AUDIT_LOG_PATH = Path("audit_log.json")


async def explain_node(state: ClusterState) -> ClusterState:
    llm = get_llm()

    anomaly = state.get("current_anomaly")
    plan = state.get("plan")

    if not anomaly or not plan:
        return state

    # Generate plain-English explanation
    context = f"""Anomaly: {anomaly.type.value} on {anomaly.affected_resource}
Diagnosis: {state.get("diagnosis", "")}
Action taken: {plan.action}
Result: {state.get("result", "")}
Execution success: {state.get("execution_success", False)}
"""

    messages = [
        SystemMessage(content=EXPLAIN_PROMPT),
        HumanMessage(content=context)
    ]

    explanation = await invoke_with_retry(llm, messages, label="explain")

    # Determine decision label
    route = state.get("route", "")
    hitl = state.get("hitl_decision", "pending")
    if route == "auto_execute":
        decision = "auto_executed"
    elif hitl == "approved":
        decision = "hitl_approved"
    elif hitl == "rejected":
        decision = "hitl_rejected"
    else:
        decision = "skipped"

    # Build log entry
    entry = LogEntry(
        incident_id=state.get("incident_id", str(uuid.uuid4())),
        anomaly_type=anomaly.type.value,
        affected_resource=anomaly.affected_resource,
        diagnosis=state.get("diagnosis", ""),
        plan_action=plan.action,
        plan_blast_radius=plan.blast_radius.value,
        decision=decision,
        result=state.get("result", ""),
        explanation=explanation,
    )

    # Append to audit_log.json
    _append_audit_log(entry)

    # Post to Slack
    _post_slack_summary(explanation, entry)

    # Update in-memory audit log
    audit_log = list(state.get("audit_log", []))
    audit_log.append(entry)

    return {**state, "explanation": explanation, "audit_log": audit_log}


def _append_audit_log(entry: LogEntry):
    """Appends LogEntry to persistent audit_log.json."""
    existing = []
    if AUDIT_LOG_PATH.exists():
        try:
            existing = json.loads(AUDIT_LOG_PATH.read_text())
        except Exception:
            existing = []
    existing.append(entry.model_dump())
    AUDIT_LOG_PATH.write_text(json.dumps(existing, indent=2, default=str))


def _post_slack_summary(explanation: str, entry: LogEntry):
    """Posts incident resolution summary to Slack."""
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_CHANNEL_ID", "")
    # Skip if empty or still using placeholder values
    if not token or not channel or token == "xoxb-..." or channel == "C...":
        print(f"[explain] Slack not configured — skipping notification")
        return

    icon = "✅" if entry.decision in ("auto_executed", "hitl_approved") else "⚠️"
    result_short = str(entry.result)[:200] if entry.result else ""
    client = WebClient(token=token)
    try:
        client.chat_postMessage(
            channel=channel,
            text=f"{icon} {entry.anomaly_type} on {entry.affected_resource} — {entry.decision}",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn",
                    "text": f"{icon} *Incident Resolved* — `{entry.anomaly_type}` on `{entry.affected_resource}`"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": explanation}},
                {"type": "section", "text": {"type": "mrkdwn",
                    "text": f"*Result:*\n```{result_short}```"}},
                {"type": "context", "elements": [
                    {"type": "mrkdwn",
                     "text": f"Action: `{entry.plan_action}` | Decision: `{entry.decision}` | ID: `{entry.incident_id[:8]}`"}
                ]},
                {"type": "divider"}
            ]
        )
        print(f"[explain] Slack summary posted for {entry.anomaly_type}")
    except SlackApiError as e:
        print(f"[explain] Slack post failed: {e.response['error']}")
