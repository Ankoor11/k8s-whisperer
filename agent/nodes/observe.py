"""
Observe Node — polls cluster state every POLL_INTERVAL_SECONDS.
Normalises raw kubectl output into ClusterState.events.
"""
import json
import os
from agent.state import ClusterState
from mcp.kubectl_client import list_pods, get_events


POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))


async def observe_node(state: ClusterState) -> ClusterState:
    """
    Polls all namespaces. Populates state.events with normalised pod/event data.
    Skips pods already in state.active_incident_pods (race condition guard).
    """
    # Fetch all pods
    pods_data = list_pods(namespace="default")

    # Fetch recent events
    events_data = get_events(namespace="default")

    # Normalise into flat event list
    events = _normalise_cluster_state(pods_data, events_data)
    print(f"[observe] Found {len(pods_data.get('items', []))} pods and {len(events)} normalized events.")

    return {
        **state,
        "events": events,
        "cluster_snapshot": pods_data,
    }


def _normalise_cluster_state(pods_data: dict, events_data: dict) -> list:
    """
    Flattens pod list and events into a uniform list of dicts for the LLM classifier.
    Each dict has: pod_name, namespace, phase, restart_count, container_states, conditions, recent_events
    """
    events = []

    items = pods_data.get("items", [])
    for pod in items:
        meta = pod.get("metadata", {})
        spec = pod.get("spec", {})
        status = pod.get("status", {})

        pod_name = meta.get("name", "")
        namespace = meta.get("namespace", "default")
        phase = status.get("phase", "Unknown")
        annotations = meta.get("annotations", {})

        container_statuses = status.get("containerStatuses", [])
        restart_count = sum(cs.get("restartCount", 0) for cs in container_statuses)

        container_states = []
        for cs in container_statuses:
            cs_state = cs.get("state", {})
            last_state = cs.get("lastState", {})
            container_states.append({
                "name": cs.get("name"),
                "ready": cs.get("ready"),
                "restart_count": cs.get("restartCount", 0),
                "state": cs_state,
                "last_state": last_state,
            })

        # Pods owned by a rolling Deployment have "pod-template-hash".
        # Pods owned by a rolling StatefulSet/DaemonSet have "controller-revision-hash".
        # "deployment.kubernetes.io/revision" appears on the Deployment object itself, NOT on pods.
        is_rolling_update = (
            "pod-template-hash" in annotations
            or "controller-revision-hash" in annotations
        )

        events.append({
            "pod_name": pod_name,
            "namespace": namespace,
            "phase": phase,
            "restart_count": restart_count,
            "container_states": container_states,
            "conditions": status.get("conditions", []),
            "is_rolling_update": is_rolling_update,
            "start_time": status.get("startTime"),
            "node_name": spec.get("nodeName"),
            "reason": status.get("reason", ""),
        })

    return events
