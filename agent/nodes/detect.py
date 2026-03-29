"""
Detect Node — LLM classifier that reads ClusterState.events and emits typed Anomaly objects.
Handles false-positive filtering for rolling update restarts.
"""
import json
import os
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from agent.state import ClusterState
from agent.models import Anomaly, AnomalyType, Severity


SYSTEM_PROMPT = """You are a Kubernetes anomaly detection classifier.

You receive a list of pod events from a cluster. Your job is to identify anomalies and output a JSON array.

ANOMALY DETECTION RULES:
- CrashLoopBackOff: restartCount > 3 (OR state is "waiting" with reason "CrashLoopBackOff")
- OOMKilled: lastState.terminated.reason == "OOMKilled"
- PendingPod: phase == "Pending" (only flag if it appears to be stuck, not a normal startup)
- ImagePullBackOff: container state waiting reason is "ImagePullBackOff" or "ErrImagePull"
- EvictedPod: pod.reason == "Evicted"
- DeploymentStalled: report via separate deployment check
- NodeNotReady: report via node status check

FALSE POSITIVE RULES — DO NOT flag these as anomalies:
- A pod restarting when is_rolling_update=true (it is intentional)
- A pod in "Pending" phase for less than 60 seconds (normal scheduling delay)
- "Completed" phase pods (Job pods that finished successfully)
- Init containers in "Init:" states (normal init sequence)

OUTPUT FORMAT — return ONLY a valid JSON array, no markdown, no explanation:
[
  {
    "type": "<AnomalyType>",
    "severity": "<CRITICAL|HIGH|MEDIUM|LOW>",
    "affected_resource": "<namespace/pod-name>",
    "namespace": "<namespace>",
    "confidence": <0.0-1.0>,
    "trigger_signal": "<exact signal that triggered detection>",
    "is_rolling_update": <true|false>
  }
]

If no anomalies are detected, return an empty array: []
"""


async def detect_node(state: ClusterState) -> ClusterState:
    """
    Runs LLM classifier over state.events.
    Skips pods in state.active_incident_pods (race condition guard).
    """
    if not state["events"]:
        return {**state, "anomalies": []}

    # Filter out pods already being processed
    active = state.get("active_incident_pods", set())
    events_to_check = [
        e for e in state["events"]
        if f"{e['namespace']}/{e['pod_name']}" not in active
    ]

    if not events_to_check:
        return {**state, "anomalies": []}

    llm = ChatGroq(model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Cluster events to analyse:\n{json.dumps(events_to_check, indent=2)}")
    ]

    print(f"[detect] Analyzing {len(events_to_check)} pods...")
    response = await llm.ainvoke(messages)
    raw = response.content.strip()
    print(f"[detect] LLM raw response: {raw}")


    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        anomaly_dicts = json.loads(raw)
        anomalies = [Anomaly(**a) for a in anomaly_dicts]
    except Exception as e:
        print(f"[detect] Failed to parse LLM output: {e}\nRaw: {raw}")
        anomalies = []

    return {**state, "anomalies": anomalies}
