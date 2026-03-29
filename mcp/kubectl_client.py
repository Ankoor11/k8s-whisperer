"""
kubectl helper — direct subprocess wrapper for kubectl commands.
Used by agent nodes when langchain-mcp-adapters is not available.
Falls back to direct kubectl calls rather than going through the MCP server.
"""
import subprocess
import json
import os
from typing import Optional


def run_kubectl(args: list, namespace: str = "default", timeout: int = 30) -> str:
    """Run a kubectl command and return stdout."""
    cmd = ["kubectl", "-n", namespace] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "ERROR: kubectl command timed out"
    except Exception as e:
        return f"ERROR: {str(e)}"


def list_pods(namespace: str = "default") -> dict:
    """List all pods in a namespace."""
    if namespace == "--all-namespaces":
        out = run_kubectl(["get", "pods", "-A", "-o", "json"], "default")
    else:
        out = run_kubectl(["get", "pods", "-o", "json"], namespace)
    try:
        return json.loads(out) if out.startswith("{") else {"raw": out}
    except json.JSONDecodeError:
        return {"raw": out}


def get_events(namespace: str = "default") -> dict:
    """Get recent events for a namespace."""
    out = run_kubectl(["get", "events", "--sort-by=.lastTimestamp", "-o", "json"], namespace)
    try:
        return json.loads(out) if out.startswith("{") else {"raw": out}
    except json.JSONDecodeError:
        return {"raw": out}


def get_pod_logs(pod_name: str, namespace: str = "default",
                 tail_lines: int = 100, previous: bool = False) -> str:
    """Get logs for a pod."""
    tail = min(tail_lines, 200)
    args = ["logs", pod_name, f"--tail={tail}"]
    if previous:
        args.append("--previous")
    out = run_kubectl(args, namespace)
    # Filter to ERROR/WARNING lines if output is large
    lines = out.split("\n")
    if len(lines) > 50:
        filtered = [l for l in lines if any(
            kw in l.upper() for kw in ["ERROR", "FATAL", "EXCEPTION", "PANIC", "WARN", "CRITICAL"]
        )]
        if len(filtered) > 10:
            out = "\n".join(filtered[-50:])
    return out


def describe_pod(pod_name: str, namespace: str = "default") -> str:
    """Get full kubectl describe output for a pod."""
    return run_kubectl(["describe", "pod", pod_name], namespace)


def get_pod_status(pod_name: str, namespace: str = "default") -> dict:
    """Get current phase and container statuses for a specific pod."""
    out = run_kubectl(["get", "pod", pod_name, "-o", "json"], namespace)
    try:
        data = json.loads(out) if out.startswith("{") else {"raw": out}
        return data.get("status", {})
    except json.JSONDecodeError:
        return {"raw": out}


def delete_pod(pod_name: str, namespace: str = "default") -> str:
    """Delete a pod by name."""
    return run_kubectl(["delete", "pod", pod_name, "--grace-period=0"], namespace)


def patch_pod_resources(deployment_name: str, namespace: str = "default",
                        memory_limit: str = "", cpu_limit: str = "") -> str:
    """Patch memory/CPU limits on the pod's parent Deployment."""
    patch = {"spec": {"template": {"spec": {"containers": [
        {"name": deployment_name,
         "resources": {"limits": {}}}
    ]}}}}
    if memory_limit:
        patch["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"] = memory_limit
    if cpu_limit:
        patch["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["cpu"] = cpu_limit
    patch_str = json.dumps(patch)
    return run_kubectl(["patch", "deployment", deployment_name, "--patch", patch_str], namespace)


def rollout_restart(deployment_name: str, namespace: str = "default") -> str:
    """Trigger a rolling restart of a Deployment."""
    return run_kubectl(["rollout", "restart", f"deployment/{deployment_name}"], namespace)


def get_node_status(node_name: Optional[str] = None) -> dict:
    """Get node conditions and resource capacity."""
    if node_name:
        args = ["get", "node", node_name, "-o", "json"]
    else:
        args = ["get", "nodes", "-o", "json"]
    out = run_kubectl(args, "default")
    try:
        return json.loads(out) if out.startswith("{") else {"raw": out}
    except json.JSONDecodeError:
        return {"raw": out}


def get_deployment_status(deployment_name: str, namespace: str = "default") -> dict:
    """Get deployment status."""
    out = run_kubectl(["get", "deployment", deployment_name, "-o", "json"], namespace)
    try:
        return json.loads(out) if out.startswith("{") else {"raw": out}
    except json.JSONDecodeError:
        return {"raw": out}
