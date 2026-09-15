# Observability and Metric Interpretation

Use this reference for performance, capacity, cache, resource, and time-series analysis. Metric availability and labels vary by release; verify the detected version against the official metrics page and the current source.

## Evidence hierarchy

1. Customer workload demand and application SLO.
2. Application latency, throughput, error, and retry rate.
3. FUSE/S3/FSSpec boundary.
4. Worker request, cache, page store, and UFS.
5. Coordinator jobs and etcd.
6. Host/container resources and external UFS metrics.

A healthy internal metric does not override a customer-visible failure. An idle workload does not prove throughput regression.

## Current metric families to look for

Search the scraped names first because Prometheus clients may expose suffixes such as _total, _count, _sum, and _bucket.

| Area | Families |
|---|---|
| Cache capacity | alluxio_cached_storage, alluxio_cached_capacity, alluxio_cached_storage_by_priority |
| Cache contents and eviction | alluxio_data_cached_pages, alluxio_data_cached_files, alluxio_eviction_by_ttl, alluxio_eviction_by_quota |
| Cached and missed reads | alluxio_cached_data_read, alluxio_missed_data_read, alluxio_ufs_fallback |
| Worker data path | alluxio_data_access, alluxio_data_throughput, alluxio_netty_operations, alluxio_netty_operation_errors |
| Metadata | alluxio_meta_operation, alluxio_meta_operation_latency_ms, alluxio_meta_operation_errors, alluxio_metadata_cache_hit_calls, alluxio_metadata_cache_miss_calls, alluxio_external_file_metadata_request_calls |
| UFS | alluxio_ufs_error, alluxio_ufs_latency_ms, alluxio_ufs_client_latency_ms, alluxio_ufs_client_call_processing |
| Page store | alluxio_page_store_operation_errors, alluxio_page_store_dir_operation_errors, alluxio_page_store_io_latency_microseconds, alluxio_page_store_dir_healthy, alluxio_page_store_dir_unavailable_bytes, alluxio_page_store_dir_verdict |
| Worker pressure | alluxio_worker_thread_pool_rejections, alluxio_worker_active_operations, alluxio_netty_in_progress_read_requests, alluxio_netty_wedged_read_requests, alluxio_netty_direct_memory_usage |
| Membership | alluxio_worker_membership, alluxio_worker_membership_refresh_count, alluxio_cumulative_unavailable_workers |
| FUSE | alluxio_fuse_call_latency_ms, alluxio_fuse_authz_latency_ms, alluxio_fuse_concurrency, alluxio_fuse_aborted_requests, alluxio_fuse_result, alluxio_fuse_blocking_calls |
| Jobs | alluxio_active_job_count, alluxio_worker_job_task_count, alluxio_scheduler_queue_size, alluxio_scheduler_job_failures, alluxio_scheduler_task_failures, alluxio_scheduler_task_retries, alluxio_scheduler_job_duration_ms |
| Coordinator and etcd | alluxio_scheduler_etcd_poll, alluxio_scheduler_etcd_claim, alluxio_scheduler_etcd_reclaim, alluxio_scheduler_etcd_latency_ms, alluxio_scheduler_job_access_etcd |
| License/version | alluxio_license_expiration_date, alluxio_version_info |

These names are a navigation aid, not a promise that every version exposes every family.

## Query safely

First discover actual names:

~~~promql
{__name__=~"alluxio_(cached|missed|ufs|data|netty|worker|fuse|scheduler|page_store).*"}
~~~

Useful patterns after labels and suffixes are verified:

~~~promql
# Cache utilization by selected cluster/workers
sum(alluxio_cached_storage) / sum(alluxio_cached_capacity)

# Counter throughput or errors over a five-minute window
sum by (job, instance) (rate(<COUNTER_SERIES>[5m]))

# Counter increase across the incident window
sum by (job, instance) (increase(<COUNTER_SERIES>[30m]))

# Histogram P99 after confirming the bucket series and labels
histogram_quantile(
  0.99,
  sum by (le, job) (rate(<HISTOGRAM_BUCKET_SERIES>[5m]))
)

# Detect scrape gaps
count_over_time(up{job=~".*alluxio.*"}[30m])
~~~

Never paste these blindly. Add cluster/namespace/component selectors to prevent cross-cluster aggregation.

## Interpretation rules

- Counter: use rate or increase; account for resets after restarts.
- Gauge: inspect level and duration; aggregate only semantically compatible instances.
- Histogram: calculate quantiles from buckets. Do not average precomputed percentiles.
- Missing series: distinguish component not deployed, scrape failure, renamed metric, and true absence.
- Zero: verify target and workload were present.
- Cardinality: keep component, cluster, namespace, instance, method, result/state, destination, UFS type, and directory labels when they change meaning.
- Time: use a common time zone and mark scrape interval.
- Baseline: compare with the same workload phase, dataset, concurrency, cache warmth, and ring size.

## Causal correlations

| Observation | Correlate with | Interpretation to test |
|---|---|---|
| Cached reads fall, missed reads/UFS fallback rise | Worker membership, eviction, workload change | Cold cache, ring change, or capacity pressure |
| UFS latency rises with stable Worker resources | UFS provider, network, connection pool | External or connection-path bottleneck |
| Worker errors rise with page-store latency/health change | disk device, filesystem capacity, kernel log | Local cache device problem |
| FUSE P99 rises but Worker/UFS are stable | FUSE concurrency, CPU throttling, blocking calls | Client-side/FUSE saturation |
| Netty errors and direct memory rise | cgroup limit, JVM flags, buffer/connection behavior | Memory or transport pressure |
| Job queue/retries rise | Coordinator CPU, etcd latency, Worker task capacity | Scheduler or dependency bottleneck |
| CPU rises while request rate is flat | GC, logs, thread dump, retry loop | Internal amplification rather than workload |
| UFS writes absent after acknowledgement | persist backlog/failure, FDB, Worker restart | Write-cache durability delay or failure |

## Threshold discipline

The supplied SOP includes useful operational reference points such as resource watermarks and warm-cache hit-rate targets. Do not promote them to universal product guarantees.

For every threshold in a conclusion, label it as one of:

- customer SLO;
- environment baseline;
- documented product default;
- runbook heuristic;
- test assumption.

State the observation duration. Short spikes, scheduled jobs, cache warm-up, and rolling changes require different interpretation from sustained degradation.

## Minimal performance conclusion

Report:

- workload phase and demand;
- affected path and time window;
- P50/P95/P99 latency, throughput, error and timeout rate;
- cache hit/miss/fallback and eviction;
- Worker, page-store, UFS, FUSE/S3, Coordinator/etcd, and node saturation;
- the narrowest proven bottleneck;
- confidence and remaining discriminator;
- proposed change, expected effect, risk, rollback, and re-test plan.
