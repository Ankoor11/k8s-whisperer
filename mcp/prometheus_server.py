"""
Prometheus MCP Server — exposes metric queries as MCP tools.
Bonus component for CPU throttling detection (+5 marks).
Start with: python mcp/prometheus_server.py
"""
import os
import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types


PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
app = Server("prometheus-mcp")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="query_metric",
            description="Query a Prometheus metric using PromQL. Returns current scalar or vector value.",
            inputSchema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string",
                              "description": "PromQL query string e.g. 'rate(container_cpu_cfs_throttled_seconds_total[5m])'"},
                    "pod": {"type": "string", "description": "Optional pod name to filter"},
                    "namespace": {"type": "string", "default": "default"}
                }
            }
        ),
        types.Tool(
            name="check_cpu_throttling",
            description="Check if any pods have CPU throttling > 50%. Returns list of affected pods.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "default": "default"},
                    "threshold": {"type": "number", "default": 0.5,
                                  "description": "Throttle ratio threshold (0.0-1.0)"}
                }
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "query_metric":
            query = arguments["query"]
            resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                                params={"query": query}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return [types.TextContent(type="text", text=str(data.get("data", {}).get("result", [])))]

        elif name == "check_cpu_throttling":
            namespace = arguments.get("namespace", "default")
            threshold = arguments.get("threshold", 0.5)
            query = (
                f'rate(container_cpu_cfs_throttled_seconds_total{{namespace="{namespace}"}}[5m]) / '
                f'rate(container_cpu_cfs_periods_total{{namespace="{namespace}"}}[5m]) > {threshold}'
            )
            resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                                params={"query": query}, timeout=10)
            resp.raise_for_status()
            results = resp.json().get("data", {}).get("result", [])
            throttled_pods = [
                {"pod": r["metric"].get("pod"), "ratio": float(r["value"][1])}
                for r in results
            ]
            return [types.TextContent(type="text", text=str(throttled_pods))]

    except Exception as e:
        return [types.TextContent(type="text", text=f"ERROR: {str(e)}")]


if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(app))
