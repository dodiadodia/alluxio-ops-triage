# Live Environment Triage

Use this reference for live Kubernetes incidents. Commands are templates: replace every placeholder, verify the current context and namespaces, and capture output to an approved incident workspace. Do not execute mutation sections during a diagnosis-only request.

## 1. Verify scope and identity

~~~bash
kubectl config current-context
kubectl cluster-info
kubectl get alluxiocluster -A
kubectl get pods -A -l app.kubernetes.io/component=doctor-controller -o wide
kubectl get pods -A -l app.kubernetes.io/component=csi-controller -o wide
~~~

Derive, do not assume:

- <ALX_NS>: namespace containing the AlluxioCluster resource and Alluxio components;
- <OP_NS>: namespace containing the Operator, CSI controllers, and doctor-controller;
- <CLUSTER>: AlluxioCluster name;
- <APP_NS>, <APP_POD>, and <NODE>: affected workload and node.

If labels are customized, list resources and select them from names, owners, images, and the AlluxioCluster status. Record ambiguity.

## 2. Detect version and topology

~~~bash
kubectl -n <ALX_NS> get alluxiocluster <CLUSTER> -o wide
kubectl -n <ALX_NS> get pods -o wide
kubectl -n <ALX_NS> get pods \
  -o custom-columns='NAME:.metadata.name,COMPONENT:.metadata.labels.app\.kubernetes\.io/component,IMAGE:.spec.containers[*].image,NODE:.spec.nodeName'
kubectl -n <ALX_NS> exec <COORDINATOR_POD> -- alluxio info version
kubectl -n <ALX_NS> exec <COORDINATOR_POD> -- alluxio info nodes
kubectl -n <ALX_NS> get alluxiocluster <CLUSTER> -o yaml
kubectl api-resources | rg -i 'alluxio|collectinfo|doctor|foundationdb'
~~~

Before sharing YAML, redact literal credentials and customer-sensitive paths. Preserve image tags, component counts, resource settings, volume types, node selectors, page-store settings, Worker identity settings, UFS type, FDB presence, and status conditions.

Classify:

- deployment: Operator, Docker, or bare metal;
- access: FUSE/CSI, S3 API, FSSpec, or mixed;
- cache: read only, or write cache with FDB;
- page store: hostPath, PVC, or other, and whether it survives a pod restart;
- Worker identity: persistent or ephemeral;
- version consistency across Coordinator, Worker, FUSE, and supporting services.

## 3. Freeze the incident timeline

Use an RFC3339 UTC start time that begins before the first reported symptom. Keep the original time zone in the report.

~~~bash
kubectl -n <APP_NS> describe pod <APP_POD>
kubectl -n <APP_NS> logs <APP_POD> --all-containers --timestamps --since-time=<RFC3339_UTC>
kubectl -n <APP_NS> logs <APP_POD> --all-containers --timestamps --since-time=<RFC3339_UTC> --previous
kubectl -n <APP_NS> get events --field-selector involvedObject.name=<APP_POD> --sort-by=.lastTimestamp
kubectl -n <APP_NS> get pod <APP_POD> -o jsonpath='{.spec.nodeName}{"\n"}{.status.containerStatuses}{"\n"}'
~~~

The --previous request can fail when Kubernetes deleted and recreated a pod instead of restarting the container. Record that as a data gap and pivot to CSI controller logs, node logs, retained hostPath logs, and the Diagnostic Snapshot.

For every affected Alluxio pod, capture before recovery:

~~~bash
kubectl -n <ALX_NS> describe pod <POD>
kubectl -n <ALX_NS> logs <POD> --all-containers --timestamps --since-time=<RFC3339_UTC>
kubectl -n <ALX_NS> logs <POD> --all-containers --timestamps --since-time=<RFC3339_UTC> --previous
~~~

Do not filter to ERROR only on the first pass. Startup, leader election, retry, recovery, and termination context often appears at INFO or WARN.

## 4. Determine the actual access path

Inspect workload volumes, mounts, image arguments, and non-secret endpoint configuration:

~~~bash
kubectl -n <APP_NS> get pod <APP_POD> \
  -o jsonpath='{.spec.volumes}{"\n"}{.spec.containers[*].volumeMounts}{"\n"}{.spec.containers[*].args}{"\n"}'
kubectl -n <APP_NS> get pvc
kubectl get pv <PV_NAME> -o yaml
~~~

FUSE evidence includes an Alluxio CSI volume/PVC and a fuse.alluxio mount. S3 evidence includes an Alluxio Worker or gateway endpoint used by the application. Some workloads use both.

Safe checks inside an application pod:

~~~bash
kubectl -n <APP_NS> exec <APP_POD> -- df -h
kubectl -n <APP_NS> exec <APP_POD> -- mount
kubectl -n <APP_NS> exec <APP_POD> -- stat <EXACT_KNOWN_FILE>
~~~

Do not run ls, find, du, recursive globbing, or a directory checksum on an Alluxio FUSE mount.

## 5. FUSE and CSI correlation

Map the application pod to its node, then find the per-volume FUSE pod and CSI nodeplugin on that same node:

~~~bash
kubectl get pods -A --field-selector spec.nodeName=<NODE> -o wide | rg -i 'alluxio|fuse|csi'
kubectl -n <OP_NS> get pod -l app.kubernetes.io/component=csi-nodeplugin \
  --field-selector spec.nodeName=<NODE> -o wide
kubectl -n <OP_NS> logs <CSI_NODEPLUGIN_POD> -c csi-nodeserver \
  --timestamps --since-time=<RFC3339_UTC>
kubectl -n <OP_NS> logs -l app.kubernetes.io/component=csi-controller \
  --all-containers --prefix --timestamps --since-time=<RFC3339_UTC>
~~~

Correlate:

- application errno and retry timing;
- FUSE termination, JVM, UFS, and Worker RPC errors;
- CSI NodePublish/NodeUnpublish and mount errors;
- CSI controller recovery, deletion, and recreation events;
- kubelet mount references and pod lifecycle when available.

ENOTCONN strongly indicates a stale kernel mount or absent FUSE process. EIO only locates the failure at the filesystem boundary; continue through Worker and UFS evidence.

## 6. Worker, Coordinator, jobs, and UFS

~~~bash
kubectl -n <ALX_NS> get pod -l app.kubernetes.io/component=worker -o wide
kubectl -n <ALX_NS> get pod -l app.kubernetes.io/component=coordinator -o wide
kubectl -n <ALX_NS> top pod
kubectl -n <ALX_NS> exec <COORDINATOR_POD> -- alluxio info nodes
kubectl -n <ALX_NS> exec <COORDINATOR_POD> -- alluxio job list --job-type ALL --job-state ALL
kubectl -n <ALX_NS> exec <COORDINATOR_POD> -- alluxio mount list
kubectl -n <ALX_NS> exec <COORDINATOR_POD> -- alluxio license status
~~~

Use alluxio --help and the relevant subcommand --help if the installed version rejects a command. Do not infer that the service is unhealthy from a CLI mismatch.

For a specific Load Job, use its exact path or identifier and read-only progress/list operations. Submitting, stopping, rerunning, freeing, rebalancing, or changing batch size is a mutation.

Do not run ufsTest, ufsIOTest, worker-benchmark, FUSE read/write tests, or a load job during diagnosis without authorization. These commands can create data or impose material load.

## 7. Etcd and write-cache dependencies

For an etcd-specific incident, also read [etcd-operations.md](etcd-operations.md). It defines the quorum, `NOSPACE`, corruption, snapshot, and destructive-recovery gates that the generic checks below do not cover.

First identify replica count, placement, PVC state, and whether the incident involves Alluxio membership/mount metadata, Coordinator job state, or FDB-backed write cache.

~~~bash
kubectl -n <ALX_NS> get pod -l app.kubernetes.io/component=etcd -o wide
kubectl -n <ALX_NS> get pvc
kubectl -n <ALX_NS> logs <ETCD_POD> --timestamps --since-time=<RFC3339_UTC>
kubectl -n <ALX_NS> exec <ETCD_POD> -- etcdctl endpoint health --cluster
kubectl -n <ALX_NS> exec <ETCD_POD> -- etcdctl endpoint status --cluster -w table
kubectl -n <ALX_NS> get foundationdbcluster -o wide
~~~

If the etcd image requires TLS flags or explicit endpoints, derive them from the pod configuration without printing secret values. Never compact, defragment, restore, delete PVCs, or clear host paths as part of a read-only investigation.

For write cache, capture FDB health, Worker restart/OOM evidence, asynchronous persistence backlog or failures, and UFS visibility. A successful client write does not prove the data is already durable in UFS.

## 8. Diagnostic Snapshot

Creating a one-time snapshot changes cluster state by creating a custom resource. Do it only when collection is requested or authorized.

Before preparing YAML:

~~~bash
kubectl api-resources | rg -i 'collectinfo|doctor'
kubectl explain collectinfo.spec
kubectl -n <OP_NS> get pod -l app.kubernetes.io/component=doctor-controller
kubectl -n <ALX_NS> get collectinfo
~~~

The current unversioned documentation uses a doctor-controller and a CollectInfo resource. Older releases may use a collectinfo-controller and store results in the Coordinator. Verify the installed CRD and controller.

Minimal one-time template, after validation:

~~~yaml
apiVersion: k8s-operator.alluxio.com/v1
kind: CollectInfo
metadata:
  name: incident-<UTC_TIMESTAMP>
  namespace: <ALX_NS>
spec:
  scheduled:
    enabled: false
  type:
    - all
  logs:
    sinceTime: "<RFC3339_UTC>"
  metrics:
    duration: <DURATION>
    step: <STEP>
~~~

Check field support with kubectl explain. Do not combine tail with sinceSeconds or sinceTime unless the installed schema and documentation say how precedence works.

After authorization:

~~~bash
kubectl apply --dry-run=server -f <COLLECTINFO_YAML>
kubectl apply -f <COLLECTINFO_YAML>
kubectl -n <ALX_NS> get collectinfo -w
~~~

Downloading the completed archive is read-only from the cluster but writes locally:

~~~bash
kubectl -n <OP_NS> get pod -l app.kubernetes.io/component=doctor-controller
kubectl -n <OP_NS> exec <DOCTOR_POD> -- ls /data/doctor
kubectl -n <OP_NS> cp <DOCTOR_POD>:/data/doctor/<SNAPSHOT_FILE> <LOCAL_APPROVED_PATH>
shasum -a 256 <LOCAL_APPROVED_PATH>
~~~

For older releases, verify whether the archive is under /mnt/alluxio/metastore/collectinfo in the Coordinator.

## 9. Mutation gate

Do not perform these operations merely because they appear in a runbook:

| Action | Primary risk | Required preparation |
|---|---|---|
| Delete/restart FUSE, Worker, or Coordinator pod | Interruption, cache miss surge, lost Last State evidence | Evidence capture, workload impact, recovery owner, rollback or reschedule path |
| Change any Alluxio property through `*.properties`, ConfigMap, AlluxioCluster, Helm, environment, JVM `-D`, or startup arguments | Rolling restart, incompatible or unsafe configuration, wider-than-expected scope | Exact current/effective source and proposed diff, version evidence, impact, rollout, validation, rollback, and explicit manual approval of those exact keys/values by an Alluxio expert |
| Edit non-property ConfigMap or AlluxioCluster fields | Rolling restart or incompatible configuration | Export current object, validate schema, maintenance window, restore plan |
| Stop/rerun/load/free/rebalance a job | Incomplete coverage, UFS load, cache deletion, data-path impact | Exact target, job state, bandwidth/capacity check, validation |
| Etcd compact/defrag | Temporary unavailability and quorum risk | Snapshot, endpoint health, one member at a time, capacity plan |
| Delete etcd PVC or host data | Loss of membership, mounts, quotas, and job metadata | Last-resort approval, tested backup and restore, full configuration inventory |
| FUSE force unmount | Application I/O failure | Exact mount identity, affected workloads stopped or coordinated, remount verification |

After an authorized recovery, verify component readiness, stable restart counts, Worker membership, exact known-path access, relevant job state, error rate, performance versus baseline, data consistency, and an agreed observation window.

Properties approval is a separate gate from general mutation approval. Even when the user originally requested a configuration change, present the exact final diff and request confirmation that an Alluxio expert reviewed and approved it immediately before applying it. If the effective value or source cannot be proven, stop at a proposed change rather than writing.

## 10. Docker or bare-metal notes

Use the same evidence model without Kubernetes:

~~~bash
alluxio info version
alluxio info nodes
alluxio mount list
alluxio job list --job-type ALL --job-state ALL
ps -ef
systemctl status <ALLUXIO_SERVICE>
journalctl -u <ALLUXIO_SERVICE> --since <TIME>
df -h
mount
~~~

Inspect component logs under the actual installation's logs directory. Verify container image, JVM flags, cgroup limits, page-store path, Worker identity path, ports, and service manager. Do not install tools, restart services, unmount FUSE, or write to UFS without authorization.
