"""
K8sWhisperer LangGraph agent — main graph definition.
Assembles all 7 pipeline nodes with conditional edges and checkpointer.
"""
import asyncio
import os
import uuid
import time
from dotenv import load_dotenv

load_dotenv()  # Load .env file so GROQ_API_KEY and other vars are available
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agent.state import ClusterState, initial_state
from agent.nodes.observe import observe_node
from agent.nodes.detect import detect_node
from agent.nodes.diagnose import diagnose_node
from agent.nodes.plan import plan_node
from agent.nodes.safety_gate import safety_gate
from agent.nodes.execute import execute_node
from agent.nodes.hitl import hitl_node
from agent.nodes.explain import explain_node


POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
COOLDOWN_SECONDS = 300  # Skip pods processed in the last 5 minutes


# ── Graph definition ────────────────────────────────────────────────
builder = StateGraph(ClusterState)

builder.add_node("observe",   observe_node)
builder.add_node("detect",    detect_node)
builder.add_node("diagnose",  diagnose_node)
builder.add_node("plan",      plan_node)
builder.add_node("hitl",      hitl_node)
builder.add_node("execute",   execute_node)
builder.add_node("explain",   explain_node)

# ── Linear edges ────────────────────────────────────────────────────
builder.set_entry_point("observe")
builder.add_edge("observe",  "detect")
builder.add_edge("detect",   "diagnose")
builder.add_edge("diagnose", "plan")

# ── Conditional: safety gate ─────────────────────────────────────────
builder.add_conditional_edges(
    "plan",
    safety_gate,
    {
        "auto_execute": "execute",
        "hitl":         "hitl",
        "skip":         "explain",
    }
)

# ── HITL branch ──────────────────────────────────────────────────────
builder.add_conditional_edges(
    "hitl",
    lambda state: "execute" if state.get("hitl_decision") == "approved" else "explain",
    {
        "execute": "execute",
        "explain": "explain",
    }
)

# ── Execute → Explain → END (one cycle per invoke) ──────────────────
builder.add_edge("execute", "explain")
builder.add_edge("explain", END)

# ── Compile with checkpointer ────────────────────────────────────────
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)


def get_config(thread_id: str) -> dict:
    """Returns LangGraph config dict for a given thread."""
    return {"configurable": {"thread_id": thread_id}}


# ── Entry point ──────────────────────────────────────────────────────
async def run():
    """
    Starts the agent loop. Each iteration is one observe→detect→...→explain cycle.
    Tracks processed pods with a 5-minute cooldown to prevent duplicate handling.
    """
    print(f"K8sWhisperer agent starting... (polling every {POLL_INTERVAL}s)")
    print(f"Incident cooldown: {COOLDOWN_SECONDS}s (pods won't be re-processed within this window)")
    print("=" * 60)

    # Track processed pods: {pod_key: timestamp}
    processed_pods: dict = {}

    while True:
        # Clean up expired cooldowns
        now = time.time()
        processed_pods = {
            k: v for k, v in processed_pods.items()
            if now - v < COOLDOWN_SECONDS
        }

        state = initial_state()
        thread_id = str(uuid.uuid4())
        state["incident_id"] = thread_id
        state["hitl_thread_id"] = thread_id
        # Pass processed pods as active_incident_pods for detect_node to filter
        state["active_incident_pods"] = set(processed_pods.keys())

        config = get_config(thread_id)
        try:
            print(f"\n[cycle] Starting observation cycle {thread_id[:8]}...")
            if processed_pods:
                print(f"[cycle] Skipping {len(processed_pods)} recently processed pods: {list(processed_pods.keys())}")

            cycle_start = time.time()
            result = await graph.ainvoke(state, config=config)
            duration = round(time.time() - cycle_start, 1)

            anomalies = result.get("anomalies", [])
            if anomalies:
                print(f"[cycle] Found {len(anomalies)} anomalies — processed in {duration}s.")
                # Mark processed pods for cooldown
                for a in anomalies:
                    processed_pods[a.affected_resource] = time.time()
            else:
                print(f"[cycle] No anomalies detected. Sleeping {POLL_INTERVAL}s...")

        except KeyboardInterrupt:
            print("\nAgent stopped.")
            break
        except Exception as e:
            print(f"[graph] Error in cycle: {e}")

        # Wait before next poll
        try:
            await asyncio.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nAgent stopped.")
            break


if __name__ == "__main__":
    asyncio.run(run())

