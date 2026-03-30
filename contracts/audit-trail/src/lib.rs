#![no_std]
use soroban_sdk::{
    contract, contractimpl, contracttype, log, symbol_short, Address, BytesN, Env,
    String, Symbol, Vec,
};

/// Represents a single incident audit record stored on-chain.
#[contracttype]
#[derive(Clone, Debug)]
pub struct IncidentRecord {
    pub audit_hash: BytesN<32>,
    pub anomaly_type: String,
    pub affected_resource: String,
    pub decision: String,
    pub blast_radius: String,
    pub ledger: u32,
    pub reporter: Address,
}

const COUNTER: Symbol = symbol_short!("COUNTER");
const INCIDENTS: Symbol = symbol_short!("INC");
const ADMIN: Symbol = symbol_short!("ADMIN");

#[contract]
pub struct AuditTrailContract;

#[contractimpl]
impl AuditTrailContract {
    pub fn initialize(env: Env, admin: Address) {
        if env.storage().instance().has(&ADMIN) {
            panic!("already initialized");
        }
        env.storage().instance().set(&ADMIN, &admin);
        env.storage().instance().set(&COUNTER, &0u32);
        log!(&env, "AuditTrail initialized with admin: {}", admin);
    }

    pub fn log_incident(
        env: Env,
        reporter: Address,
        audit_hash: BytesN<32>,
        anomaly_type: String,
        affected_resource: String,
        decision: String,
        blast_radius: String,
    ) -> u32 {
        reporter.require_auth();
        let mut count: u32 = env.storage().instance().get(&COUNTER).unwrap_or(0);
        count += 1;

        let record = IncidentRecord {
            audit_hash: audit_hash.clone(),
            anomaly_type,
            affected_resource,
            decision,
            blast_radius,
            ledger: env.ledger().sequence(),
            reporter,
        };

        env.storage().persistent().set(&(INCIDENTS, count), &record);
        env.storage().instance().set(&COUNTER, &count);
        log!(&env, "Incident #{} logged, hash: {:?}", count, audit_hash);
        count
    }

    pub fn verify_incident(env: Env, incident_id: u32, audit_hash: BytesN<32>) -> bool {
        let record: IncidentRecord = env
            .storage()
            .persistent()
            .get(&(INCIDENTS, incident_id))
            .expect("incident not found");
        record.audit_hash == audit_hash
    }

    pub fn get_incident(env: Env, incident_id: u32) -> IncidentRecord {
        env.storage()
            .persistent()
            .get(&(INCIDENTS, incident_id))
            .expect("incident not found")
    }

    pub fn get_incident_count(env: Env) -> u32 {
        env.storage().instance().get(&COUNTER).unwrap_or(0)
    }

    pub fn get_recent_incidents(env: Env, count: u32) -> Vec<IncidentRecord> {
        let total: u32 = env.storage().instance().get(&COUNTER).unwrap_or(0);
        let start = if total > count { total - count + 1 } else { 1 };
        let mut results = Vec::new(&env);
        for i in start..=total {
            if let Some(record) = env
                .storage()
                .persistent()
                .get::<_, IncidentRecord>(&(INCIDENTS, i))
            {
                results.push_back(record);
            }
        }
        results
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use soroban_sdk::testutils::Address as _;
    use soroban_sdk::Env;

    #[test]
    fn test_log_and_verify() {
        let env = Env::default();
        let contract_id = env.register_contract(None, AuditTrailContract);
        let client = AuditTrailContractClient::new(&env, &contract_id);

        let admin = Address::generate(&env);
        let reporter = Address::generate(&env);
        client.initialize(&admin);
        env.mock_all_auths();

        let hash = BytesN::from_array(&env, &[0u8; 32]);
        let anomaly_type = String::from_str(&env, "CrashLoopBackOff");
        let resource = String::from_str(&env, "default/crashloop-test");
        let decision = String::from_str(&env, "auto_executed");
        let blast = String::from_str(&env, "low");

        let id = client.log_incident(&reporter, &hash, &anomaly_type, &resource, &decision, &blast);
        assert_eq!(id, 1);
        assert!(client.verify_incident(&1, &hash));
        assert_eq!(client.get_incident_count(), 1);
    }
}
