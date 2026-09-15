# Source Map and Freshness Rules

Use this reference when a command, configuration property, metric, resource kind, port, default, or recovery step may vary by version.

## Authority and version pinning

1. Detect the Alluxio image/version and Operator version from the environment or bundle.
2. Prefer the official page for that version. Use the unversioned Enterprise AI documentation only when it matches the detected release line.
3. Confirm CLI syntax with the installed binary's --help output or the matching source revision.
4. Confirm Kubernetes resource fields with kubectl api-resources and kubectl explain before preparing YAML.
5. Treat values in the SOP as operational guidance, not immutable product defaults.

Record the documentation URL and access date in a Support report when it affects the recommendation.

This skill was initially reconciled against the unversioned documentation on 2026-09-15. That date is provenance, not a freshness guarantee; re-check the site for each version-sensitive incident.

## Official documentation entry points

- Product overview: https://documentation.alluxio.io/ee-ai-en
- Troubleshooting and Diagnostic Snapshot: https://documentation.alluxio.io/ee-ai-en/administration/troubleshooting-alluxio
- Monitoring: https://documentation.alluxio.io/ee-ai-en/administration/monitoring-alluxio
- Metrics reference: https://documentation.alluxio.io/ee-ai-en/reference/metrics
- Production and lifecycle administration: https://documentation.alluxio.io/ee-ai-en/administration/managing-alluxio
- Coordinator and job scheduling: https://documentation.alluxio.io/ee-ai-en/administration/managing-coordinators
- Kubernetes installation and Operator resources: https://documentation.alluxio.io/ee-ai-en/start/installing-on-kubernetes
- Docker and bare-metal deployment: https://documentation.alluxio.io/ee-ai-en/start/installing-on-docker

The documentation site exposes versioned branches under paths such as /ee-ai-en/ai-3.7/. Search for the detected version rather than assuming the current page applies.

## Enterprise source checkout

When an Enterprise checkout is available, start at these paths:

| Question | Source path |
|---|---|
| CLI groups and current flags | enterprise/cli/cmd/ |
| Version and Worker status commands | enterprise/cli/cmd/info/ |
| Load, free, list, rerun, and rebalance jobs | enterprise/cli/cmd/job/ |
| UFS mount commands | enterprise/cli/cmd/mount/ |
| Worker removal/decommission | enterprise/cli/cmd/process/ |
| Write-cache and FDB diagnostics | enterprise/cli/cmd/writecache/ |
| Filesystem stat/location/check-cached | enterprise/cli/cmd/fs/ |
| Configuration keys and defaults | enterprise/dora/core/common/src/main/java/alluxio/conf/PropertyKey.java |
| Metric names and labels | enterprise/dora/core/common/src/main/java/alluxio/metrics/MultiDimensionalMetricsSystem.java |
| Local data collector | enterprise/bin/collectinfo.sh |
| Full collectinfo analyzer | enterprise/dev/scripts/collectinfo-analyzer/analyze_collectinfo.py |
| Analyzer tests | enterprise/dev/scripts/collectinfo-analyzer/test_analyze_collectinfo.py |
| Existing deep Kubernetes triage material | enterprise/.claude/skills/alluxio-cluster-triage/SKILL.md |

If enterprise/.codegraph/ exists, use CodeGraph before text search to locate symbols and call paths. For exact CLI usage, inspect the Cobra Use, flags, examples, and Run translation in the matching file.

## Supplied SOP coverage

The supplied Alluxio 标准操作手册（SOP）大纲.docx contributes these operational patterns:

- daily health inspection and Diagnostic Snapshot collection;
- Coordinator, Worker, file-not-found, UFS, CSI FUSE, logging CPU, and Load Job incidents;
- client fallback, FUSE, S3 API, load performance, and write-cache performance;
- etcd node, capacity, Coordinator, Worker, and FUSE recovery;
- pre-change checks, rollback, evidence retention, incident timelines, Support escalation, and recovery verification.

Known reconciliation points:

- Current documentation may use a doctor-controller while the custom resource kind remains CollectInfo. Verify both from the installed cluster.
- Worker cache survival depends on page-store and Worker identity persistence; do not assume every restart loses or preserves cache.
- A recursive ls against a FUSE mount is unsafe during degradation even if an older checklist suggests listing a test directory.
- Resource thresholds and recommended sizes require workload baseline and release-specific validation.
