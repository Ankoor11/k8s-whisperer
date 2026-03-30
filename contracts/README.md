# K8sWhisperer — Blockchain Audit Trail

## Project Title
**K8sWhisperer Immutable Audit Trail** — Tamper-proof incident logging on Stellar blockchain.

## Project Description
K8sWhisperer is an autonomous Kubernetes incident response agent. This Web3 module adds an **immutable audit trail** by hashing every incident resolution and storing it on the **Stellar blockchain** via a **Soroban smart contract**. A React + Tailwind dashboard lets users verify that no audit records have been tampered with.

## Project Vision
Autonomous AI agents making infrastructure decisions need accountability. By anchoring every incident's diagnosis, action, and outcome on-chain, we create a trustless verification layer — anyone can independently confirm that the agent's decision history hasn't been altered.

## Key Features
- **SHA-256 Audit Hashing** — Every incident enters a deterministic hash stored on-chain
- **Soroban Smart Contract** — `log_incident`, `verify_incident`, `get_recent_incidents`
- **Real-time Dashboard** — React + Tailwind with blockchain verification UI
- **Automatic Integration** — Agent pipeline submits hashes after every remediation cycle
- **Tamper Detection** — Hash mismatch reveals if any audit entry was modified

## Deployed Smart Contract Details

### Contract ID
```
TBD — Deployed to Stellar Testnet via `stellar contract deploy`
```

### Contract Functions
| Function | Description |
|---|---|
| `initialize(admin)` | Set contract admin |
| `log_incident(reporter, hash, type, resource, decision, blast)` | Store incident |
| `verify_incident(id, hash)` | Check hash matches |
| `get_incident(id)` | Retrieve record |
| `get_recent_incidents(count)` | Dashboard feed |

## UI Screenshots
The frontend provides three views:
1. **Dashboard** — Stats cards, anomaly distribution, decision breakdown, blockchain status
2. **Incidents** — Expandable table with filtering, showing diagnosis and execution results
3. **Blockchain** — Incident selector with SHA-256 hash verification and on-chain proof

## Demo Link
```bash
# Start API server
uvicorn api.webhook:app --port 8002 --reload

# Start frontend (requires npm)
cd frontend && npm install && npm run dev

# Open http://localhost:3000
```

## Project Setup Guide

### Prerequisites
- Python 3.9+
- Node.js 18+ (for frontend)
- Rust + Soroban CLI (for contract deployment)
- Minikube (for K8s monitoring)

### Installation
```bash
# Python agent
pip install -r requirements.txt

# Frontend
cd frontend && npm install

# Smart contract (optional — for deployment)
cd contracts/audit-trail
stellar contract build
stellar contract deploy --wasm target/wasm32-unknown-unknown/release/k8s_audit_trail.wasm --network testnet
```

### Configuration
Add to `.env`:
```bash
STELLAR_SECRET_KEY=S...         # Stellar testnet keypair secret
STELLAR_CONTRACT_ID=C...        # Deployed contract ID
SOROBAN_RPC_URL=https://soroban-testnet.stellar.org
```

### Running
```bash
# Terminal 1: API + HITL
uvicorn api.webhook:app --port 8002 --reload

# Terminal 2: Agent
python -m agent.graph

# Terminal 3: Frontend
cd frontend && npm run dev

# Terminal 4: Inject test
kubectl apply -f k8s/test-scenarios/crashloop.yaml
```

## Repository Structure
```
k8s-whisperer/
├── contracts/audit-trail/      # Soroban smart contract (Rust)
│   ├── Cargo.toml
│   └── src/lib.rs              # log_incident, verify_incident, get_*
├── frontend/                   # React + Tailwind dashboard
│   ├── src/
│   │   ├── components/
│   │   │   ├── Dashboard.jsx
│   │   │   ├── IncidentTable.jsx
│   │   │   └── BlockchainVerifier.jsx
│   │   ├── App.jsx
│   │   └── index.css
│   ├── package.json
│   └── tailwind.config.js
├── integration/                # Stellar-SDK integration
│   └── stellar_client.py       # submit_to_stellar, verify_on_chain
├── agent/                      # LangGraph pipeline
│   └── nodes/explain.py        # Calls stellar_client after audit log
└── api/
    └── webhook.py              # /api/audit-log endpoint for frontend
```

## Future Scope
- Deploy contract to Stellar mainnet for production audit trails
- Add multi-signature approval for HITL decisions on-chain
- NFT-based incident certificates for compliance
- Cross-cluster audit aggregation via Stellar anchors
- Dashboard integration with StellarExpert block explorer links
