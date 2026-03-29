"""
Safety Gate — conditional routing node.
Returns route string consumed by LangGraph conditional edge.
"""
from agent.state import ClusterState
from agent.models import BlastRadius
from agent.nodes.plan import DESTRUCTIVE_ACTIONS


def safety_gate(state: ClusterState) -> str:
    """
    Returns: "auto_execute" | "hitl" | "skip"
    Routing logic is deterministic — not LLM-dependent.
    """
    plan = state.get("plan")

    if not plan:
        return "skip"

    action = plan.action
    confidence = plan.confidence
    blast_radius = plan.blast_radius

    # Hard blocks — always HITL regardless of confidence
    if action in DESTRUCTIVE_ACTIONS:
        print(f"[safety_gate] BLOCKED: {action} is in DESTRUCTIVE_ACTIONS → HITL")
        return "hitl"

    if blast_radius == BlastRadius.HIGH:
        print(f"[safety_gate] blast_radius=HIGH → HITL")
        return "hitl"

    # Node NotReady is always HITL — never auto
    anomaly = state.get("current_anomaly")
    if anomaly and anomaly.type.value == "NodeNotReady":
        print(f"[safety_gate] NodeNotReady → HITL ONLY")
        return "hitl"

    # Auto-execute conditions
    if (
        confidence > 0.8
        and blast_radius == BlastRadius.LOW
        and action not in DESTRUCTIVE_ACTIONS
    ):
        print(f"[safety_gate] confidence={confidence:.2f}, blast_radius=low → AUTO EXECUTE")
        return "auto_execute"

    # Everything else → HITL
    print(f"[safety_gate] confidence={confidence:.2f}, blast_radius={blast_radius} → HITL")
    return "hitl"
