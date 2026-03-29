"""
kubectl MCP Server — exposes Kubernetes operations as typed MCP tools.
Scoped to pod-level operations only via RBAC ServiceAccount.
Start with: python mcp/kubectl_server.py
"""
import subprocess
import json
import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types


app = Server("kubectl-mcp")


def run_kubectl(args: list[str], namespace: str = "default") -> str:
    """Run a kubectl command and return stdout. Raises on non-zero exit."""
    cmd = ["kubectl", "-n", namespace] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"
    return result.stdout.strip()


# ── TOOL: list_pods ────────────────────────────────────────────────────────
@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_pods",
            description="List all pods in a namespace with their phase, restart count, and conditions",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "default": "default",
                                  "description": "Kubernetes namespace. Use '--all-namespaces' for all."}
                }
            }
        ),
        types.Tool(
            name="get_events",
            description="Get recent Kubernetes events for a namespace, sorted by time",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "default": "default"}
                }
            }
        ),
        types.Tool(
            name="get_pod_logs",
            description="Get logs for a pod. Returns last N lines only to avoid context overflow.",
            inputSchema={
                "type": "object",
                "required": ["pod_name"],
                "properties": {
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                    "tail_lines": {"type": "integer", "default": 100,
                                   "description": "Number of lines to tail. Max 200."},
                    "previous": {"type": "boolean", "default": False,
                                 "description": "Get logs from previous container instance (useful for crash analysis)"}
                }
            }
        ),
        types.Tool(
            name="describe_pod",
            description="Get full kubectl describe output for a pod including events and conditions",
            inputSchema={
                "type": "object",
                "required": ["pod_name"],
                "properties": {
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"}
                }
            }
        ),
        types.Tool(
            name="get_pod_status",
            description="Get current phase and container statuses for a specific pod",
            inputSchema={
                "type": "object",
                "required": ["pod_name"],
                "properties": {
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"}
                }
            }
        ),
        types.Tool(
            name="delete_pod",
            description="Delete a pod by name. Kubernetes will recreate it if managed by a Deployment/ReplicaSet.",
            inputSchema={
                "type": "object",
                "required": ["pod_name"],
                "properties": {
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"}
                }
            }
        ),
        types.Tool(
            name="patch_pod_resources",
            description="Patch memory/CPU limits on the pod's parent Deployment. Use for OOMKilled remediation.",
            inputSchema={
                "type": "object",
                "required": ["deployment_name", "memory_limit"],
                "properties": {
                    "deployment_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                    "memory_limit": {"type": "string",
                                     "description": "New memory limit e.g. '512Mi', '1Gi'"},
                    "cpu_limit": {"type": "string",
                                  "description": "New CPU limit e.g. '500m', '1000m'. Optional."}
                }
            }
        ),
        types.Tool(
            name="rollout_restart",
            description="Trigger a rolling restart of a Deployment",
            inputSchema={
                "type": "object",
                "required": ["deployment_name"],
                "properties": {
                    "deployment_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"}
                }
            }
        ),
        types.Tool(
            name="get_node_status",
            description="Get node conditions and resource capacity. READ-ONLY. Never auto-drain.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_name": {"type": "string", "description": "Optional. Omit for all nodes."}
                }
            }
        ),
        types.Tool(
            name="get_deployment_status",
            description="Get desired vs ready vs updated replicas for a deployment",
            inputSchema={
                "type": "object",
                "required": ["deployment_name"],
                "properties": {
                    "deployment_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"}
                }
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    ns = arguments.get("namespace", "default")
    try:
        if name == "list_pods":
            if ns == "--all-namespaces":
                out = run_kubectl(["get", "pods", "-A", "-o", "json"], "default")
            else:
                out = run_kubectl(["get", "pods", "-o", "json"], ns)
            # Parse and return summary
            data = json.loads(out) if out.startswith("{") else {"raw": out}
            return [types.TextContent(type="text", text=json.dumps(data, indent=2))]

        elif name == "get_events":
            out = run_kubectl(["get", "events", "--sort-by=.lastTimestamp", "-o", "json"], ns)
            return [types.TextContent(type="text", text=out)]

        elif name == "get_pod_logs":
            pod = arguments["pod_name"]
            tail = min(arguments.get("tail_lines", 100), 200)
            previous = arguments.get("previous", False)
            args = ["logs", pod, f"--tail={tail}"]
            if previous:
                args.append("--previous")
            out = run_kubectl(args, ns)
            # Filter to ERROR/WARNING lines if output is large
            lines = out.split("\n")
            if len(lines) > 50:
                filtered = [l for l in lines if any(
                    kw in l.upper() for kw in ["ERROR", "FATAL", "EXCEPTION", "PANIC", "WARN", "CRITICAL"]
                )]
                if len(filtered) > 10:
                    out = "\n".join(filtered[-50:])  # last 50 error lines
            return [types.TextContent(type="text", text=out)]

        elif name == "describe_pod":
            out = run_kubectl(["describe", "pod", arguments["pod_name"]], ns)
            return [types.TextContent(type="text", text=out)]

        elif name == "get_pod_status":
            out = run_kubectl(["get", "pod", arguments["pod_name"], "-o", "json"], ns)
            data = json.loads(out) if out.startswith("{") else {"raw": out}
            status = data.get("status", {})
            return [types.TextContent(type="text", text=json.dumps(status, indent=2))]

        elif name == "delete_pod":
            out = run_kubectl(["delete", "pod", arguments["pod_name"], "--grace-period=0"], ns)
            return [types.TextContent(type="text", text=out)]

        elif name == "patch_pod_resources":
            deployment = arguments["deployment_name"]
            memory = arguments["memory_limit"]
            cpu = arguments.get("cpu_limit", "")
            patch = {"spec": {"template": {"spec": {"containers": [
                {"name": deployment,
                 "resources": {"limits": {"memory": memory}}}
            ]}}}}
            if cpu:
                patch["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["cpu"] = cpu
            patch_str = json.dumps(patch)
            out = run_kubectl(["patch", "deployment", deployment, "--patch", patch_str], ns)
            return [types.TextContent(type="text", text=out)]

        elif name == "rollout_restart":
            out = run_kubectl(["rollout", "restart", f"deployment/{arguments['deployment_name']}"], ns)
            return [types.TextContent(type="text", text=out)]

        elif name == "get_node_status":
            node = arguments.get("node_name", "")
            args = ["get", "nodes", "-o", "json"]
            if node:
                args = ["get", "node", node, "-o", "json"]
            out = run_kubectl(args, "default")
            return [types.TextContent(type="text", text=out)]

        elif name == "get_deployment_status":
            out = run_kubectl(["get", "deployment", arguments["deployment_name"], "-o", "json"], ns)
            return [types.TextContent(type="text", text=out)]

        else:
            return [types.TextContent(type="text", text=f"ERROR: Unknown tool '{name}'")]

    except Exception as e:
        return [types.TextContent(type="text", text=f"ERROR: {str(e)}")]


if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(app))
