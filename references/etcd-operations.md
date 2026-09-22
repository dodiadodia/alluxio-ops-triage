# Etcd Operations Triage and Recovery

Use this reference when an Alluxio incident involves etcd member readiness, loss of leader or quorum, a `NOSPACE` alarm, backend growth, suspected corruption, compaction, defragmentation, snapshot, member replacement, or data-volume rebuild. It distills the Support `ETCD recovery SOP` while correcting unsafe or version-sensitive assumptions.

This is a diagnostic and decision guide, not standing authorization to mutate a cluster. Commands are templates. Derive namespace, StatefulSet, pod, endpoints, TLS arguments, authentication, data directory, and service manager from the affected environment. Never print certificate private keys, tokens, or credentials.

## First classify the incident

| Branch | Decisive evidence | Typical impact | Do not infer |
|---|---|---|---|
| One member or pod unavailable, quorum intact | Remaining endpoints commit proposals and agree on leader/term; one member fails health/readiness | Reduced fault tolerance; service may remain available | Non-Ready means corrupt data |
| Leader churn or quorum loss | `endpoint health/status`, `member list`, leader metrics, peer errors | Writes and linearizable reads fail or stall; Alluxio job/control functions degrade | Restarting every member restores quorum |
| `NOSPACE` / backend quota | `alarm list`, `mvcc: database space exceeded`, DB size versus quota | Cluster enters limited-operation maintenance mode; Alluxio job updates may fail | Physical disk free space alone clears the alarm |
| Backend fragmentation | Physical DB size materially exceeds in-use size after compaction | Disk pressure; defrag may reclaim host space | Compaction immediately shrinks the DB file |
| Confirmed corruption | `CORRUPT` alarm, hash/checksum mismatch, explicit corruption log or panic | One member or cluster may be unusable | A crash loop alone proves corruption |
| Kubernetes scheduling/storage issue | Pod events, PVC/PV state, node affinity, attach/mount errors | Member cannot start although etcd data may be valid | Deleting the PVC is the safest repair |

Record the Alluxio-visible symptoms separately: Coordinator readiness, job submission/update failure, mount or membership changes, and the exact start/end time. Alluxio data access paths may have different dependencies; report observed impact rather than claiming every client I/O path is down.

## Establish version, topology, and ownership

Before narrowing, capture:

- Alluxio, Operator, etcd image and `etcdctl` versions;
- Kubernetes, Docker, or bare-metal deployment and who owns lifecycle/configuration;
- voting member count, learner count, expected quorum, member IDs, peer/client endpoints, placement, and leader;
- StatefulSet/Service/Pod ownership or systemd unit, launch arguments, environment, and config file;
- PVC/PV/storage class or host data directory, filesystem capacity/inodes, and storage latency;
- TLS/auth requirements without exposing secret material;
- last known-good snapshot, its verification status, storage location, and restore procedure;
- which Alluxio state is stored in etcd for this release and deployment.

For a voting cluster of `N` members, quorum is `floor(N/2)+1`. A three-voter cluster therefore needs two voters. Do not count `Running` pods or learners as healthy voting members without checking membership and endpoint status.

## Read-only Kubernetes evidence

Replace every placeholder and preserve outputs in the approved incident workspace.

~~~bash
kubectl config current-context
kubectl -n <ALX_NS> get statefulset <ETCD_STS> -o wide
kubectl -n <ALX_NS> get pod -l app.kubernetes.io/component=etcd -o wide
kubectl -n <ALX_NS> get pvc
kubectl -n <ALX_NS> describe pod <ETCD_POD>
kubectl -n <ALX_NS> logs <ETCD_POD> --timestamps --since-time=<RFC3339_UTC>
kubectl -n <ALX_NS> logs <ETCD_POD> --timestamps --since-time=<RFC3339_UTC> --previous
kubectl -n <ALX_NS> get events --field-selector involvedObject.name=<ETCD_POD> --sort-by=.lastTimestamp
kubectl -n <ALX_NS> get pod <ETCD_POD> -o jsonpath='{.spec.containers[*].image}{"\n"}{.spec.containers[*].args}{"\n"}{.spec.containers[*].env}{"\n"}'
~~~

Run the installed `etcdctl --help` first and add the version-matched endpoint, CA, certificate, key-file path, and authentication flags. Do not emit secret file contents.

~~~bash
kubectl -n <ALX_NS> exec <ETCD_POD> -- etcdctl version
kubectl -n <ALX_NS> exec <ETCD_POD> -- etcdctl endpoint health --cluster
kubectl -n <ALX_NS> exec <ETCD_POD> -- etcdctl endpoint status --cluster --write-out=table
kubectl -n <ALX_NS> exec <ETCD_POD> -- etcdctl member list --write-out=table
kubectl -n <ALX_NS> exec <ETCD_POD> -- etcdctl alarm list
~~~

If `--cluster` discovery fails, test every configured client endpoint explicitly. A failed aggregate command is a data gap, not proof that all members are down. Correlate with pod/node CPU, memory, filesystem capacity/inodes, I/O latency, peer-network failure, DNS, and certificate validity.

## Read-only Docker or bare-metal evidence

The same decision model applies without Kubernetes. Identify the actual runtime and service account before running commands.

~~~bash
etcd --version
etcdctl version
systemctl status <ETCD_UNIT>
systemctl cat <ETCD_UNIT>
journalctl -u <ETCD_UNIT> --since <INCIDENT_START>
ps -ef | rg '[e]tcd'
df -h <ETCD_DATA_FILESYSTEM>
df -i <ETCD_DATA_FILESYSTEM>
mount | rg '<ETCD_DATA_FILESYSTEM>|<ETCD_DATA_DIR>'
etcdctl endpoint health --cluster
etcdctl endpoint status --cluster --write-out=table
etcdctl member list --write-out=table
etcdctl alarm list
~~~

Inspect the unit and process arguments to locate data directory, config, endpoints, TLS files, and auto-compaction/quota settings. Do not recursively scan the data directory while etcd is live. Use host disk and service metrics for I/O latency, fsync stalls, OOM, filesystem errors, and time synchronization.

## Member unavailable or suspected corruption

Use this order:

1. Preserve current/previous logs, events, status, membership, endpoint health, alarms, disk evidence, launch configuration, and metric window.
2. Prove whether quorum exists. If quorum is intact, protect it: avoid concurrent member restarts or a whole-cluster scale-down.
3. Distinguish scheduling/PVC attach, network/TLS, resource exhaustion, slow/full disk, `NOSPACE`, incompatible configuration/version, and confirmed corruption.
4. Allow the owning controller to perform its documented self-healing only while observing that it does not loop, replace multiple voters, or threaten quorum.
5. If a member needs replacement or state purge, use the exact Operator/chart or upstream procedure for the deployed version. Change one voting member at a time and re-establish health before proceeding.
6. If quorum is lost, stop improvising member-by-member changes. Escalate to a whole-cluster disaster-recovery plan using a verified snapshot and version-matched restore procedure.

The source SOP proposes scaling a three-pod StatefulSet to zero and then back to three. That guarantees a total control-plane outage and is not a default recovery. Consider it only if the release-specific owner procedure explicitly requires a coordinated full restart, the business impact is approved, evidence and a verified snapshot are preserved, and rollback is defined.

The source SOP also proposes deleting all etcd PVCs and rebuilding Alluxio configuration through CRDs/CLI/API. Treat that as destructive last resort. It can remove membership, mount, quota, license, and job metadata and may not recreate every state object. Require a complete state inventory, tested backup/restore, customer approval, maintenance window, and a post-rebuild reconciliation plan.

Do not copy a live member's entire data directory and call it a verified snapshot. Prefer the deployed version's supported `etcdctl snapshot save` workflow against one healthy endpoint, then verify with the matching `etcdutl snapshot status` or version-equivalent command. If only filesystem-level data remains, preserve it immutably and let a version-qualified recovery procedure determine whether it is usable.

## `NOSPACE` and backend growth

### Confirm the condition

Look for all of the following, not a single keyword:

- `etcdserver: mvcc: database space exceeded` or `NOSPACE`;
- `etcdctl alarm list` showing the affected member IDs;
- endpoint status DB size, leader, raft term/index, and errors;
- configured backend quota and physical filesystem headroom;
- actual metric names from `/metrics` for the deployed version.

Common v3.5-era metrics are:

- `etcd_mvcc_db_total_size_in_use_in_bytes`: live/in-use backend bytes;
- `etcd_mvcc_db_total_size_in_bytes`: physical backend bytes including reusable/free pages;
- `etcd_server_has_leader`, proposal failure/pending, leader changes;
- `etcd_disk_wal_fsync_duration_seconds` and `etcd_disk_backend_commit_duration_seconds`.

`etcd_server_alarm_common{alarm="NOSPACE"}` is useful only if the deployed exporter exposes it. Always retain `etcdctl alarm list` as the direct check. Metric names vary by etcd/exporter version; query `/metrics` or Prometheus label values rather than assuming the SOP spelling.

### Interpret sizes

Use:

- quota utilization = physical DB bytes / configured quota;
- live utilization = in-use DB bytes / configured quota;
- reclaimable fragmentation = max(physical DB bytes - in-use DB bytes, 0);
- filesystem headroom = free bytes on the filesystem that holds the data directory.

High live utilization calls for retention/key-growth reduction or a validated quota/capacity change. A large physical-versus-in-use gap indicates possible defrag benefit. A full host filesystem can remain dangerous even when backend quota usage is lower.

### Authorized recovery gate

Before compaction, defragmentation, or alarm clearing, require:

- explicit production-change authorization and maintenance/impact window;
- healthy endpoint/membership assessment and known quorum;
- a newly verified snapshot or a documented reason it cannot be taken;
- exact endpoints and TLS/auth arguments;
- current revision, alarms, DB sizes, quota, filesystem headroom, and workload impact;
- watcher/consumer risk assessment, because compaction makes older revisions unavailable;
- rollback/escalation owner and stop conditions.

The upstream recovery sequence is compact history, defragment members, then disarm the alarm. Adapt syntax to the installed version. Do not execute the following during diagnosis-only work:

~~~bash
# Example only; derive endpoint and TLS/auth flags from the environment.
REV=$(etcdctl --endpoints=<HEALTHY_ENDPOINT> endpoint status --write-out=json \
  | jq -r '.[0].Status.header.revision')
etcdctl --endpoints=<HEALTHY_ENDPOINT> compact "${REV}"

# Defragment one member, verify health, then continue to the next member.
etcdctl --endpoints=<ONE_MEMBER_ENDPOINT> defrag

# Clear only after enough space is reclaimed and all required members are checked.
etcdctl --endpoints=<ENDPOINTS> alarm disarm
~~~

Prefer one-member-at-a-time defragmentation with a health gate between members. Live defragmentation blocks reads and writes on the target member while rebuilding the backend; `defrag --cluster` can make sequencing and failure control less explicit.

Stop immediately if quorum degrades, the target does not return healthy, DB size grows unexpectedly, disk errors appear, latency breaches the approved limit, or the revision/snapshot checks are inconsistent. Do not continue to the next member.

### Validate recovery

Capture before/after evidence for:

1. every endpoint healthy, a stable leader, expected membership, consistent raft progress;
2. alarm list empty only after space is reclaimed;
3. physical/in-use DB size, quota utilization, and filesystem free space;
4. no new fsync/backend-commit latency or peer errors;
5. Alluxio Coordinator readiness and successful read-only job/status operations;
6. customer-visible job submission/update behavior only when an authorized validation write is available;
7. stable state for the agreed observation window.

An error returned during `NOSPACE` is not by itself proof that the corresponding write did not commit; etcd may detect quota at more than one layer. Verify idempotency and resulting state before retrying a customer operation.

## Capacity planning and preventive configuration

Do not promote the source SOP's `6 GB`, `1h`, `>400k jobs/day`, or `3d` examples to universal defaults. Build the plan from:

- jobs created per day and peak jobs per hour;
- average and high-percentile etcd bytes per retained job, measured in the target release;
- average revisions/updates per job and peak revision rate;
- Alluxio completed-job retention window;
- compaction mode/window and watcher catch-up requirements;
- measured BoltDB overhead/fragmentation and growth rate;
- restore-time objective, disk performance, disk capacity, and quota headroom.

Use an explicit variable model when estimating:

~~~text
retained_jobs = jobs_per_day * retention_days
live_bytes = retained_jobs * measured_live_bytes_per_job
history_bytes = peak_revisions_per_window * measured_bytes_per_revision
planned_backend_bytes = (live_bytes + history_bytes) * measured_overhead_factor
required_quota = planned_backend_bytes + operational_headroom
~~~

The Google Doc's exported formulas omit some operands, so its implied per-job byte and overhead values are unavailable. Measure them from a representative environment or obtain them from Support; do not reverse-engineer them from the sample conclusion.

For the current supplied Enterprise checkout, `alluxio.job.retention.time` has a source default of `7d`; verify the affected release's effective value. Reducing retention can lower retained job state but changes how long completed job information remains available.

Etcd v3.5 supports `periodic` and `revision` auto-compaction modes. In periodic mode, an explicit duration such as `1h` expresses a time window; a bare integer is not universally “the last N operations.” In revision mode the retention value represents revisions. Confirm the deployed version's help/configuration before changing:

~~~yaml
# Illustrative candidate, not a universal recommendation.
auto-compaction-mode: periodic
auto-compaction-retention: "1h"
quota-backend-bytes: <CAPACITY_PLAN_BYTES>
~~~

A quota increase without disk capacity, retention, growth, and restore planning only delays recurrence. A more aggressive compaction window can break slow watchers that need older revisions. Treat scheduled defragmentation as a controlled maintenance job: low-load window, one member at a time, health gate, non-overlap lock, timeout, alerting, and evidence retention. Do not deploy a blind simultaneous cron across all members.

## Support handoff fields

Include:

- incident window, business impact, and Alluxio-visible symptoms;
- Alluxio/Operator/etcd versions and deployment owner;
- topology, members, quorum, leader, endpoints, placement, PVC/data-directory mapping;
- endpoint status/health, member list, alarms, pod/service state, logs, events;
- physical/in-use DB sizes, quota, filesystem capacity/inodes, disk latency, and metric window;
- confirmed versus suspected corruption evidence;
- snapshot filename/location, creation method, status verification, and restore test date;
- every mutation proposed or executed, approver, timestamp, result, rollback, and stop condition;
- before/after Alluxio and etcd validation plus remaining unknowns.

## Source provenance

- Support Google Doc: `ETCD recovery SOP`, read on 2026-09-22. The document has one tab, duplicated English/Chinese material, missing rendered formula operands, and an unresolved comment requesting a physical-machine procedure.
- Enterprise source: current workspace checkout; `alluxio.job.retention.time` default verified in `PropertyKey.java` for that checkout.
- Upstream etcd: use the version-matched maintenance, metrics, corruption, and disaster-recovery pages linked from [source-map.md](source-map.md).
