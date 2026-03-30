"""
HITL Node — posts Slack approval message and polls for thread replies.
User replies 'yes' (👍 approve) or 'no' (👎 reject) in the Slack thread.
No ngrok, no reactions:read scope needed — only channels:history.
"""
import os
import time
import asyncio
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from agent.state import ClusterState
from agent.models import RemediationPlan, HITLDecision


# Poll for replies every 5 seconds, timeout after 5 minutes
REPLY_POLL_INTERVAL = 5
REPLY_TIMEOUT = 60

# Words that count as approve/reject
APPROVE_WORDS = {"yes", "approve", "approved", "y", "ok", "go", "do it", "proceed", "👍"}
REJECT_WORDS = {"no", "reject", "rejected", "n", "stop", "skip", "cancel", "👎"}


async def hitl_node(state: ClusterState) -> ClusterState:
    """
    1. Posts Slack message with approval request
    2. Polls for thread replies ('yes' / 'no')
    3. Returns decision based on reply content
    """
    plan: RemediationPlan = state["plan"]
    anomaly = state["current_anomaly"]

    if not plan or not anomaly:
        return {**state, "hitl_decision": HITLDecision.REJECTED}

    # Post the approval message to Slack
    ts = _post_slack_approval(state)

    if ts:
        decision = await _poll_for_reply_async(ts)
        if decision == "poll_error":
            print("[hitl] ⚠️  Add 'channels:history' scope to your Slack app, then reinstall!")
            print("[hitl] Auto-rejecting this incident for safety.")
            decision = HITLDecision.REJECTED
        else:
            print(f"[hitl] Slack decision received: {decision}")
    else:
        print("[hitl] Slack unavailable — auto-rejecting")
        decision = HITLDecision.REJECTED

    return {
        **state,
        "hitl_decision": decision,
        "slack_message_ts": ts or "",
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
            "text": "🛡️ *Reply in this thread to decide:*\n\n"
                    "👍  Type `yes` → *Approve* — execute the action\n"
                    "👎  Type `no`  → *Reject* — skip this action\n\n"
                    "⏰ _Auto-rejects after 60 seconds if no response_"}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "K8sWhisperer Agent | Waiting for your reply..."}
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
        print(f"[hitl] → Reply 'yes' to approve or 'no' to reject in Slack thread")
        return msg_ts
    except SlackApiError as e:
        print(f"[hitl] Slack post failed: {e.response['error']}")
        return ""


async def _poll_for_reply_async(message_ts: str) -> str:
    """
    Async version of reply polling — uses await asyncio.sleep so the event loop
    is not blocked while waiting for the Slack thread reply.
    Returns HITLDecision enum value or 'poll_error'.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_CHANNEL_ID", "")
    client = WebClient(token=token)

    start = time.time()
    print(f"[hitl] Waiting for Slack thread reply (timeout={REPLY_TIMEOUT}s)...")

    while time.time() - start < REPLY_TIMEOUT:
        try:
            result = client.conversations_replies(
                channel=channel,
                ts=message_ts,
                limit=10
            )
            messages = result.get("messages", [])

            # Skip the first message (that's our original post)
            replies = messages[1:] if len(messages) > 1 else []

            for reply in replies:
                text = reply.get("text", "").strip().lower()

                # Check if reply is an approve word
                if any(word in text for word in APPROVE_WORDS):
                    user = reply.get("user", "unknown")
                    _post_decision_reply(client, channel, message_ts,
                                        f"✅ *APPROVED* by <@{user}> — executing action now")
                    return HITLDecision.APPROVED

                # Check if reply is a reject word
                if any(word in text for word in REJECT_WORDS):
                    user = reply.get("user", "unknown")
                    _post_decision_reply(client, channel, message_ts,
                                        f"❌ *REJECTED* by <@{user}> — action skipped")
                    return HITLDecision.REJECTED

        except SlackApiError as e:
            error = e.response.get('error', '')
            if error == 'missing_scope':
                print(f"[hitl] Slack missing 'channels:history' scope — switching to web UI")
                return "poll_error"
            print(f"[hitl] Reply poll error: {error}")

        await asyncio.sleep(REPLY_POLL_INTERVAL)  # non-blocking sleep

    # Timeout — reject by default
    print(f"[hitl] Timeout after {REPLY_TIMEOUT}s — auto-rejecting")
    _post_decision_reply(client, channel, message_ts,
                         "⏰ *TIMEOUT* — no reply received, action skipped for safety")
    return HITLDecision.REJECTED


def _post_decision_reply(client: WebClient, channel: str, ts: str, status: str):
    """Posts the decision as a reply in the Slack thread."""
    try:
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f"{status}\n_Decision recorded by K8sWhisperer_"
        )
    except Exception:
        pass
