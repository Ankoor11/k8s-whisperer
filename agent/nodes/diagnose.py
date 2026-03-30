"""
Diagnose Node — fetches real kubectl output for the affected pod and synthesises root cause.
Uses chunked log strategy to avoid LLM context overflow.
"""
import json
import os
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm_helper import get_llm, invoke_with_retry
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

    # Sort by severity: CRITICAL > HIGH > MEDIUM > LOW → process highest first
    severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    sorted_anomalies = sorted(
        state["anomalies"],
        key=lambda a: severity_rank.get(a.severity.value, 0),
        reverse=True
    )
    anomaly: Anomaly = sorted_anomalies[0]
    print(f"[diagnose] Processing highest severity anomaly: {anomaly.type.value} ({anomaly.severity.value}) on {anomaly.affected_resource}")
    pod_name = anomaly.affected_resource.split("/")[-1]
    namespace = anomaly.namespace

    # Fetch current logs
    raw_logs = get_pod_logs(pod_name=pod_name, namespace=namespace,
                            tail_lines=100, previous=False)

    # Also fetch previous container logs for crash analysis
    if anomaly.type.value in ["CrashLoopBackOff", "OOMKilled"]:
        prev_logs = get_pod_logs(pod_name=pod_name, namespace=namespace,
                                 tail_lines=50, previous=True)
        if prev_logs and not prev_logs.startswith("ERROR"):  # skip if kubectl returned an error
            raw_logs = f"=== Previous container logs ===\n{prev_logs}\n\n=== Current logs ===\n{raw_logs}"

    # Fetch describe
    raw_describe = describe_pod(pod_name=pod_name, namespace=namespace)

    # Truncate if still too large
    if len(raw_logs) > 3000:
        raw_logs = raw_logs[-3000:]
    if len(raw_describe) > 4000:
        raw_describe = raw_describe[-4000:]

    llm = get_llm()

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

    diagnosis = await invoke_with_retry(llm, messages, label="diagnose")

    return {
        **state,
        "current_anomaly": anomaly,
        "diagnosis": diagnosis,
        "raw_logs": raw_logs,
        "raw_describe": raw_describe,
    }
