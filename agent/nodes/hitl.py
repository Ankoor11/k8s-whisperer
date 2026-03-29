"""
HITL Node — suspends LangGraph graph and posts Slack approval request.
Graph resumes only when /approve or /reject webhook is called.
"""
import os
from langgraph.types import interrupt
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from agent.state import ClusterState
from agent.models import RemediationPlan


def hitl_node(state: ClusterState) -> ClusterState:
    """
    Posts Slack Block Kit message with Approve/Reject buttons.
    Calls interrupt() to suspend the LangGraph graph.
    The graph resumes when the FastAPI webhook updates state and calls graph.invoke().
    """
    plan: RemediationPlan = state["plan"]
    anomaly = state["current_anomaly"]
    ts = ""

    if plan and anomaly:
        ts = _post_slack_approval(state)

    # interrupt() suspends the graph here. Execution resumes when graph.invoke() is called
    # with the same thread_id and state.hitl_decision set to "approved" or "rejected".
    human_decision = interrupt({
        "message": "Awaiting human approval",
        "plan": plan.model_dump() if plan else {},
        "slack_message_ts": ts,
    })

    return {
        **state,
        "hitl_decision": human_decision.get("decision", "rejected"),
        "slack_message_ts": ts,
    }


def _post_slack_approval(state: ClusterState) -> str:
    """Posts Block Kit message with Approve/Reject buttons. Returns message timestamp."""
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL_ID")
    webhook_base = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8002")

    plan = state["plan"]
    anomaly = state["current_anomaly"]
    diagnosis_short = state.get("diagnosis", "")[:300]
    thread_id = state.get("hitl_thread_id", "unknown")

    severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
    sev_icon = severity_emoji.get(anomaly.severity.value, "⚪")

    blocks = [
        {"type": "header", "text": {"type": "plain_text",
            "text": f"{sev_icon} K8sWhisperer — Action Approval Required"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Anomaly:*\n`{anomaly.type.value}`"},
            {"type": "mrkdwn", "text": f"*Severity:*\n`{anomaly.severity.value}`"},
            {"type": "mrkdwn", "text": f"*Resource:*\n`{anomaly.affected_resource}`"},
            {"type": "mrkdwn", "text": f"*Blast Radius:*\n`{plan.blast_radius.value}`"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Proposed action:* `{plan.action}`\n*Confidence:* {plan.confidence:.0%}"}},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Diagnosis:*\n{diagnosis_short}"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ Approve"},
             "style": "primary",
             "action_id": "approve_action",
             "value": f"{thread_id}"},
            {"type": "button", "text": {"type": "plain_text", "text": "❌ Reject"},
             "style": "danger",
             "action_id": "reject_action",
             "value": f"{thread_id}"},
        ]},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"Thread ID: `{thread_id[:12]}...` | K8sWhisperer Agent"}
        ]}
    ]

    if not token or not channel or token == "xoxb-..." or channel == "C...":
        print("[hitl] Slack not configured — skipping approval post")
        return ""

    client = WebClient(token=token)
    try:
        response = client.chat_postMessage(channel=channel, blocks=blocks)
        return response["ts"]
    except SlackApiError as e:
        print(f"[hitl] Slack post failed: {e.response['error']}")
        return ""
