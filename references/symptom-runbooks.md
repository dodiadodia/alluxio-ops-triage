# Symptom and Component Runbooks

Use this reference after version, deployment mode, access mode, cache mode, incident window, and affected scope are known. Each section gives a diagnostic route, not permission to recover or change production.

## Cross-component first pass

For every incident:

1. Preserve application and affected component current/previous logs, pod Last State, events, configuration, version, and the relevant metric window.
2. Confirm whether the path is FUSE/CSI, S3 API, FSSpec, or mixed.
3. Check Worker membership and readiness, Coordinator/job state, etcd health, page-store health, and UFS errors.
4. If write cache is enabled, add FDB health and asynchronous persistence.
5. Build a UTC timeline and identify the earliest abnormal event.

Use the table to choose the first discriminating evidence:

| Symptom | First discriminator | Do not assume |
|---|---|---|
| Entire cluster or job service unavailable | Coordinator readiness plus etcd health and leader | Every client I/O path depends on Coordinator in the same way |
| Worker restarts or membership flaps | Last State, previous log, cgroup/node event, Worker identity | OOMKilled always means Java heap exhaustion |
| ENOTCONN / Transport endpoint | FUSE process and mount lifecycle on the same node | UFS is the primary cause |
| EIO / Input/output error | FUSE log, Worker request error, UFS/page-store evidence | EIO identifies the failed backend |
| File not found or wrong content | Exact UFS object plus mount mapping and metadata/cache state | The file is absent in UFS |
| 403 / signature error | Endpoint, region, credential source, time, UFS or S3 API layer | Keys must be rotated |
| Cache hit or throughput drop | Workload demand, Worker membership, cache/eviction, UFS and disk latency | A static global threshold proves regression |
| Load Job slow or failed | Job failure details, scheduler, UFS, Worker and page store | More concurrency will improve it |
| Etcd alarm or no leader | Quorum, endpoint health/status, disk and DB size | Deleting PVCs is an acceptable first response |
| Writes missing in UFS | Write-cache mode, FDB, persist state/backlog, Worker failure | Client acknowledgement equals UFS durability |

## Coordinator or job service unavailable

Evidence:

- pod readiness, restart count, Last State, current and previous logs;
- image/version, JVM flags, requests/limits, node pressure;
- etcd endpoint health, leader and latency;
- Coordinator job-store mode and scheduler metrics;
- alluxio job list and alluxio info nodes;
- recent upgrade, scaling, ConfigMap, license, or job-volume changes.

Hypotheses to distinguish:

- container or JVM memory failure;
- process deadlock, long GC, CPU throttling, file descriptor or thread exhaustion;
- etcd unavailable or slow;
- job queue/scheduler saturation;
- corrupted or incompatible persisted job state;
- version or configuration mismatch;
- license or startup validation failure.

Do not restart solely because the CLI hangs. First determine whether the Coordinator endpoint, etcd, DNS/network, or the client command is failing. A Coordinator issue can affect job management differently from an already established data path; describe the observed impact rather than generalizing.

Recovery proposals such as restart, job rerun, job-store repair, or configuration changes require evidence capture and explicit authorization.

## Worker instability, restart, or membership fluctuation

Evidence:

- pod Last State, exit code, reason, previous log, events, and node;
- heap, direct memory, native/FUSE overhead where relevant, cgroup limit, node OOM;
- CPU throttling, thread-pool rejection, active/wedged requests, open files;
- page-store filesystem capacity, inode use, I/O latency, health verdict, and errors;
- Worker ID/identity file persistence and duplicate identity errors;
- etcd connectivity and membership refresh;
- UFS latency/errors and traffic shift after the Worker disappears;
- whether write cache is enabled and unpersisted writes existed.

Interpret carefully:

- OOMKilled or exit 137 proves cgroup/kernel termination, not which memory pool grew.
- Java OutOfMemoryError identifies a memory domain only when the message and surrounding evidence are retained.
- No space left must be mapped to page store, etcd, logs, root disk, or temp space.
- Duplicate Worker ID can come from cloned identity state or conflicting persistent volumes.
- Cache survival after a restart depends on page-store and identity persistence.

Validate any recovery with stable readiness/restart counts, expected ONLINE Worker count, error cessation, UFS load, cache behavior, and write durability when applicable.

## FUSE or CSI mount failure

Decisive signals:

- ENOTCONN / Transport endpoint is not connected: kernel mount exists but the serving FUSE process is absent or disconnected.
- EIO: the FUSE boundary returned an error; root cause may be FUSE, Worker, page store, network, metadata, or UFS.
- application pod Pending or ContainerCreating: inspect PVC/PV, CSI controller, nodeplugin, kubelet, and per-volume FUSE lifecycle.

Evidence sequence:

1. Application pod volume, PVC/PV, node, events, exact errno, and timestamp.
2. Per-volume or DaemonSet FUSE pod on the same node; init containers, Last State, current/previous log.
3. CSI nodeplugin NodePublish/NodeUnpublish log on the same node.
4. CSI controller recovery/delete/recreate events.
5. Worker and UFS evidence at the same time.
6. Kubelet and retained host logs if container history is gone.

Check for mount stacking and stale references without traversing the mount. Use mount, findmnt if available, df, and one exact known-file stat. Do not use ls/find/du on the mounted tree.

Deleting a FUSE pod, force-unmounting, deleting the application pod, or changing mount options is a recovery action that requires customer coordination.

## File not found, stale metadata, or wrong content

Evidence sequence:

1. Confirm the exact requested URI/path and access mode.
2. Verify the exact object/file in UFS with an approved read-only HEAD/stat operation.
3. Verify Alluxio mount mapping and path translation.
4. Compare size, modification time, generation/etag when available, and relevant cache metadata.
5. Check metadata cache expiry/refresh configuration and recent UFS changes.
6. Check Worker membership, partial read, page-store, and UFS errors.
7. For replicas or write cache, check consistency and persistence state.

Distinguish:

- object truly absent in UFS;
- wrong mount, bucket, prefix, endpoint, tenant, or credentials;
- stale positive/negative metadata;
- cached content from an earlier UFS generation;
- partial read or unhealthy Worker/page store;
- write acknowledged but not persisted, or persist failed.

Do not clear cache, run a Free Job, force metadata refresh, or rewrite the object until the authoritative UFS state and customer consistency requirement are confirmed.

## UFS access, authentication, or latency

Classify the failing layer:

- DNS, route, security group/network policy, proxy, or TLS;
- endpoint, region, addressing mode, or protocol mismatch;
- credential discovery, expiration, signing, IAM/policy, or clock skew;
- UFS throttling, connection-pool exhaustion, server error, or slow response;
- Alluxio Worker resource, thread, or buffer pressure before the UFS call;
- wrong mount mapping or unsupported operation.

Evidence:

- exact error code/message and component emitting it;
- resolved endpoint and region with credentials redacted;
- credential source type and expiry, never the secret;
- time synchronization;
- UFS error and latency metrics by method/type;
- Worker request concurrency, pool/thread pressure, CPU, direct memory;
- UFS provider metrics and limits when available.

AccessDenied and SignatureDoesNotMatch are not interchangeable. Connection refused and timeout are not interchangeable. Preserve the full cause chain and HTTP status.

Do not run a write-capable UFS test or change credentials during a diagnosis-only task.

## Cache miss, UFS fallback, or read-performance regression

Confirm there is active workload demand, then compare:

- application throughput/latency;
- FUSE or S3 API operations and latency;
- Worker data throughput, cached reads, missed reads, and UFS fallback;
- cache storage/capacity, eviction, metadata hits/misses;
- Worker membership/ring changes;
- page-store health and I/O latency;
- UFS latency/errors and provider throttling;
- CPU, memory, direct memory, network, threads, queues, and open files.

Common mechanisms:

- cold start or workload working-set change;
- Worker add/remove/restart causing ring reshaping;
- cache capacity pressure and eviction churn;
- unhealthy or slow page-store device;
- metadata cache misses even when data pages exist;
- path/mount/tenant mismatch bypassing expected cached data;
- UFS/network slowdown dominating miss latency;
- FUSE or Worker concurrency saturation.

Avoid recommending capacity expansion solely from utilization. Prove that eviction or misses affect the active working set and that disk or UFS behavior explains the customer impact.

## S3 API errors or throughput

The Worker S3 API path does not use FUSE or CSI. Confirm:

- application endpoint and port, DNS/TLS, and reachability;
- HTTP status, S3 error code, request operation, bucket/key, request ID, and time;
- whether the bucket/prefix is mounted and visible in the intended Alluxio cluster;
- credential/signing path and region;
- Worker S3 handler log, request concurrency, CPU, direct memory, thread/pool rejection;
- cache/page-store behavior and UFS connection/latency/errors;
- multipart or streaming upload state for writes;
- component version and whether the configured property name exists in that release.

For 404, distinguish NoSuchBucket, NoSuchKey, and unmounted-path behavior by version. For 5xx, inspect the Worker cause before blaming UFS. For 403, identify whether rejection came from Alluxio/gateway policy or the underlying store.

## Load Job slow, stuck, or failed

Evidence:

- exact command and flags, path/index source, submit time, job state, progress, failure files/reasons;
- Coordinator scheduler queue, claims/retries, active jobs, etcd latency;
- Worker task count/concurrency, thread rejection, CPU/memory/direct memory;
- UFS throughput, latency, error/throttling and connection pool;
- page-store capacity, reserved space, eviction, health, and write latency;
- file count and size distribution, listing latency, and partition/batch settings;
- ring changes or scaling during the job.

Analyze in order:

1. UFS listing/read and provider limit.
2. Coordinator scheduler and etcd.
3. Worker task admission and resources.
4. Page-store write path and capacity.
5. Job partition, batch, replica, verify, and skip behavior.

More parallelism can worsen UFS throttling, Worker memory, page-store contention, or small-file overhead. Tune only the proven bottleneck. Submitting, stopping, rerunning, rebalancing, or changing a job is a mutation.

## Etcd unavailable, alarmed, or out of space

Evidence:

- replica count, placement, readiness, restarts, PVCs and disk;
- endpoint health/status, leader, raft term/index, DB size and alarms;
- logs for no leader, slow apply, fsync/disk latency, quota exceeded, corruption, TLS or network;
- Alluxio membership/mount/job symptoms and duration;
- last valid backup/snapshot and restore procedure.

For a three-member cluster, quorum requires two healthy members. Do not generalize that every pod marked Running is a healthy member.

Recovery order must be release- and topology-specific. Never delete PVCs or host data as an initial fix. Before compact/defrag, restore, member replacement, or rebuild, require a verified backup, endpoint health assessment, one-member-at-a-time plan where applicable, configuration inventory, rollback, and explicit approval.

## Write cache, FoundationDB, or missing persisted writes

First prove write cache is enabled from configuration and FDB presence. Capture:

- FDB cluster health, availability, reconciled generation, process/pod state, and logs;
- Worker write-path errors, restarts/OOM, page-store health/capacity;
- asynchronous persist tasks, backlog, age, retries, and failures;
- client acknowledgement time versus UFS object visibility;
- exact file/object state in cache, FDB metadata, and UFS;
- recent failover, decommission, restart, or scale event.

Treat confirmed unpersisted data plus Worker loss as a potential data-loss incident and escalate severity based on customer impact. Do not claim loss from absence in UFS alone while persistence may still be pending.

Do not clear locks, resolve metadata, decommission Workers, import/export write-cache state, or run fsck without explicit authorization and a version-matched procedure.

## High CPU, logging, or apparent idle saturation

Correlate CPU with request rate, thread states, GC, log rate and size, storage/network I/O, and throttling. Check:

- whether workload changed;
- which process/container and threads consume CPU;
- log message frequency and stack trace amplification;
- logging configuration actually mounted and loaded;
- known release-specific logging issue;
- compression, rotation, and disk pressure;
- busy loops, retry storms, or connection failures.

Do not apply a generic Log4j file or lower logging without verifying the release and preserving enough diagnostics. A logging change often requires a restart and can hide evidence.

## Recovery closure

Do not declare resolved until:

- affected components are Ready and restart counts remain stable for the agreed window;
- Worker membership and dependent services match expected topology;
- the original error no longer occurs;
- an exact known-path or application canary passes without broad FUSE traversal;
- metrics recover relative to workload baseline;
- jobs and asynchronous persistence are healthy where relevant;
- data consistency/durability is verified;
- temporary changes and residual risks are recorded.
