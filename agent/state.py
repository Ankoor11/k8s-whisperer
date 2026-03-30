from typing import TypedDict, Optional
from agent.models import Anomaly, RemediationPlan, LogEntry, HITLDecision
import uuid


class ClusterState(TypedDict):
    # ── Observe ──────────────────────────────────────────────────────
    events: list[dict]              # raw kubectl events from current cycle
    cluster_snapshot: dict          # pods, nodes, deployments summary

    # ── Detect ───────────────────────────────────────────────────────
    anomalies: list[Anomaly]        # detected anomalies this cycle

    # ── Diagnose ─────────────────────────────────────────────────────
    current_anomaly: Optional[Anomaly]   # anomaly being actively processed
    diagnosis: str                       # LLM root cause string with evidence
    raw_logs: str                        # chunked log output for diagnosis
    raw_describe: str                    # kubectl describe output

    # ── Plan ─────────────────────────────────────────────────────────
    plan: Optional[RemediationPlan]

    # ── Safety Gate ──────────────────────────────────────────────────
    route: str                      # "auto_execute" | "hitl" | "skip"

    # ── HITL ─────────────────────────────────────────────────────────
    hitl_decision: HITLDecision
    hitl_thread_id: str             # LangGraph thread ID for resume
    slack_message_ts: str           # Slack message timestamp for updates

    # ── Execute ──────────────────────────────────────────────────────
    result: str                     # kubectl output + post-action pod state
    execution_success: bool

    # ── Explain ──────────────────────────────────────────────────────
    explanation: str                # plain English summary

    # ── Persistent ───────────────────────────────────────────────────
    audit_log: list[LogEntry]       # grows across all cycles
    active_incident_pods: list      # mutex: pods currently being processed (serializable list)
    incident_id: str                # uuid for current incident


def initial_state() -> ClusterState:
    return ClusterState(
        events=[],
        cluster_snapshot={},
        anomalies=[],
        current_anomaly=None,
        diagnosis="",
        raw_logs="",
        raw_describe="",
        plan=None,
        route="",
        hitl_decision=HITLDecision.PENDING,
        hitl_thread_id="",
        slack_message_ts="",
        result="",
        execution_success=False,
        explanation="",
        audit_log=[],
        active_incident_pods=[],
        incident_id=str(uuid.uuid4()),
    )
