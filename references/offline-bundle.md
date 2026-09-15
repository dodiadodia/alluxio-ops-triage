# Offline Diagnostic Bundle Analysis

Use this reference for a Diagnostic Snapshot, collectinfo archive, extracted bundle, or a directory of logs and configuration.

## 1. Preserve and isolate the evidence

- Work on a copy in an approved incident directory.
- Record filename, size, SHA-256, source, collection time, and stated incident window.
- Treat archive paths and file contents as untrusted input.
- Do not execute scripts or binaries from the bundle.
- Do not upload or forward the archive without explicit authorization.
- Keep the original unchanged; write summaries separately.

For an archive:

~~~bash
shasum -a 256 <SNAPSHOT.tar.gz>
python3 <SKILL_DIR>/scripts/analyze_bundle.py <SNAPSHOT.tar.gz> \
  --output <INCIDENT_DIR>/bundle-summary.md
~~~

The bundled analyzer reads tar members without extracting them, rejects unsafe member paths, limits bytes read, and redacts common secret forms in excerpts.

If the Enterprise checkout and its Python dependencies are available, the fuller analyzer can add metrics, configuration, job, and feature summaries:

~~~bash
python3 enterprise/dev/scripts/collectinfo-analyzer/analyze_collectinfo.py \
  -p <SNAPSHOT.tar.gz> -o <INCIDENT_DIR>/enterprise-analysis.txt
~~~

Do not install dependencies globally. Use an existing project environment or an isolated virtual environment when installation is explicitly in scope.

## 2. Inventory before interpretation

Expected evidence categories include:

| Category | What it can establish |
|---|---|
| meta | collection version, cluster identity, bundle time window |
| config | effective properties, images, resources, mount definitions |
| hardware | node and pod state, CPU, memory, disk, kernel context |
| etcd | membership, mount, quota, TTL, priority, and license state |
| logs | component lifecycle, errors, retries, and recovery |
| metrics | time-series behavior and cross-component correlation |
| job-history | Load, Free, Copy, Move, Rebalance state and failure details |

Names and contents vary by Operator release. Mark missing categories explicitly; absence of a category does not imply health.

## 3. Establish the environment facts

Extract, with evidence paths:

- Alluxio, Operator, CSI, etcd, and FDB versions;
- deployment and access modes;
- component counts and restart/termination state;
- page-store type, capacity, backing volume, and persistence;
- Worker identity persistence;
- UFS type and mount topology without revealing credentials;
- write-cache/FDB presence;
- incident and bundle time zones;
- metric time range and scrape gaps.

Flag mixed Alluxio versions unless a documented rolling upgrade explains them.

## 4. Analyze in causal order

1. Application-visible symptom and time.
2. FUSE/S3/FSSpec boundary.
3. CSI lifecycle and node mount state for FUSE.
4. Worker request, cache, page-store, network, and UFS evidence.
5. Coordinator and job service state.
6. Etcd membership, leader, latency, alarms, and capacity.
7. FDB and asynchronous persistence for write cache.
8. Node resource pressure, OOM, disk, network, and time synchronization.
9. Recent deployment, configuration, scaling, or workload changes.

Build a single UTC timeline. Retain original timestamps and time zones in the evidence table. Client retries can delay the visible error, so search before the reported symptom.

## 5. Log analysis rules

- Read the surrounding startup and recovery context, not only ERROR lines.
- Group repeated messages by normalized signature, but retain first and last time, count, component, and representative file/line.
- Distinguish primary failure, retry noise, cleanup noise, and unrelated historical errors.
- Prefer current and previous container logs together.
- OOMKilled or exit 137 is evidence of termination, not by itself proof of heap exhaustion; correlate JVM, direct memory, cgroup, and node events.
- Connection refused identifies a failed endpoint at that moment; it does not identify why the endpoint failed.
- AccessDenied or signature errors indicate an authentication/authorization or signing path; verify endpoint, region, credential source, and clock before prescribing key rotation.
- No space left must be tied to the exact filesystem: page store, etcd volume, logs, root disk, or temporary space.

## 6. Metrics analysis rules

- Check that the series overlaps the incident window and has expected scrape continuity.
- Treat counters as rates or deltas over a stated interval.
- Aggregate only after understanding labels and component cardinality.
- Correlate request/throughput changes with workload presence to avoid treating idle time as failure.
- Compare P50/P95/P99, error rate, CPU, memory, disk latency, direct memory, thread/queue pressure, cache utilization, eviction, UFS fallback, and job throughput.
- Use the customer's baseline or SLO. Documentation defaults and SOP thresholds are reference points, not universal acceptance criteria.
- Treat zero, missing, stale, and reset series differently.

Read [observability.md](observability.md) for metric families and safe query patterns.

## 7. Configuration analysis rules

- Separate explicit settings from defaults and resolved runtime settings.
- Compare the AlluxioCluster/ConfigMap with the live JVM command line when both exist.
- Flag unknown or unrecognized properties, conflicting old/new property names, and component version mismatches.
- Check resource requests/limits against heap, direct memory, native/FUSE overhead, kernel page cache, and observed peaks.
- Check page-store size plus reserved space against the backing filesystem.
- Do not copy literal secret values into the report.

## 8. Produce hypotheses, not keyword verdicts

For each candidate cause, list:

- two or more independent supporting signals when possible;
- material contradicting evidence;
- the earliest causal event;
- customer impact mechanism;
- safest missing discriminator;
- confidence level.

Examples of useful multi-signal correlations:

- OOMKilled + memory limit + JVM/direct-memory configuration + rising memory before termination;
- ENOTCONN + FUSE process disappearance + CSI recovery event on the same node;
- UFS latency/error rise + cache miss/fallback rise + stable Worker resources;
- job slowdown + saturated UFS or page-store I/O + queue/thread evidence;
- write acknowledged + persistence backlog/failure + absent object in UFS.

## 9. Support handoff

Use [report-template.md](report-template.md). Cite bundle paths and line numbers or metric series for every important conclusion. Include:

- original archive checksum and collection window;
- analyzer outputs;
- redacted configuration;
- exact missing categories;
- suspected root cause and confidence;
- reproduction or workload context;
- safe next checks;
- mutation proposals with impact, rollback, and validation.
