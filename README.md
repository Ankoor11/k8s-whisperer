# K8sWhisperer

Autonomous Kubernetes incident response agent built with LangGraph, MCP, and Claude.

## Architecture

```
Observe → Detect → Diagnose → Plan → Safety Gate → Execute → Explain → (loop)
                                            │
                                      ┌─────┴─────┐
                                  auto_execute    hitl
                                      │            │
                                  Execute    Slack Approve/Reject
                                      │            │
                                  Explain     Execute or Skip
                                      │            │
                                      └──── Observe ◄──┘
```

**Pipeline nodes:** 7 stages sharing a single `ClusterState` TypedDict.  
**Safety:** DESTRUCTIVE_ACTIONS frozenset + deterministic blast radius map.  
**HITL:** LangGraph `interrupt()` + Slack Block Kit + FastAPI webhook.

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, etc.
```

### 3. Apply RBAC (minikube)
```bash
kubectl apply -f k8s/rbac.yaml

# Verify (must return "no" for both):
kubectl auth can-i delete namespace --as=system:serviceaccount:default:k8swhisperer-sa
kubectl auth can-i drain nodes --as=system:serviceaccount:default:k8swhisperer-sa
```

### 4. Start services

```bash
# Terminal 1: HITL webhook server
uvicorn api.webhook:app --port 8002 --reload

# Terminal 2: Expose to Slack (copy HTTPS URL to Slack App Interactivity settings)
ngrok http 8002

# Terminal 3: Start the agent
python -m agent.graph
```

## Demo Scenarios

```bash
# CrashLoopBackOff (auto-fix)
kubectl apply -f k8s/test-scenarios/crashloop.yaml

# OOMKilled (HITL approval required)
kubectl apply -f k8s/test-scenarios/oom-pod.yaml

# Pending Pod (recommendation only)
kubectl apply -f k8s/test-scenarios/pending-pod.yaml

# Clean up
kubectl delete -f k8s/test-scenarios/
```

## Audit Log

Every incident is logged to `audit_log.json` with: timestamp, incident_id, anomaly_type, affected_resource, diagnosis, plan_action, blast_radius, decision, result, and plain-English explanation.

```bash
python -c "
import json
log = json.load(open('audit_log.json'))
print(f'Total incidents: {len(log)}')
for e in log:
    print(f'  [{e[\"timestamp\"][:19]}] {e[\"anomaly_type\"]} | {e[\"decision\"]} | {e[\"affected_resource\"]}')
    print(f'    Explanation: {e[\"explanation\"]}')
"
```

## Scoring (100 pts)

| Category | Points |
|---|---|
| Autonomous Remediation | 30 |
| Safety Gate & HITL | 25 |
| Diagnosis Quality | 20 |
| LangGraph Architecture | 15 |
| MCP Integration | 10 |

## Key Safety Constraints

- **RBAC**: ServiceAccount scoped to pod-level only — zero `cluster-admin`
- **DESTRUCTIVE_ACTIONS**: Hardcoded Python frozenset (never LLM-controlled)
- **Blast radius**: Deterministic map by anomaly type (never LLM-determined)
- **Node-level actions**: Always HITL — never auto-execute
- **HITL**: LangGraph `interrupt()` — no spin-waiting or `time.sleep()`
