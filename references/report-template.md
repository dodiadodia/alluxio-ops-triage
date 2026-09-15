# Support Diagnosis Report

Use this template for an interim update, final incident diagnosis, or escalation. Omit empty optional sections, but never hide data gaps.

## Confidence vocabulary

| Level | Meaning |
|---|---|
| Confirmed | Direct evidence proves the causal mechanism, and contradicting evidence has been resolved. |
| Probable | Multiple independent signals support the mechanism; one material proof is still missing. |
| Possible | Plausible and partially supported, but competing explanations remain. |
| Unresolved | Available evidence cannot distinguish the leading explanations. |

Do not label a hypothesis Confirmed solely because a log contains ERROR, a pod restarted, or a metric crossed a generic threshold.

## Severity guide

| Severity | Operational meaning | Typical communication |
|---|---|---|
| P0 | All critical workloads cannot access data, or confirmed active data-loss/corruption risk | Immediate incident bridge; frequent updates per customer policy |
| P1 | Critical workload or major function is unavailable or materially degraded | Urgent coordinated response |
| P2 | Service remains usable but performance, capacity, or a subset of workloads is affected | Tracked incident with bounded response |
| P3 | Latent risk, minor defect, or informational finding without current impact | Planned remediation |

Customer impact determines severity. A severe-looking internal error with no impact is not automatically P0.

## Report template

~~~markdown
# Alluxio Incident Diagnosis

## 1. Executive conclusion

- Severity:
- Status: investigating / contained / monitoring / resolved
- Customer impact:
- Root cause:
- Confidence:
- Immediate next action:

## 2. Scope and environment

| Field | Value |
|---|---|
| Incident window and time zone | |
| Alluxio version and image | |
| Operator version | |
| Deployment mode | Kubernetes / Docker / bare metal |
| Access mode | FUSE / S3 API / FSSpec / mixed |
| Cache mode | read cache / write cache with FDB |
| Cluster and namespaces | |
| UFS | |
| Affected workloads, nodes, paths | |
| Recent changes | |

## 3. Timeline

| Time | Source | Event or action | Result |
|---|---|---|---|
| | | | |

## 4. Evidence

| ID | Time | Component | Source or command | Redacted observation | Interpretation |
|---|---|---|---|---|---|
| E1 | | | | | |

## 5. Hypothesis assessment

| Hypothesis | Supporting evidence | Contradicting evidence | Confidence | Next discriminator |
|---|---|---|---|---|
| | | | | |

## 6. Root cause and contributing factors

- Trigger:
- Failure mechanism:
- Why redundancy or recovery did not prevent impact:
- Contributing configuration, capacity, or process factors:

## 7. Containment and remediation

### Immediate containment

| Action | Risk and impact | Prerequisite | Validation | Rollback |
|---|---|---|---|---|
| | | | | |

### Durable remediation

| Action | Owner | Target date | Validation |
|---|---|---|---|
| | | | |

## 8. Recovery verification

- Component readiness and restart counts:
- Worker membership:
- Exact known-path read or application canary:
- Job state:
- Error and timeout rate:
- Throughput and latency versus baseline:
- Cache and UFS behavior:
- Observation window:
- Data consistency check:

## 9. Data gaps and residual risk

- Missing evidence:
- Why it is missing:
- Effect on confidence:
- Residual customer or data risk:

## 10. Support attachment manifest

- Diagnostic Snapshot filename and SHA-256:
- Collection window:
- Current and previous logs:
- Pod descriptions and events:
- Relevant metrics or screenshots:
- Redacted configuration and custom resources:
- Job history:
- Reproduction details:
- Files intentionally excluded or redacted:
~~~

## Minimum escalation package

Include Alluxio and Operator versions, deployment and access modes, UFS type, incident time zone, impact, exact error, affected scope, recent changes, current pod and Worker status, previous logs for restarted containers, a time-bounded Diagnostic Snapshot, relevant metrics, actions already taken, and data gaps.

Before sharing, remove credentials, secret values, authorization headers, signed URLs, private keys, customer-sensitive paths, and unnecessary data payloads. Preserve filenames, timestamps, component names, and correlation IDs needed for analysis.
