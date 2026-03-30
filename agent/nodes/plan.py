"""
Plan Node — proposes a RemediationPlan based on diagnosis and anomaly type.
DESTRUCTIVE_ACTIONS is hardcoded here — never LLM-controlled.
Includes escalation logic: restart → patch_memory → HITL.
"""
import json
import os
import re
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm_helper import get_llm, invoke_with_retry
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
    AnomalyType.CRASH_LOOP_BACK_OFF: BlastRadius.LOW,
    AnomalyType.OOM_KILLED: BlastRadius.MEDIUM,
    AnomalyType.EVICTED_POD: BlastRadius.LOW,
    AnomalyType.IMAGE_PULL_BACK_OFF: BlastRadius.LOW,
    AnomalyType.PENDING_POD: BlastRadius.MEDIUM,
    AnomalyType.CPU_THROTTLING: BlastRadius.MEDIUM,
    AnomalyType.DEPLOYMENT_STALLED: BlastRadius.HIGH,
    AnomalyType.NODE_NOT_READY: BlastRadius.HIGH,
}

PLAN_PROMPT = """You are a Kubernetes remediation planner.

Given an anomaly type, diagnosis, and affected resource, propose a remediation action.

AVAILABLE ACTIONS (only suggest from this list):
- restart_pod: Delete the pod so Kubernetes recreates it. For CrashLoopBackOff on Deployment-managed pods.
- patch_memory: Patch the parent Deployment to increase memory limits by 50%. For OOMKilled. ONLY use if the pod is owned by a Deployment.
- patch_cpu: Patch the parent Deployment to increase CPU limits. For CPU throttling. ONLY use if the pod is owned by a Deployment.
- delete_evicted_pod: Delete an evicted pod. For Evicted status.
- rollout_restart: Trigger rolling restart of Deployment. For DeploymentStalled (only with HITL).
- rollback_deployment: Roll back to previous revision. For DeploymentStalled (only with HITL).
- recommend: No automated action — explain to engineer what to do. For Pending, ImagePullBackOff, or bare Pods without a parent Deployment.
- alert_only: Post alert, no action. For Node NotReady.

IMPORTANT RULES:
- If is_bare_pod is true (no parent Deployment), NEVER use patch_memory or patch_cpu — use restart_pod or recommend instead.
- CrashLoopBackOff on a bare Pod → use restart_pod (not patch_memory).

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

AUDIT_LOG_PATH = Path("audit_log.json")


def _count_previous_actions(pod_prefix: str) -> dict:
    """Count how many times each action was tried on this pod/deployment."""
    counts = {"restart_pod": 0, "patch_memory": 0, "total": 0}
    if not AUDIT_LOG_PATH.exists():
        return counts
    try:
        log = json.loads(AUDIT_LOG_PATH.read_text())
        for entry in log:
            # Match by deployment prefix (e.g. "default/oom-test" matches "default/oom-test-xxx-yyy")
            if entry.get("affected_resource", "").startswith(pod_prefix):
                action = entry.get("plan_action", "")
                counts[action] = counts.get(action, 0) + 1
                counts["total"] += 1
    except Exception:
        pass
    return counts


def _get_deployment_prefix(affected_resource: str) -> str:
    """Extract deployment prefix from pod name. e.g. 'default/oom-test-7d9-xkc' → 'default/oom-test'"""
    parts = affected_resource.rsplit("-", 2)
    return parts[0] if len(parts) >= 3 else affected_resource


def _is_bare_pod(affected_resource: str) -> bool:
    """Returns True if the pod appears to be a bare Pod (not owned by a Deployment/ReplicaSet).
    Deployment pods have a pattern like 'name-<replicaset-hash>-<pod-hash>'.
    Bare pods like 'crashloop-test' have no double-hash suffix."""
    pod_name = affected_resource.split("/")[-1]
    parts = pod_name.rsplit("-", 2)
    if len(parts) < 3:
        return True  # No double-hash suffix → likely bare pod
    # Check if last two segments look like k8s hashes (5-10 alphanumeric chars)
    for seg in parts[1:]:
        if not (3 <= len(seg) <= 10 and seg.isalnum()):
            return True
    return False


def _parse_memory_need_from_diagnosis(diagnosis: str) -> int:
    """Extract memory requirement from diagnosis text. Returns memory in Mi with 25% headroom."""
    # Try multiple patterns to find the memory need
    patterns = [
        r'--vm-bytes\s+(\d+)\s*[Mm]',              # --vm-bytes 200M
        r'allocat\w*\s+(\d+)\s*[Mm]',               # allocating 200M
        r'(\d+)\s*[Mm]\s+of\s+(?:virtual\s+)?memory', # 200M of memory
        r'(\d+)\s*[Mm](?:i?[Bb])?\s+memory',         # 200MB memory / 200Mi memory
        r'exceeds?\s+.*?(\d+)\s*[Mm]i',              # exceeds the 32Mi limit (gets the limit)
    ]
    
    largest = 0
    for pattern in patterns:
        matches = re.findall(pattern, diagnosis, re.IGNORECASE)
        for m in matches:
            val = int(m)
            if val > largest:
                largest = val
    
    if largest > 0:
        return int(largest * 1.25)  # 25% headroom
    return 0


async def plan_node(state: ClusterState) -> ClusterState:
    if not state["current_anomaly"]:
        return {**state, "plan": None}

    anomaly: Anomaly = state["current_anomaly"]
    
    # ── Escalation logic ────────────────────────────────────────────
    pod_prefix = _get_deployment_prefix(anomaly.affected_resource)
    prev_actions = _count_previous_actions(pod_prefix)
    
    if prev_actions["total"] >= 4:
        print(f"[plan] ESCALATION: {prev_actions['total']} previous attempts on {pod_prefix} → routing to HITL")
        plan = RemediationPlan(
            action="recommend",
            target_resource=anomaly.affected_resource,
            namespace=anomaly.namespace,
            params={},
            confidence=0.5,
            blast_radius=BlastRadius.HIGH,
            reasoning=f"Automated fixes exhausted ({prev_actions['total']} attempts). Escalating to human."
        )
        return {**state, "plan": plan}

    # Detect if this is a bare pod (no parent Deployment)
    bare_pod = _is_bare_pod(anomaly.affected_resource)
    if bare_pod:
        print(f"[plan] Detected bare Pod (no Deployment parent): {anomaly.affected_resource}")

    llm = get_llm()

    context = f"""Anomaly: {anomaly.type.value}
Affected resource: {anomaly.affected_resource}
Namespace: {anomaly.namespace}
is_bare_pod: {bare_pod}  (if true, the pod has NO parent Deployment — do NOT use patch_memory or patch_cpu)
Previous attempts on this resource: {json.dumps(prev_actions)}
Diagnosis:
{state["diagnosis"]}
"""

    messages = [
        SystemMessage(content=PLAN_PROMPT),
        HumanMessage(content=context)
    ]

    raw = await invoke_with_retry(llm, messages, label="plan")

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:].lstrip()  # strip "json" + any leading newline/whitespace

    try:
        plan_dict = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[plan] Failed to parse LLM output: {e}\nRaw: {raw[:200]}")
        plan = RemediationPlan(
            action="recommend",
            target_resource=anomaly.affected_resource,
            namespace=anomaly.namespace,
            params={},
            confidence=0.0,
            blast_radius=BlastRadius.HIGH,
            reasoning="LLM output could not be parsed — escalating to human review."
        )
        return {**state, "plan": plan}

    # Enforce blast_radius deterministically
    blast_radius = BLAST_RADIUS_MAP.get(anomaly.type, BlastRadius.HIGH)
    plan_dict["blast_radius"] = blast_radius.value

    # Reject destructive actions
    if plan_dict.get("action") in DESTRUCTIVE_ACTIONS:
        plan_dict["action"] = "recommend"
        plan_dict["confidence"] = 0.0
        plan_dict["reasoning"] = f"Action was in DESTRUCTIVE_ACTIONS list — downgraded to recommend."

    # ── Smarter OOM fix ─────────────────────────────────────────────
    if anomaly.type == AnomalyType.OOM_KILLED and plan_dict["action"] == "patch_memory":
        smart_limit = _parse_memory_need_from_diagnosis(state.get("diagnosis", ""))
        if smart_limit > 0:
            plan_dict["params"]["memory_limit_mi"] = smart_limit
            plan_dict["params"]["memory_factor"] = 1.0  # use absolute value instead
            print(f"[plan] Smart OOM fix: setting memory to {smart_limit}Mi (parsed from diagnosis)")
        else:
            plan_dict["params"]["memory_factor"] = 1.5

    # ── Bare pod guard: never patch_memory/patch_cpu on a bare pod ───────
    if bare_pod and plan_dict.get("action") in ("patch_memory", "patch_cpu"):
        if anomaly.type.value == "CrashLoopBackOff":
            plan_dict["action"] = "restart_pod"
            plan_dict["reasoning"] += " [GUARDED: bare pod has no Deployment — downgraded to restart_pod]"
            print(f"[plan] GUARD: bare pod + patch action → restart_pod")
        else:
            plan_dict["action"] = "recommend"
            plan_dict["confidence"] = 0.5
            plan_dict["reasoning"] += " [GUARDED: bare pod has no Deployment — downgraded to recommend]"
            print(f"[plan] GUARD: bare pod + patch action → recommend")

    # ── Escalation: if restart already tried on a DEPLOYMENT pod, escalate to patch_memory
    if (plan_dict["action"] == "restart_pod" and 
        not bare_pod and
        anomaly.type.value in ["CrashLoopBackOff", "OOMKilled"] and
        prev_actions.get("restart_pod", 0) >= 1):
        plan_dict["action"] = "patch_memory"
        plan_dict["params"]["memory_factor"] = 2.0
        plan_dict["reasoning"] += " [ESCALATED: restart already tried, upgrading to patch_memory]"
        print(f"[plan] ESCALATION: restart already tried → patch_memory (2x)")

    plan = RemediationPlan(**plan_dict)
    return {**state, "plan": plan}

