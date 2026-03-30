from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime


class AnomalyType(str, Enum):
    CRASH_LOOP_BACK_OFF = "CrashLoopBackOff"
    OOM_KILLED = "OOMKilled"
    PENDING_POD = "PendingPod"
    IMAGE_PULL_BACK_OFF = "ImagePullBackOff"
    CPU_THROTTLING = "CPUThrottling"
    EVICTED_POD = "EvictedPod"
    DEPLOYMENT_STALLED = "DeploymentStalled"
    NODE_NOT_READY = "NodeNotReady"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class BlastRadius(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Anomaly(BaseModel):
    type: AnomalyType
    severity: Severity
    affected_resource: str          # e.g. "default/my-pod-abc123"
    namespace: str = "default"
    confidence: float = Field(ge=0.0, le=1.0)
    trigger_signal: str             # raw signal that caused detection
    is_rolling_update: bool = False # true if restart is part of planned rollout


class RemediationPlan(BaseModel):
    action: str                     # e.g. "restart_pod", "patch_memory", "recommend"
    target_resource: str            # e.g. "default/my-pod-abc123"
    namespace: str = "default"
    params: dict = {}               # action-specific params e.g. {"memory_factor": 1.5}
    confidence: float = Field(ge=0.0, le=1.0)
    blast_radius: BlastRadius
    reasoning: str                  # why this action was chosen


class HITLDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LogEntry(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    incident_id: str
    anomaly_type: str
    affected_resource: str
    diagnosis: str
    plan_action: str
    plan_blast_radius: str
    decision: str                   # "auto_executed", "hitl_approved", "hitl_rejected", "skipped"
    result: str
    explanation: str                # plain English, non-expert readable
    duration_seconds: float = 0.0
    blockchain_tx_hash: Optional[str] = None  # Stellar tx hash if on-chain submission succeeded

