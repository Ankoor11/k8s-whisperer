"""
Detect Node — deterministic pre-filter + LLM classifier.
Pre-filter catches obvious anomalies without an API call.
LLM is only called when suspicious pods are found.
"""
import json
import os
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm_helper import get_llm, invoke_with_retry
from agent.state import ClusterState
from agent.models import Anomaly, AnomalyType, Severity


# ── Deterministic pre-filter ────────────────────────────────────────
# These rules run in pure Python — ZERO API calls.
# Only pods that match are sent to the LLM for classification.

def _is_suspicious(event: dict) -> bool:
    """Returns True if a pod shows any anomaly signal worth classifying."""
    # Skip rolling updates
    if event.get("is_rolling_update"):
        return False

    phase = event.get("phase", "")
    restart_count = event.get("restart_count", 0)

    # High restart count → likely CrashLoopBackOff
    if restart_count >= 3:
        return True

    # Pending phase (stuck scheduling)
    if phase == "Pending":
        return True

    # Evicted pods
    if event.get("reason") == "Evicted":
        return True

    # Check container states for known bad signals
    for cs in event.get("container_states", []):
        state = cs.get("state", {})
        last_state = cs.get("last_state", {})

        # Waiting with bad reason
        waiting = state.get("waiting", {})
        if waiting:
            reason = waiting.get("reason", "")
            if reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
                          "CreateContainerConfigError", "RunContainerError"):
                return True

        # Terminated with OOMKilled
        terminated = state.get("terminated", {})
        if terminated.get("reason") == "OOMKilled":
            return True
        last_terminated = last_state.get("terminated", {})
        if last_terminated.get("reason") == "OOMKilled":
            return True

    return False


# ── LLM prompt (only used when suspicious pods exist) ───────────────
SYSTEM_PROMPT = """You are a Kubernetes anomaly detection classifier.

You receive a list of SUSPICIOUS pod events from a cluster. These pods have already been pre-filtered.
Your job is to classify each anomaly precisely and output a JSON array.

ANOMALY TYPES:
- CrashLoopBackOff: restartCount > 3 or waiting reason is CrashLoopBackOff
- OOMKilled: terminated reason is OOMKilled
- PendingPod: phase == Pending and appears stuck
- ImagePullBackOff: waiting reason is ImagePullBackOff or ErrImagePull
- EvictedPod: reason == Evicted

FALSE POSITIVES — DO NOT flag:
- Rolling update restarts (is_rolling_update=true)
- Pending for < 60 seconds (normal scheduling)
- Completed phase pods (finished Jobs)

OUTPUT FORMAT — return ONLY a valid JSON array, no markdown:
[
  {
    "type": "<AnomalyType>",
    "severity": "<CRITICAL|HIGH|MEDIUM|LOW>",
    "affected_resource": "<namespace/pod-name>",
    "namespace": "<namespace>",
    "confidence": <0.0-1.0>,
    "trigger_signal": "<exact signal>",
    "is_rolling_update": false
  }
]

If none qualify after analysis, return: []
"""


async def detect_node(state: ClusterState) -> ClusterState:
    """
    Two-stage detection:
    1. Deterministic pre-filter (zero API calls) — finds suspicious pods
    2. LLM classifier (1 API call) — only runs if pre-filter finds something
    """
    if not state["events"]:
        print("[detect] No events to analyze.")
        return {**state, "anomalies": []}

    # Filter out pods already being processed (cooldown)
    # Checks both exact pod name AND deployment prefix
    active = state.get("active_incident_pods", set())
    events_to_check = []
    for e in state["events"]:
        pod_key = f"{e['namespace']}/{e['pod_name']}"
        # Check exact match
        if pod_key in active:
            continue
        # Check deployment prefix match (e.g. "default/oom-test" matches "default/oom-test-xxx-yyy")
        dep_parts = e['pod_name'].rsplit("-", 2)
        if len(dep_parts) >= 3:
            dep_prefix = f"{e['namespace']}/{dep_parts[0]}"
            if dep_prefix in active:
                continue
        events_to_check.append(e)

    if not events_to_check:
        print("[detect] All pods in cooldown — skipping.")
        return {**state, "anomalies": []}

    # ── Stage 1: Deterministic pre-filter (FREE) ────────────────────
    suspicious = [e for e in events_to_check if _is_suspicious(e)]

    if not suspicious:
        print(f"[detect] Pre-filter: {len(events_to_check)} pods checked, all healthy. (0 API calls)")
        return {**state, "anomalies": []}

    print(f"[detect] Pre-filter: {len(suspicious)}/{len(events_to_check)} pods suspicious → calling LLM...")

    # ── Stage 2: LLM classification (1 API call) ────────────────────
    llm = get_llm()

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Suspicious pods to classify:\n{json.dumps(suspicious, indent=2)}")
    ]

    raw = await invoke_with_retry(llm, messages, label="detect")
    print(f"[detect] LLM response: {raw[:200]}...")

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:].lstrip()  # strip "json" + any leading newline/whitespace

    try:
        anomaly_dicts = json.loads(raw)
        anomalies = [Anomaly(**a) for a in anomaly_dicts]
    except Exception as e:
        print(f"[detect] Failed to parse LLM output: {e}\nRaw: {raw}")
        anomalies = []

    return {**state, "anomalies": anomalies}
