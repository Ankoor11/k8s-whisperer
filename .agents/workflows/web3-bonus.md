---
description: How to build, deploy, and demo the Web3/Blockchain Bonus (Stellar audit trail)
---

# Web3 Blockchain Bonus — Edition Workflow

## Prerequisites
1. Install Rust: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
2. Add wasm target: `rustup target add wasm32-unknown-unknown`
3. Install Stellar CLI: `cargo install --locked stellar-cli --features opt`
4. Install Node.js 18+
5. Generate a Stellar testnet keypair:
   ```bash
   stellar keys generate k8swhisperer --network testnet --fund
   stellar keys address k8swhisperer   # → public key (G...)
   stellar keys show k8swhisperer      # → secret key (S...)
   ```

## Step 1 — Build the Smart Contract
```bash
cd contracts/audit-trail
stellar contract build
```
// turbo
Expected: `target/wasm32-unknown-unknown/release/k8s_audit_trail.wasm` is created.

## Step 2 — Deploy to Stellar Testnet
```bash
stellar contract deploy \
  --wasm target/wasm32-unknown-unknown/release/k8s_audit_trail.wasm \
  --network testnet \
  --source k8swhisperer
```
Copy the output Contract ID (starts with `C...`).

## Step 3 — Initialize the Contract
```bash
stellar contract invoke --id <CONTRACT_ID> --network testnet --source k8swhisperer -- initialize --admin <PUBLIC_KEY>
```

## Step 4 — Configure Environment
Add to `.env` in the project root:
```bash
STELLAR_SECRET_KEY=S...         # from step 0
STELLAR_CONTRACT_ID=C...        # from step 2
SOROBAN_RPC_URL=https://soroban-testnet.stellar.org
```

## Step 5 — Install Python Dependencies
```bash
pip install stellar-sdk
```
// turbo

## Step 6 — Start Backend API
```bash
uvicorn api.webhook:app --port 8002 --reload
```

## Step 7 — Start Frontend
```bash
cd frontend && npm install && npm run dev
```

## Step 8 — Run End-to-End Demo
```bash
# Terminal: Start the agent
python -m agent.graph

# Inject a test scenario
kubectl apply -f k8s/test-scenarios/crashloop.yaml
```
Wait for the agent to detect → diagnose → plan → execute → explain.
Check:
- `audit_log.json` has a new entry
- Terminal shows `[stellar] ✓ Incident logged on-chain`
- Frontend at `http://localhost:3000` shows the incident
- Blockchain tab verifies the SHA-256 hash

## Step 9 — Capture Block Explorer Screenshot
Visit: `https://stellar.expert/explorer/testnet/contract/<CONTRACT_ID>`
Take a screenshot showing the deployed contract details and transaction history.

## Step 10 — Update README
1. Replace `TBD` in `contracts/README.md` with the actual Contract ID
2. Add the block explorer screenshot
3. Add UI screenshots of Dashboard, Incidents, and Blockchain tabs
4. Review that README doesn't look AI-generated

## Step 11 — Clean Up Repository
```bash
# Remove scaffolding contract if not needed
rm -rf contracts/hello-world
```
Ensure `contracts/` only contains the `audit-trail` contract and `README.md`.

## Step 12 — Final Verification
// turbo
```bash
cd contracts/audit-trail && cargo test
cd ../../frontend && npm run build
```
Both must pass without errors.
