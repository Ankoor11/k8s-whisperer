"""
Plan Node — proposes a RemediationPlan based on diagnosis and anomaly type.
DESTRUCTIVE_ACTIONS is hardcoded here — never LLM-controlled.
"""
import json
import os
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from agent.state import ClusterState
from agent.models import RemediationPlan, BlastRadius, Anomaly, AnomalyType


# HARDCODED — never modify based on LLM output
DESTRUCTIVE_ACTIONS = frozenset([
    "delete_namespace",
    "drain_node",
    "cordon_node",
    "delete_deployment",
    "delete_statefulset",
    "delete_pvc",
    "delete_configmap",
    "scale_to_zero",
    "force_delete_namespace",
])

# Blast radius rules — deterministic, not LLM-determined
BLAST_RADIUS_MAP = {
    AnomalyType.CRASH_LOOP_BACK_OFF: BlastRadius.LOW,    # restart pod only
    AnomalyType.OOM_KILLED: BlastRadius.MEDIUM,           # patch deployment memory
    AnomalyType.EVICTED_POD: BlastRadius.LOW,             # delete evicted pod
    AnomalyType.IMAGE_PULL_BACK_OFF: BlastRadius.LOW,     # alert only, no change
    AnomalyType.PENDING_POD: BlastRadius.MEDIUM,          # recommend only
    AnomalyType.CPU_THROTTLING: BlastRadius.MEDIUM,       # patch CPU limit
    AnomalyType.DEPLOYMENT_STALLED: BlastRadius.HIGH,     # rollback or force rollout
    AnomalyType.NODE_NOT_READY: BlastRadius.HIGH,         # HITL only, never auto
}

PLAN_PROMPT = """You are a Kubernetes remediation planner.

Given an anomaly type, diagnosis, and affected resource, propose a remediation action.

AVAILABLE ACTIONS (only suggest from this list):
- restart_pod: Delete the pod so Kubernetes recreates it. For CrashLoopBackOff.
- patch_memory: Patch the parent Deployment to increase memory limits by 50%. For OOMKilled.
- patch_cpu: Patch the parent Deployment to increase CPU limits. For CPU throttling.
- delete_evicted_pod: Delete an evicted pod. For Evicted status.
- rollout_restart: Trigger rolling restart of Deployment. For DeploymentStalled (only with HITL).
- rollback_deployment: Roll back to previous revision. For DeploymentStalled (only with HITL).
- recommend: No automated action — explain to engineer what to do. For Pending, ImagePullBackOff.
- alert_only: Post alert, no action. For Node NotReady.

NEVER suggest: delete_namespace, drain_node, cordon_node, delete_deployment, delete_pvc, scale_to_zero

OUTPUT — return ONLY valid JSON, no markdown:
{
  "action": "<action from list above>",
  "target_resource": "<namespace/resource-name>",
  "namespace": "<namespace>",
  "params": {},
  "confidence": <0.0-1.0>,
  "reasoning": "<why this action, citing evidence from diagnosis>"
}
"""


async def plan_node(state: ClusterState) -> ClusterState:
    if not state["current_anomaly"]:
        return {**state, "plan": None}

    anomaly: Anomaly = state["current_anomaly"]
    llm = ChatGroq(model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))

    context = f"""Anomaly: {anomaly.type.value}
Affected resource: {anomaly.affected_resource}
Namespace: {anomaly.namespace}
Diagnosis:
{state["diagnosis"]}
"""

    messages = [
        SystemMessage(content=PLAN_PROMPT),
        HumanMessage(content=context)
    ]

    response = await llm.ainvoke(messages)
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    plan_dict = json.loads(raw)

    # Enforce blast_radius deterministically — never trust LLM for safety classification
    blast_radius = BLAST_RADIUS_MAP.get(anomaly.type, BlastRadius.HIGH)
    plan_dict["blast_radius"] = blast_radius.value

    # Reject destructive actions outright
    if plan_dict.get("action") in DESTRUCTIVE_ACTIONS:
        plan_dict["action"] = "recommend"
        plan_dict["confidence"] = 0.0
        plan_dict["reasoning"] = f"Action was in DESTRUCTIVE_ACTIONS list — downgraded to recommend. Original: {plan_dict.get('action')}"

    # Add OOMKilled memory params
    if anomaly.type == AnomalyType.OOM_KILLED and plan_dict["action"] == "patch_memory":
        plan_dict["params"]["memory_factor"] = 1.5

    plan = RemediationPlan(**plan_dict)
    return {**state, "plan": plan}
