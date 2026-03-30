#![no_std]
use soroban_sdk::{contract, contractimpl, contracttype, log, symbol_short, vec, Env, String, Symbol, Vec};

/// Represents a single incident record stored on-chain
#[contracttype]
#[derive(Clone, Debug)]
pub struct IncidentRecord {
    pub incident_hash: String,    // SHA-256 hash of the full audit entry
    pub anomaly_type: String,     // e.g. "OOMKilled", "CrashLoopBackOff"
    pub resource: String,         // e.g. "default/oom-test-xxx"
    pub action: String,           // e.g. "patch_memory", "restart_pod"
    pub decision: String,         // e.g. "auto_executed", "hitl_approved"
    pub timestamp: u64,           // Unix timestamp
}

/// Storage key for the incident list
const INCIDENTS: Symbol = symbol_short!("INCIDENT");
const COUNT: Symbol = symbol_short!("COUNT");

#[contract]
pub struct AuditContract;

#[contractimpl]
impl AuditContract {
    /// Store a new incident record on the blockchain.
    /// Called by the K8sWhisperer agent after each remediation.
    pub fn store_incident(
        env: Env,
        incident_hash: String,
        anomaly_type: String,
        resource: String,
        action: String,
        decision: String,
        timestamp: u64,
    ) -> u64 {
        let record = IncidentRecord {
            incident_hash,
            anomaly_type,
            resource,
            action,
            decision,
            timestamp,
        };

        // Get current count
        let count: u64 = env.storage().instance().get(&COUNT).unwrap_or(0);
        let new_count = count + 1;

        // Store the record with its index as key
        let key = (INCIDENTS, new_count);
        env.storage().instance().set(&key, &record);
        env.storage().instance().set(&COUNT, &new_count);

        // Extend TTL to keep data alive (30 days)
        env.storage().instance().extend_ttl(100, 518400);

        log!(&env, "Incident #{} stored: {}", new_count, record.anomaly_type);
        new_count
    }

    /// Get a specific incident by index (1-based)
    pub fn get_incident(env: Env, index: u64) -> IncidentRecord {
        let key = (INCIDENTS, index);
        env.storage().instance().get(&key).unwrap()
    }

    /// Get the total number of stored incidents
    pub fn get_count(env: Env) -> u64 {
        env.storage().instance().get(&COUNT).unwrap_or(0)
    }

    /// Get the most recent N incidents
    pub fn get_recent(env: Env, n: u64) -> Vec<IncidentRecord> {
        let count: u64 = env.storage().instance().get(&COUNT).unwrap_or(0);
        let mut results = vec![&env];
        
        let start = if count > n { count - n + 1 } else { 1 };
        let mut i = start;
        while i <= count {
            let key = (INCIDENTS, i);
            if let Some(record) = env.storage().instance().get::<_, IncidentRecord>(&key) {
                results.push_back(record);
            }
            i += 1;
        }
        results
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use soroban_sdk::Env;

    #[test]
    fn test_store_and_retrieve() {
        let env = Env::default();
        let contract_id = env.register(AuditContract, ());
        let client = AuditContractClient::new(&env, &contract_id);

        let hash = String::from_str(&env, "abc123def456");
        let anomaly = String::from_str(&env, "OOMKilled");
        let resource = String::from_str(&env, "default/oom-test");
        let action = String::from_str(&env, "patch_memory");
        let decision = String::from_str(&env, "auto_executed");

        let count = client.store_incident(&hash, &anomaly, &resource, &action, &decision, &1711700000);
        assert_eq!(count, 1);

        let record = client.get_incident(&1);
        assert_eq!(record.anomaly_type, anomaly);
        assert_eq!(record.action, action);

        let total = client.get_count();
        assert_eq!(total, 1);
    }
}
