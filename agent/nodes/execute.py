"""
Execute Node — runs the approved kubectl action and verifies resolution with backoff polling.
"""
import asyncio
import json
import os
from agent.state import ClusterState
from agent.models import RemediationPlan, AnomalyType
from mcp.kubectl_client import (
    delete_pod, describe_pod, get_pod_status,
    patch_pod_resources, rollout_restart
)


VERIFY_BACKOFF = [5, 10, 20, 30, 30]   # seconds between verify polls, max 95s total


async def execute_node(state: ClusterState) -> ClusterState:
    """
    Executes state.plan action via kubectl.
    Polls pod state with exponential backoff to verify resolution.
    """
    plan: RemediationPlan = state["plan"]
    if not plan:
        return {**state, "result": "No plan to execute", "execution_success": False}

    pod_name = plan.target_resource.split("/")[-1]
    namespace = plan.namespace
    result = ""
    route = "auto_execute"  # Track route for explain_node audit
    success = False

    # ── Execute the action ──────────────────────────────────────
    if plan.action == "restart_pod":
        result = delete_pod(pod_name=pod_name, namespace=namespace)

    elif plan.action == "patch_memory":
        factor = plan.params.get("memory_factor", 1.5)
        # Get current memory limit first
        desc_out = describe_pod(pod_name=pod_name, namespace=namespace)
        current_mi = _parse_memory_from_describe(desc_out)
        new_mi = int(current_mi * factor)
        deployment_name = _pod_to_deployment(pod_name)
        result = patch_pod_resources(
            deployment_name=deployment_name,
            namespace=namespace,
            memory_limit=f"{new_mi}Mi"
        )
        # Restart pod to pick up new limits
        delete_pod(pod_name=pod_name, namespace=namespace)

    elif plan.action == "delete_evicted_pod":
        result = delete_pod(pod_name=pod_name, namespace=namespace)

    elif plan.action in ("recommend", "alert_only"):
        result = f"No automated action taken. Recommendation: {plan.reasoning}"
        return {**state, "result": result, "execution_success": True, "route": "auto_execute"}

    elif plan.action == "patch_cpu":
        deployment_name = _pod_to_deployment(pod_name)
        new_cpu = plan.params.get("cpu_limit", "500m")
        result = patch_pod_resources(
            deployment_name=deployment_name,
            namespace=namespace,
            cpu_limit=new_cpu
        )

    elif plan.action == "rollout_restart":
        deployment_name = _pod_to_deployment(pod_name)
        result = rollout_restart(
            deployment_name=deployment_name,
            namespace=namespace
        )

    else:
        result = f"Unknown action: {plan.action}"
        return {**state, "result": result, "execution_success": False, "route": "auto_execute"}

    # ── Verify with backoff ─────────────────────────────────────
    for wait_s in VERIFY_BACKOFF:
        await asyncio.sleep(wait_s)
        status = get_pod_status(pod_name=pod_name, namespace=namespace)
        try:
            phase = status.get("phase", "Unknown")
            if phase == "Running":
                result += f"\n✓ Pod verified Running after {sum(VERIFY_BACKOFF[:VERIFY_BACKOFF.index(wait_s)+1])}s"
                success = True
                break
            elif phase in ("Failed", "Unknown"):
                result += f"\n✗ Pod in {phase} state after action"
                break
            # else Pending/ContainerCreating — keep polling
        except Exception:
            pass

    if not success and "✓" not in result:
        result += "\n⚠ Pod not yet Running after 95s — may still be starting"

    return {**state, "result": result, "execution_success": success, "route": route}


def _pod_to_deployment(pod_name: str) -> str:
    """Heuristic: strip pod hash suffix to get deployment name.
    e.g. 'my-app-7d9f8b-xkc2p' → 'my-app'
    """
    parts = pod_name.rsplit("-", 2)
    return parts[0] if len(parts) >= 3 else pod_name


def _parse_memory_from_describe(describe_output: str) -> int:
    """Extract memory limit in Mi from kubectl describe output. Returns 256 as default."""
    for line in describe_output.split("\n"):
        if "memory:" in line.lower() and "Limits" in describe_output:
            parts = line.strip().split()
            for p in parts:
                if p.endswith("Mi"):
                    return int(p[:-2])
                elif p.endswith("Gi"):
                    return int(p[:-2]) * 1024
    return 256  # safe default
