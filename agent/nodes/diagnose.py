"""
Diagnose Node — fetches real kubectl output for the affected pod and synthesises root cause.
Uses chunked log strategy to avoid LLM context overflow.
"""
import json
import os
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from agent.state import ClusterState
from agent.models import Anomaly
from mcp.kubectl_client import get_pod_logs, describe_pod


DIAGNOSIS_PROMPT = """You are a senior Kubernetes SRE performing root cause analysis.

You are given:
1. The anomaly type and trigger signal
2. Recent pod logs (error lines only)
3. kubectl describe output for the pod

Your task: Write a concise root cause diagnosis with evidence.

FORMAT your response as plain text (no JSON, no markdown):
- Start with: "Root cause: [one sentence summary]"
- Then: "Evidence: [cite specific log lines, events, or conditions that prove your diagnosis]"
- Then: "Impact: [what is currently broken for end users]"

Be specific. Quote actual log messages or event reasons. Do not speculate beyond the evidence.
If the logs are empty, say so and diagnose from the describe output only.
"""


async def diagnose_node(state: ClusterState) -> ClusterState:
    """
    Takes the first unprocessed anomaly from state.anomalies.
    Fetches logs and describe. Runs LLM synthesis.
    """
    if not state["anomalies"]:
        return {**state, "diagnosis": "", "current_anomaly": None}

    anomaly: Anomaly = state["anomalies"][0]
    pod_name = anomaly.affected_resource.split("/")[-1]
    namespace = anomaly.namespace

    # Fetch current logs
    raw_logs = get_pod_logs(pod_name=pod_name, namespace=namespace,
                            tail_lines=100, previous=False)

    # Also fetch previous container logs for crash analysis
    if anomaly.type.value in ["CrashLoopBackOff", "OOMKilled"]:
        prev_logs = get_pod_logs(pod_name=pod_name, namespace=namespace,
                                 tail_lines=50, previous=True)
        if prev_logs and "ERROR" not in prev_logs[:5]:
            raw_logs = f"=== Previous container logs ===\n{prev_logs}\n\n=== Current logs ===\n{raw_logs}"

    # Fetch describe
    raw_describe = describe_pod(pod_name=pod_name, namespace=namespace)

    # Truncate if still too large
    if len(raw_logs) > 3000:
        raw_logs = raw_logs[-3000:]
    if len(raw_describe) > 4000:
        raw_describe = raw_describe[-4000:]

    llm = ChatGroq(model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))

    context = f"""Anomaly type: {anomaly.type.value}
Severity: {anomaly.severity.value}
Affected pod: {anomaly.affected_resource}
Trigger signal: {anomaly.trigger_signal}

=== POD LOGS (error lines, last 100 lines) ===
{raw_logs or "(no logs available)"}

=== KUBECTL DESCRIBE OUTPUT ===
{raw_describe or "(no describe output available)"}
"""

    messages = [
        SystemMessage(content=DIAGNOSIS_PROMPT),
        HumanMessage(content=context)
    ]

    response = await llm.ainvoke(messages)
    diagnosis = response.content.strip()

    return {
        **state,
        "current_anomaly": anomaly,
        "diagnosis": diagnosis,
        "raw_logs": raw_logs,
        "raw_describe": raw_describe,
    }
