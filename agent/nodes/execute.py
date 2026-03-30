"""
Execute Node — runs the approved kubectl action and verifies resolution with backoff polling.
"""
import asyncio
import json
import os
import subprocess
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
    route = state.get("route", "auto_execute")  # preserve the route from safety_gate
    success = False

    # ── Execute the action ──────────────────────────────────────
    if plan.action == "restart_pod":
        result = delete_pod(pod_name=pod_name, namespace=namespace)

    elif plan.action == "patch_memory":
        deployment_name = _pod_to_deployment(pod_name)

        # Smart OOM fix: use absolute limit if available, else use factor
        if plan.params.get("memory_limit_mi"):
            new_mi = int(plan.params["memory_limit_mi"])
            print(f"[execute] Smart patch: setting memory to {new_mi}Mi (absolute)")
        else:
            factor = plan.params.get("memory_factor", 1.5)
            current_mi = _get_current_memory_mi(deployment_name, namespace)
            new_mi = int(current_mi * factor)
            print(f"[execute] Factor patch: {current_mi}Mi × {factor} = {new_mi}Mi")

        result = patch_pod_resources(
            deployment_name=deployment_name,
            namespace=namespace,
            memory_limit=f"{new_mi}Mi"
        )
        print(f"[execute] Patch result: {result}")
        # Delete old pod so new one picks up the new deployment spec
        delete_pod(pod_name=pod_name, namespace=namespace)

    elif plan.action == "delete_evicted_pod":
        result = delete_pod(pod_name=pod_name, namespace=namespace)

    elif plan.action in ("recommend", "alert_only"):
        result = f"No automated action taken. Recommendation: {plan.reasoning}"
        return {**state, "result": result, "execution_success": True, "route": route}

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

    elif plan.action == "rollback_deployment":
        deployment_name = _pod_to_deployment(pod_name)
        result = _rollback_deployment(deployment_name, namespace)

    else:
        result = f"Unknown action: {plan.action}"
        return {**state, "result": result, "execution_success": False, "route": route}

    # ── Verify with backoff ─────────────────────────────────────
    deployment_actions = {"patch_memory", "patch_cpu", "rollout_restart", "rollback_deployment"}
    is_dep_action = plan.action in deployment_actions

    for wait_s in VERIFY_BACKOFF:
        await asyncio.sleep(wait_s)
        try:
            if is_dep_action:
                dep_name = _pod_to_deployment(pod_name)
                dep_info = _get_deployment_replicas(dep_name, namespace)
                desired = dep_info.get("desired", 0)
                ready = dep_info.get("ready", 0)
                if desired > 0 and ready >= desired:
                    elapsed = sum(VERIFY_BACKOFF[:VERIFY_BACKOFF.index(wait_s)+1])
                    result += f"\n✓ Deployment {dep_name}: {ready}/{desired} replicas ready after {elapsed}s"
                    success = True
                    break
            else:
                status = get_pod_status(pod_name=pod_name, namespace=namespace)
                phase = status.get("phase", "Unknown")
                if phase == "Running":
                    elapsed = sum(VERIFY_BACKOFF[:VERIFY_BACKOFF.index(wait_s)+1])
                    result += f"\n✓ Pod verified Running after {elapsed}s"
                    success = True
                    break
                elif phase in ("Failed", "Unknown"):
                    result += f"\n✗ Pod in {phase} state after action"
                    break
        except Exception:
            pass

    if not success and "✓" not in result:
        if is_dep_action:
            result += "\n⚠ Deployment not fully ready after 95s — may still be rolling out"
        else:
            result += "\n⚠ Pod not yet Running after 95s — may still be starting"

    return {**state, "result": result, "execution_success": success, "route": route}


def _pod_to_deployment(pod_name: str) -> str:
    """Heuristic: strip pod hash suffix to get deployment name."""
    parts = pod_name.rsplit("-", 2)
    return parts[0] if len(parts) >= 3 else pod_name


def _get_current_memory_mi(deployment_name: str, namespace: str) -> int:
    """Get current memory limit from deployment spec via kubectl JSON."""
    try:
        cmd = ["kubectl", "-n", namespace, "get", "deployment", deployment_name, "-o", "json"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            deploy = json.loads(out.stdout)
            containers = deploy["spec"]["template"]["spec"]["containers"]
            limits = containers[0].get("resources", {}).get("limits", {})
            mem = limits.get("memory", "256Mi")
            if mem.endswith("Mi"):
                return int(mem[:-2])
            elif mem.endswith("Gi"):
                return int(mem[:-2]) * 1024
            elif mem.endswith("m"):
                return max(int(int(mem[:-1]) / 1000000), 1)
    except Exception as e:
        print(f"[execute] Could not parse memory from deployment: {e}")
    return 256  # safe default


def _rollback_deployment(deployment_name: str, namespace: str) -> str:
    """Roll back a Deployment to its previous revision using kubectl rollout undo."""
    import subprocess
    cmd = ["kubectl", "-n", namespace, "rollout", "undo", f"deployment/{deployment_name}"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return f"ERROR: {out.stderr.strip()}"
        return out.stdout.strip()
    except subprocess.TimeoutExpired:
        return "ERROR: rollback timed out"
    except Exception as e:
        return f"ERROR: {str(e)}"


def _get_deployment_replicas(deployment_name: str, namespace: str) -> dict:
    """Get desired and ready replica counts from a Deployment."""
    try:
        cmd = ["kubectl", "-n", namespace, "get", "deployment", deployment_name, "-o", "json"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            dep = json.loads(out.stdout)
            status = dep.get("status", {})
            spec = dep.get("spec", {})
            return {
                "desired": spec.get("replicas", 0),
                "ready": status.get("readyReplicas", 0),
            }
    except Exception as e:
        print(f"[execute] Could not get deployment replicas: {e}")
    return {"desired": 0, "ready": 0}

