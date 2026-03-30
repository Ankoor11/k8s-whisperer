"""
Stellar integration client for K8sWhisperer.
Submits incident audit hashes to the Stellar blockchain for immutable logging.
Uses Stellar Python SDK to interact with the deployed Soroban smart contract.
"""
import hashlib
import json
import os
import time
from typing import Optional

try:
    from stellar_sdk import (
        Keypair, Network, Server, TransactionBuilder,
        scval, SorobanServer
    )
    STELLAR_AVAILABLE = True
    NETWORK_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
except ImportError:
    STELLAR_AVAILABLE = False
    NETWORK_PASSPHRASE = "Test SDF Network ; September 2015"


# ── Configuration ──────────────────────────────────────────────────
SOROBAN_RPC_URL = os.getenv("SOROBAN_RPC_URL", "https://soroban-testnet.stellar.org")
STELLAR_SECRET_KEY = os.getenv("STELLAR_SECRET_KEY", "")
CONTRACT_ID = os.getenv("STELLAR_CONTRACT_ID", "")


def compute_audit_hash(audit_entry: dict) -> str:
    """
    Compute SHA-256 hash of an audit log entry.
    Used as the tamper-proof fingerprint stored on-chain.
    """
    # Deterministic JSON serialization
    canonical = json.dumps(audit_entry, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def submit_to_stellar(audit_entry: dict) -> Optional[dict]:
    """
    Submit an incident audit hash to the Stellar blockchain.
    
    Returns:
        dict with tx_hash and incident_id on success, None on failure
    """
    if not STELLAR_AVAILABLE:
        print("[stellar] stellar-sdk not installed — skipping blockchain submission")
        return None
    
    if not STELLAR_SECRET_KEY or not CONTRACT_ID:
        print("[stellar] STELLAR_SECRET_KEY or STELLAR_CONTRACT_ID not configured — skipping")
        return None

    try:
        # Compute the audit hash
        audit_hash = compute_audit_hash(audit_entry)
        
        # Setup Stellar client
        keypair = Keypair.from_secret(STELLAR_SECRET_KEY)
        soroban = SorobanServer(SOROBAN_RPC_URL)
        account = soroban.load_account(keypair.public_key)
        
        # Build the contract invocation transaction
        builder = TransactionBuilder(
            source_account=account,
            network_passphrase=NETWORK_PASSPHRASE,
            base_fee=100,
        )
        
        # Call log_incident on the contract
        tx = builder.append_invoke_contract_function_op(
            contract_id=CONTRACT_ID,
            function_name="log_incident",
            parameters=[
                scval.to_address(keypair.public_key),  # reporter
                scval.to_bytes(bytes.fromhex(audit_hash)),  # audit_hash
                scval.to_string(audit_entry.get("anomaly_type", "")),  # anomaly_type
                scval.to_string(audit_entry.get("affected_resource", "")),  # affected_resource
                scval.to_string(audit_entry.get("decision", "")),  # decision
                scval.to_string(audit_entry.get("plan_blast_radius", "")),  # blast_radius
            ]
        ).set_timeout(30).build()
        
        # Simulate the transaction
        sim_response = soroban.simulate_transaction(tx)
        
        # Prepare and sign
        prepared_tx = soroban.prepare_transaction(tx, sim_response)
        prepared_tx.sign(keypair)
        
        # Submit
        response = soroban.send_transaction(prepared_tx)
        tx_hash = response.hash
        
        print(f"[stellar] ✓ Incident logged on-chain — tx: {tx_hash[:16]}...")
        
        return {
            "tx_hash": tx_hash,
            "audit_hash": audit_hash,
            "network": "testnet",
            "contract_id": CONTRACT_ID,
        }
        
    except Exception as e:
        print(f"[stellar] Failed to submit to blockchain: {e}")
        return None


def verify_on_chain(incident_id: int, audit_entry: dict) -> Optional[bool]:
    """
    Verify that an incident's audit hash matches the on-chain record.
    
    Returns:
        True if hash matches, False if mismatch, None if verification failed
    """
    if not STELLAR_AVAILABLE or not STELLAR_SECRET_KEY or not CONTRACT_ID:
        return None

    try:
        audit_hash = compute_audit_hash(audit_entry)
        
        soroban = SorobanServer(SOROBAN_RPC_URL)
        keypair = Keypair.from_secret(STELLAR_SECRET_KEY)
        account = soroban.load_account(keypair.public_key)
        
        builder = TransactionBuilder(
            source_account=account,
            network_passphrase=NETWORK_PASSPHRASE,
            base_fee=100,
        )
        
        tx = builder.append_invoke_contract_function_op(
            contract_id=CONTRACT_ID,
            function_name="verify_incident",
            parameters=[
                scval.to_uint32(incident_id),
                scval.to_bytes(bytes.fromhex(audit_hash)),
            ]
        ).set_timeout(30).build()
        
        sim_response = soroban.simulate_transaction(tx)
        # Parse the boolean result from simulation
        result = scval.from_bool(sim_response.results[0].xdr)
        
        return result
        
    except Exception as e:
        print(f"[stellar] Verification failed: {e}")
        return None


def get_blockchain_explorer_url(tx_hash: str) -> str:
    """Returns the StellarExpert URL for a transaction."""
    return f"https://stellar.expert/explorer/testnet/tx/{tx_hash}"
