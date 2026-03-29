"""
HITL Node — posts Slack approval message and polls for 👍/👎 reactions.
No ngrok needed — works entirely via Slack API polling.
"""
import os
import time
import asyncio
from langgraph.types import interrupt
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from agent.state import ClusterState
from agent.models import RemediationPlan


# Poll for reactions every 5 seconds, timeout after 5 minutes
REACTION_POLL_INTERVAL = 5
REACTION_TIMEOUT = 300


def hitl_node(state: ClusterState) -> ClusterState:
    """
    1. Posts Slack message with 👍 Approve / 👎 Reject instructions
    2. Polls Slack for emoji reactions on that message
    3. Returns decision based on which reaction was added
    """
    plan: RemediationPlan = state["plan"]
    anomaly = state["current_anomaly"]

    if not plan or not anomaly:
        return {**state, "hitl_decision": "rejected"}

    # Post the approval message to Slack
    ts = _post_slack_approval(state)

    if ts:
        # Poll Slack for reactions (blocking until 👍 or 👎 is found)
        decision = _poll_for_reaction(ts)
        print(f"[hitl] Slack decision received: {decision}")
    else:
        # Slack not available — auto-approve with warning
        print("[hitl] Slack unavailable — auto-approving (demo mode)")
        decision = "approved"

    return {
        **state,
        "hitl_decision": decision,
        "slack_message_ts": ts,
    }


def _post_slack_approval(state: ClusterState) -> str:
    """Posts approval message to Slack. Returns message timestamp."""
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_CHANNEL_ID", "")

    if not token or not channel or token == "xoxb-..." or channel == "C...":
        print("[hitl] Slack not configured — skipping")
        return ""

    plan = state["plan"]
    anomaly = state["current_anomaly"]
    diagnosis_short = state.get("diagnosis", "")[:300]

    severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
    sev_icon = severity_emoji.get(anomaly.severity.value, "⚪")

    blocks = [
        {"type": "header", "text": {"type": "plain_text",
            "text": f"{sev_icon} K8sWhisperer — Approval Required"}},
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
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": "*React to this message:*\n\n👍  = *Approve* — execute the action\n👎  = *Reject* — skip this action"}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "K8sWhisperer Agent | Waiting for your reaction..."}
        ]}
    ]

    client = WebClient(token=token)
    try:
        response = client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=f"🛡️ Approval Required: {plan.action} on {anomaly.affected_resource}"
        )
        msg_ts = response["ts"]
        print(f"[hitl] Posted Slack approval message (ts={msg_ts})")
        print(f"[hitl] → React with 👍 to approve or 👎 to reject in Slack")
        return msg_ts
    except SlackApiError as e:
        print(f"[hitl] Slack post failed: {e.response['error']}")
        return ""


def _poll_for_reaction(message_ts: str) -> str:
    """
    Polls Slack for 👍 (approve) or 👎 (reject) reactions on the message.
    Returns 'approved' or 'rejected'.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_CHANNEL_ID", "")
    client = WebClient(token=token)

    start = time.time()
    print(f"[hitl] Waiting for Slack reaction (timeout={REACTION_TIMEOUT}s)...")

    while time.time() - start < REACTION_TIMEOUT:
        try:
            result = client.reactions_get(channel=channel, timestamp=message_ts)
            message = result.get("message", {})
            reactions = message.get("reactions", [])

            for reaction in reactions:
                name = reaction.get("name", "")
                if name in ("+1", "thumbsup"):
                    # Update message to show approved
                    _update_slack_status(client, channel, message_ts, "✅ APPROVED — executing action")
                    return "approved"
                elif name in ("-1", "thumbsdown"):
                    _update_slack_status(client, channel, message_ts, "❌ REJECTED — action skipped")
                    return "rejected"

        except SlackApiError as e:
            error = e.response.get('error', '')
            if error == 'missing_scope':
                print(f"[hitl] Slack missing reactions:read scope — auto-approving")
                _update_slack_status(client, channel, message_ts, "✅ AUTO-APPROVED (reactions scope not configured)")
                return "approved"
            print(f"[hitl] Reaction poll error: {error}")

        time.sleep(REACTION_POLL_INTERVAL)

    # Timeout — reject by default
    print(f"[hitl] Timeout after {REACTION_TIMEOUT}s — auto-rejecting")
    _update_slack_status(client, channel, message_ts, "⏰ TIMEOUT — action skipped")
    return "rejected"


def _update_slack_status(client: WebClient, channel: str, ts: str, status: str):
    """Updates the Slack message to show the decision."""
    try:
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f"*{status}*\n_Decision recorded by K8sWhisperer_"
        )
    except Exception:
        pass
