#!/usr/bin/env python3
"""Generate a bounded, redacted first-pass summary of an Alluxio support bundle.

The analyzer accepts an extracted directory or tar archive. Archives are read in
place and are never extracted. The output is an evidence inventory, not an
automatic root-cause verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Iterable, Iterator, Optional


DEFAULT_MAX_FILE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 50_000
DEFAULT_MAX_EVIDENCE = 5

TEXT_SUFFIXES = {
    "",
    ".conf",
    ".csv",
    ".env",
    ".json",
    ".log",
    ".md",
    ".out",
    ".prom",
    ".properties",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

CATEGORY_RULES = {
    "config": re.compile(r"(^|/)(conf|config)(/|$)", re.I),
    "hardware": re.compile(r"(^|/)(hardware|system|node)(/|$)", re.I),
    "etcd": re.compile(r"(^|/)etcd(/|$)", re.I),
    "logs": re.compile(r"(^|/)(logs?|containers?|pods?)(/|$)|\.(log|out)$", re.I),
    "metrics": re.compile(r"(^|/)(metrics?|prometheus)(/|$)|\.prom$", re.I),
    "job-history": re.compile(r"(^|/)(job[-_ ]?history|jobs?)(/|$)", re.I),
    "meta": re.compile(r"(^|/)(meta|manifest|summary)(/|$)", re.I),
}

COMPONENT_RULES = [
    ("csi", re.compile(r"csi[-_/ ]?(controller|node|plugin|driver|nodeserver)", re.I)),
    ("fuse", re.compile(r"(^|[-_/ ])fuse($|[-_/ .])", re.I)),
    ("coordinator", re.compile(r"coordinator|job[-_ ]?master", re.I)),
    ("worker", re.compile(r"(^|[-_/ ])worker($|[-_/ .])", re.I)),
    ("etcd", re.compile(r"(^|[-_/ ])etcd($|[-_/ .])", re.I)),
    ("fdb", re.compile(r"foundationdb|(^|[-_/ ])fdb($|[-_/ .])", re.I)),
    ("operator", re.compile(r"operator|doctor|collectinfo", re.I)),
    ("application", re.compile(r"application|workload|training|inference", re.I)),
]

VERSION_RE = re.compile(
    r"\b(?:AI|DA|EE|enterprise)[-_]?[0-9]+\.[0-9]+(?:[-_.][0-9A-Za-z]+){0,5}\b",
    re.I,
)
PROPERTY_RE = re.compile(r"\balluxio\.[a-zA-Z0-9_.-]+\b")
ISO_TIMESTAMP_RE = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?)\b"
)

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|aws[_-]?secret|"
    r"aws[_-]?access[_-]?key|access[_-]?key|secret[_-]?key|credential)"
    r"(\s*[:=]\s*)([^\s,;}\]]+)"
)
AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")
URL_CREDENTIAL_RE = re.compile(r"(?P<scheme>https?://)[^/\s:@]+:[^/\s@]+@")


@dataclass(frozen=True)
class SignalRule:
    signal_id: str
    priority: str
    pattern: re.Pattern[str]
    meaning: str
    discriminator: str


SIGNAL_RULES = [
    SignalRule(
        "memory_termination",
        "HIGH",
        re.compile(
            r"OOMKilled|OutOfMemoryError|Java heap space|Direct buffer memory|"
            r"Cannot reserve .* direct buffer|exit(?:ed)?(?: with)?(?: code)?\s*137",
            re.I,
        ),
        "A process or container reported memory exhaustion or a memory-related termination.",
        "Correlate Last State, cgroup limit, JVM heap/direct memory, node OOM events, and the memory time series.",
    ),
    SignalRule(
        "fuse_disconnected",
        "HIGH",
        re.compile(r"Transport endpoint is not connected|ENOTCONN|Errno\s*107", re.I),
        "A FUSE mount was present but disconnected from its serving process.",
        "Correlate the application, FUSE pod/process, CSI recovery, and kubelet lifecycle on the same node.",
    ),
    SignalRule(
        "filesystem_io_error",
        "HIGH",
        re.compile(r"Input/output error|Errno\s*5|\bEIO\b", re.I),
        "The filesystem boundary returned an I/O error; the failing backend is not yet identified.",
        "Check the same timestamp in FUSE, Worker, page-store, network, and UFS evidence.",
    ),
    SignalRule(
        "etcd_quorum_or_capacity",
        "HIGH",
        re.compile(
            r"etcdserver:.*(?:no leader|database space exceeded)|\bNOSPACE\b|"
            r"mvcc: database space exceeded|rafthttp.*unhealthy",
            re.I,
        ),
        "Etcd reported quorum, leadership, peer, or backend-capacity trouble.",
        "Check all endpoint health/status, alarms, quorum, DB size, disk latency, and the last valid snapshot.",
    ),
    SignalRule(
        "storage_full",
        "HIGH",
        re.compile(r"No space left on device|\bENOSPC\b", re.I),
        "A filesystem was full.",
        "Identify the exact filesystem: page store, etcd PVC, logs, root disk, or temporary storage.",
    ),
    SignalRule(
        "ufs_authentication",
        "HIGH",
        re.compile(
            r"AccessDenied|SignatureDoesNotMatch|InvalidAccessKeyId|ExpiredToken|"
            r"InvalidToken|AuthorizationHeaderMalformed",
            re.I,
        ),
        "An S3-compatible or UFS authentication/signing path rejected a request.",
        "Identify the rejecting layer, endpoint, region, credential source/expiry, policy, and clock skew without exposing secrets.",
    ),
    SignalRule(
        "ufs_throttling",
        "HIGH",
        re.compile(
            r"\bSlowDown\b|TooManyRequests|status(?: code)?\s*[:=]?\s*429|"
            r"HTTP/?\s*429|ServiceUnavailable",
            re.I,
        ),
        "The UFS or an intermediate service may be throttling or unavailable.",
        "Correlate provider metrics, retry headers, request rate, connection pool, and Worker resources.",
    ),
    SignalRule(
        "worker_identity_conflict",
        "HIGH",
        re.compile(
            r"AlreadyExistsException.*(?:same id|member)|other member with same id|"
            r"duplicate worker.*(?:id|identity)",
            re.I,
        ),
        "Worker identity appears duplicated or already registered.",
        "Compare identity files, persistent volumes, pod/node ownership, and etcd membership before changing membership.",
    ),
    SignalRule(
        "page_store_unhealthy",
        "HIGH",
        re.compile(
            r"page[ _-]?store.*(?:unhealthy|failed|failure|error)|"
            r"alluxio_page_store_dir_healthy[^\n]*\s0(?:\.0+)?$",
            re.I,
        ),
        "The Worker page-store path reported an error or unhealthy state.",
        "Correlate directory verdict, unavailable bytes, filesystem capacity/inodes, device latency, and kernel errors.",
    ),
    SignalRule(
        "write_persistence_risk",
        "HIGH",
        re.compile(
            r"async(?:hronous)?[ _-]?persist.*(?:failed|failure|timeout)|"
            r"\bNOT_PERSISTED\b|Value length exceeds limit|transaction_too_large|"
            r"FDB.*(?:error|failed|unavailable)",
            re.I,
        ),
        "Write-cache metadata or asynchronous persistence reported a failure or incomplete durability.",
        "Confirm write-cache mode, FDB health, persist backlog, Worker lifecycle, and exact UFS object visibility.",
    ),
    SignalRule(
        "thread_or_queue_pressure",
        "MEDIUM",
        re.compile(
            r"RejectedExecutionException|thread pool.*(?:reject|exhaust)|"
            r"queue.*(?:full|capacity exceeded)|alluxio_worker_thread_pool_rejections",
            re.I,
        ),
        "A thread pool or work queue may be saturated.",
        "Correlate active operations, request rate, CPU throttling, task duration, queue depth, and downstream latency.",
    ),
    SignalRule(
        "job_failure",
        "MEDIUM",
        re.compile(
            r"(?:load|free|copy|move|rebalance)[ _-]?job[^\n]{0,120}(?:FAILED|failure)|"
            r"mJobState[\"':= ]+FAILED|Files Failed:\s*[1-9]",
            re.I,
        ),
        "An Alluxio background job reported failure.",
        "Inspect job details, failed files/reasons, Coordinator scheduler, etcd, Worker tasks, UFS, and page store.",
    ),
    SignalRule(
        "unrecognized_property",
        "MEDIUM",
        re.compile(r"unrecognized propert|unknown configuration|invalid property", re.I),
        "A component may be ignoring or rejecting a configuration property.",
        "Compare the exact property with the detected version's PropertyKey source and effective runtime configuration.",
    ),
    SignalRule(
        "license_warning",
        "MEDIUM",
        re.compile(r"license[^\n]{0,100}(?:expire|expired|invalid|exceed)", re.I),
        "License validity, expiry, or entitlement may require attention.",
        "Check the license status/expiration metric and the exact component behavior and customer impact.",
    ),
    SignalRule(
        "network_timeout",
        "MEDIUM",
        re.compile(
            r"Connection refused|ConnectException|connection reset|"
            r"Timeout waiting for connection|(?:read|connect|request) timed out|deadline exceeded",
            re.I,
        ),
        "A dependency connection failed, reset, or timed out.",
        "Identify the source, destination, protocol, retry window, and whether the endpoint was unhealthy or saturated.",
    ),
    SignalRule(
        "container_crash_loop",
        "MEDIUM",
        re.compile(r"CrashLoopBackOff|Back-off restarting failed container", re.I),
        "Kubernetes reported repeated container startup failure.",
        "Inspect Last State, previous logs, events, probes, configuration, dependencies, and resource limits.",
    ),
]

RELEVANT_METRICS = [
    "alluxio_cached_storage",
    "alluxio_cached_capacity",
    "alluxio_cached_data_read",
    "alluxio_missed_data_read",
    "alluxio_ufs_fallback",
    "alluxio_ufs_error",
    "alluxio_ufs_latency_ms",
    "alluxio_page_store_dir_healthy",
    "alluxio_page_store_operation_errors",
    "alluxio_worker_thread_pool_rejections",
    "alluxio_worker_active_operations",
    "alluxio_netty_operation_errors",
    "alluxio_netty_direct_memory_usage",
    "alluxio_worker_membership",
    "alluxio_cumulative_unavailable_workers",
    "alluxio_fuse_call_latency_ms",
    "alluxio_fuse_aborted_requests",
    "alluxio_active_job_count",
    "alluxio_scheduler_queue_size",
    "alluxio_scheduler_job_failures",
    "alluxio_license_expiration_date",
    "alluxio_version_info",
]


@dataclass
class Evidence:
    file: str
    line: int
    component: str
    excerpt: str


@dataclass
class SignalResult:
    signal_id: str
    priority: str
    count: int
    meaning: str
    discriminator: str
    evidence: list[Evidence]


@dataclass
class ScanSummary:
    source: str
    source_type: str
    sha256: Optional[str]
    files_seen: int
    text_files_scanned: int
    bytes_scanned: int
    truncated_files: int
    skipped_binary_files: int
    rejected_archive_members: list[str]
    categories: dict[str, int]
    components: dict[str, int]
    versions: dict[str, int]
    timestamp_ranges: dict[str, dict[str, str]]
    relevant_metrics_present: list[str]
    alluxio_properties: list[str]
    signals: list[SignalResult]
    data_gaps: list[str]


@dataclass
class FileRecord:
    name: str
    size: int
    opener: Callable[[], BinaryIO]


def safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def iter_directory(path: Path) -> Iterator[FileRecord]:
    for candidate in sorted(path.rglob("*")):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            size = candidate.stat().st_size
        except OSError:
            continue
        relative = candidate.relative_to(path).as_posix()
        yield FileRecord(relative, size, lambda p=candidate: p.open("rb"))


def iter_archive(path: Path, max_members: int, rejected: list[str]) -> Iterator[FileRecord]:
    archive = tarfile.open(path, mode="r:*")
    try:
        members = archive.getmembers()
        if len(members) > max_members:
            raise ValueError(
                f"archive has {len(members)} members; limit is {max_members}"
            )
        for member in members:
            if not member.isfile():
                continue
            if not safe_archive_name(member.name):
                rejected.append(member.name)
                continue

            def open_member(m=member, a=archive):
                stream = a.extractfile(m)
                if stream is None:
                    raise OSError(f"cannot read archive member {m.name}")
                return stream

            yield FileRecord(member.name, member.size, open_member)
    finally:
        archive.close()


def is_likely_text(name: str, sample: bytes) -> bool:
    suffix = Path(name).suffix.lower()
    if suffix not in TEXT_SUFFIXES:
        return False
    return b"\x00" not in sample


def redact(text: str) -> str:
    text = SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}<REDACTED>", text)
    text = AWS_ACCESS_KEY_RE.sub("<REDACTED_AWS_ACCESS_KEY>", text)
    text = JWT_RE.sub("<REDACTED_JWT>", text)
    return URL_CREDENTIAL_RE.sub(lambda m: m.group("scheme") + "<REDACTED>@", text)


def component_for(name: str) -> str:
    for component, pattern in COMPONENT_RULES:
        if pattern.search(name):
            return component
    return "unknown"


def categories_for(name: str) -> list[str]:
    return [category for category, pattern in CATEGORY_RULES.items() if pattern.search(name)]


def parse_timestamp(raw: str) -> Optional[tuple[str, datetime]]:
    normalized = raw.replace(",", ".")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", normalized):
        normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return "timezone-unknown", parsed
    return "utc", parsed.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan(
    source: Path,
    max_file_bytes: int,
    max_total_bytes: int,
    max_members: int,
    max_evidence: int,
) -> ScanSummary:
    rejected: list[str] = []
    if source.is_dir():
        source_type = "directory"
        records: Iterable[FileRecord] = iter_directory(source)
        source_hash = None
    elif source.is_file() and tarfile.is_tarfile(source):
        source_type = "tar-archive"
        records = iter_archive(source, max_members, rejected)
        source_hash = sha256_file(source)
    else:
        raise ValueError("input must be an extracted directory or readable tar archive")

    files_seen = 0
    text_files_scanned = 0
    bytes_scanned = 0
    truncated_files = 0
    skipped_binary_files = 0
    category_counts: Counter[str] = Counter()
    component_counts: Counter[str] = Counter()
    version_counts: Counter[str] = Counter()
    property_counts: Counter[str] = Counter()
    metric_presence: set[str] = set()
    signal_counts: Counter[str] = Counter()
    signal_evidence: dict[str, list[Evidence]] = defaultdict(list)
    timestamp_values: dict[str, list[datetime]] = defaultdict(list)

    rules_by_id = {rule.signal_id: rule for rule in SIGNAL_RULES}

    for record in records:
        files_seen += 1
        for category in categories_for(record.name):
            category_counts[category] += 1
        component = component_for(record.name)
        component_counts[component] += 1

        if bytes_scanned >= max_total_bytes:
            break

        read_limit = min(record.size, max_file_bytes, max_total_bytes - bytes_scanned)
        if read_limit <= 0:
            break
        try:
            with record.opener() as stream:
                data = stream.read(read_limit)
        except (OSError, tarfile.TarError):
            continue

        if record.size > len(data):
            truncated_files += 1
        bytes_scanned += len(data)
        if not is_likely_text(record.name, data[:4096]):
            skipped_binary_files += 1
            continue

        text_files_scanned += 1
        text = data.decode("utf-8", errors="replace")

        for version in VERSION_RE.findall(text):
            version_counts[version] += 1
        for prop in PROPERTY_RE.findall(text):
            property_counts[prop] += 1
        for metric in RELEVANT_METRICS:
            if metric in text:
                metric_presence.add(metric)

        for timestamp in ISO_TIMESTAMP_RE.findall(text):
            parsed = parse_timestamp(timestamp)
            if parsed is not None:
                basis, value = parsed
                timestamp_values[basis].append(value)

        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            for rule in SIGNAL_RULES:
                if not rule.pattern.search(line):
                    continue
                signal_counts[rule.signal_id] += 1
                evidence_list = signal_evidence[rule.signal_id]
                if len(evidence_list) < max_evidence:
                    excerpt = redact(" ".join(line.strip().split()))
                    if len(excerpt) > 320:
                        excerpt = excerpt[:317] + "..."
                    evidence_list.append(
                        Evidence(
                            file=record.name,
                            line=line_number,
                            component=component,
                            excerpt=excerpt,
                        )
                    )

    signals = []
    priority_order = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
    for signal_id, count in signal_counts.items():
        rule = rules_by_id[signal_id]
        signals.append(
            SignalResult(
                signal_id=signal_id,
                priority=rule.priority,
                count=count,
                meaning=rule.meaning,
                discriminator=rule.discriminator,
                evidence=signal_evidence[signal_id],
            )
        )
    signals.sort(key=lambda item: (priority_order.get(item.priority, 9), -item.count, item.signal_id))

    timestamp_ranges: dict[str, dict[str, str]] = {}
    for basis, values in timestamp_values.items():
        if not values:
            continue
        earliest = min(values)
        latest = max(values)
        timestamp_ranges[basis] = {
            "earliest": earliest.isoformat(),
            "latest": latest.isoformat(),
        }

    expected = ["config", "hardware", "etcd", "logs", "metrics", "job-history"]
    data_gaps = [
        f"No files classified as {category}; this is missing evidence, not proof of health."
        for category in expected
        if category_counts[category] == 0
    ]
    if not timestamp_ranges:
        data_gaps.append("No parseable ISO-like timestamps were found in the scanned text.")
    if bytes_scanned >= max_total_bytes:
        data_gaps.append(
            f"Total scan limit reached at {max_total_bytes} bytes; later files were not scanned."
        )
    if truncated_files:
        data_gaps.append(
            f"{truncated_files} files exceeded a scan limit and were only partially read."
        )
    if rejected:
        data_gaps.append(
            f"{len(rejected)} unsafe archive member paths were rejected."
        )

    return ScanSummary(
        source=str(source),
        source_type=source_type,
        sha256=source_hash,
        files_seen=files_seen,
        text_files_scanned=text_files_scanned,
        bytes_scanned=bytes_scanned,
        truncated_files=truncated_files,
        skipped_binary_files=skipped_binary_files,
        rejected_archive_members=rejected[:20],
        categories=dict(sorted(category_counts.items())),
        components=dict(sorted(component_counts.items())),
        versions=dict(version_counts.most_common()),
        timestamp_ranges=timestamp_ranges,
        relevant_metrics_present=sorted(metric_presence),
        alluxio_properties=[item for item, _ in property_counts.most_common(100)],
        signals=signals,
        data_gaps=data_gaps,
    )


def markdown_escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(summary: ScanSummary) -> str:
    lines = [
        "# Alluxio Diagnostic Bundle First-Pass Summary",
        "",
        "> This is a bounded signal inventory, not an automatic root-cause verdict. "
        "Signal priority is not the customer incident severity. Review redaction before sharing.",
        "",
        "## Bundle",
        "",
        f"- Source: {summary.source}",
        f"- Type: {summary.source_type}",
        f"- SHA-256: {summary.sha256 or 'not calculated for a directory'}",
        f"- Files seen: {summary.files_seen}",
        f"- Text files scanned: {summary.text_files_scanned}",
        f"- Bytes scanned: {summary.bytes_scanned}",
        f"- Truncated files: {summary.truncated_files}",
        f"- Binary/unsupported files skipped: {summary.skipped_binary_files}",
        "",
        "## Inventory",
        "",
        "| Category | Files |",
        "|---|---:|",
    ]
    for category, count in summary.categories.items():
        lines.append(f"| {markdown_escape(category)} | {count} |")
    if not summary.categories:
        lines.append("| unclassified | 0 |")

    lines.extend(["", "### Components by filename/path", "", "| Component | Files |", "|---|---:|"])
    for component, count in summary.components.items():
        lines.append(f"| {markdown_escape(component)} | {count} |")

    lines.extend(["", "## Environment clues", ""])
    if summary.versions:
        lines.append("Versions observed:")
        for version, count in summary.versions.items():
            lines.append(f"- {markdown_escape(version)} ({count} occurrences)")
    else:
        lines.append("- No Alluxio version string was detected.")

    if summary.timestamp_ranges:
        lines.extend(["", "Timestamp ranges:"])
        for basis, values in summary.timestamp_ranges.items():
            label = "UTC-normalized" if basis == "utc" else "timezone unknown"
            lines.append(
                f"- {label}: {values['earliest']} to {values['latest']}"
            )

    lines.extend(["", "Relevant metric families present:"])
    if summary.relevant_metrics_present:
        lines.extend(f"- {metric}" for metric in summary.relevant_metrics_present)
    else:
        lines.append("- None detected in the scanned text.")

    lines.extend(["", "Alluxio property names observed:"])
    if summary.alluxio_properties:
        lines.extend(f"- {prop}" for prop in summary.alluxio_properties)
    else:
        lines.append("- None detected.")

    lines.extend(["", "## Signals", ""])
    if not summary.signals:
        lines.append(
            "No configured signal pattern matched. This does not prove the bundle is healthy."
        )
    for signal in summary.signals:
        lines.extend(
            [
                f"### {signal.priority} {signal.signal_id}",
                "",
                f"- Matches: {signal.count}",
                f"- Meaning: {signal.meaning}",
                f"- Next discriminator: {signal.discriminator}",
                "",
                "| File | Line | Component | Redacted excerpt |",
                "|---|---:|---|---|",
            ]
        )
        for evidence in signal.evidence:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_escape(evidence.file),
                        str(evidence.line),
                        markdown_escape(evidence.component),
                        markdown_escape(evidence.excerpt),
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.extend(["## Data gaps and scan limits", ""])
    if summary.data_gaps:
        lines.extend(f"- {gap}" for gap in summary.data_gaps)
    else:
        lines.append("- No structural gap was detected by the first-pass inventory.")

    if summary.rejected_archive_members:
        lines.extend(["", "Rejected archive member paths:"])
        lines.extend(
            f"- {markdown_escape(name)}" for name in summary.rejected_archive_members
        )

    lines.extend(
        [
            "",
            "## Next analysis",
            "",
            "Correlate the earliest high-priority signal with application impact, component "
            "lifecycle, metrics, configuration, and recent changes. Use the version-matched "
            "Alluxio documentation and source. Treat missing or truncated evidence as a gap.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a bounded, redacted first-pass summary of an Alluxio diagnostic bundle."
    )
    parser.add_argument("source", type=Path, help="Extracted bundle directory or tar archive")
    parser.add_argument("-o", "--output", type=Path, help="Write output to this file")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help=f"Maximum bytes read from one file (default: {DEFAULT_MAX_FILE_BYTES})",
    )
    parser.add_argument(
        "--max-total-bytes",
        type=int,
        default=DEFAULT_MAX_TOTAL_BYTES,
        help=f"Maximum bytes read across files (default: {DEFAULT_MAX_TOTAL_BYTES})",
    )
    parser.add_argument(
        "--max-members",
        type=int,
        default=DEFAULT_MAX_MEMBERS,
        help=f"Maximum archive members accepted (default: {DEFAULT_MAX_MEMBERS})",
    )
    parser.add_argument(
        "--max-evidence",
        type=int,
        default=DEFAULT_MAX_EVIDENCE,
        help=f"Maximum excerpts retained per signal (default: {DEFAULT_MAX_EVIDENCE})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    for name in (
        "max_file_bytes",
        "max_total_bytes",
        "max_members",
        "max_evidence",
    ):
        if getattr(args, name) <= 0:
            print(f"error: --{name.replace('_', '-')} must be positive", file=sys.stderr)
            return 2
    try:
        summary = scan(
            args.source,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
            max_members=args.max_members,
            max_evidence=args.max_evidence,
        )
    except (OSError, ValueError, tarfile.TarError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        output = json.dumps(asdict(summary), indent=2, ensure_ascii=False) + "\n"
    else:
        output = render_markdown(summary)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
