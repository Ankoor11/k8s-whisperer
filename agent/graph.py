"""
K8sWhisperer LangGraph agent — main graph definition.
Assembles all 7 pipeline nodes with conditional edges and checkpointer.
"""
import asyncio
import os
import uuid
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
# After HITL approval → execute; rejection → explain (no action)
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
builder.add_edge("explain", END)  # End the graph; outer loop handles polling

# ── Compile with checkpointer (required for HITL interrupt/resume) ───
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer, interrupt_before=["hitl"])


def get_config(thread_id: str) -> dict:
    """Returns LangGraph config dict for a given thread."""
    return {"configurable": {"thread_id": thread_id}}


# ── Entry point ──────────────────────────────────────────────────────
async def run():
    """
    Starts the agent loop. Each iteration is one observe→detect→...→explain cycle.
    Polls every POLL_INTERVAL_SECONDS. Ctrl+C to stop.
    """
    print(f"K8sWhisperer agent starting... (polling every {POLL_INTERVAL}s)")
    print("=" * 60)

    while True:
        state = initial_state()
        thread_id = str(uuid.uuid4())
        state["incident_id"] = thread_id
        state["hitl_thread_id"] = thread_id

        config = get_config(thread_id)
        try:
            print(f"\n[cycle] Starting observation cycle {thread_id[:8]}...")
            result = await graph.ainvoke(state, config=config)

            anomalies = result.get("anomalies", [])
            if anomalies:
                print(f"[cycle] Found {len(anomalies)} anomalies — processed.")
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
