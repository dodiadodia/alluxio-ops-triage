#!/usr/bin/env python3
"""Regression tests for analyze_bundle.py."""

from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

import analyze_bundle


class AnalyzeBundleTest(unittest.TestCase):
    def create_fixture(self, root: Path) -> Path:
        bundle = root / "bundle"
        (bundle / "logs" / "worker").mkdir(parents=True)
        (bundle / "config").mkdir()
        (bundle / "metrics").mkdir()
        (bundle / "logs" / "worker" / "worker.log").write_text(
            "2026-09-15T01:02:03Z ERROR OOMKilled password=should-not-leak\n"
            "2026-09-15T01:02:04Z ERROR Transport endpoint is not connected\n",
            encoding="utf-8",
        )
        (bundle / "config" / "alluxio-site.properties").write_text(
            "alluxio.worker.page.store.type=LOCAL\n"
            "alluxio.test.secret=should-not-leak\n"
            "image=alluxio-enterprise:AI-3.9-16.0.0\n",
            encoding="utf-8",
        )
        (bundle / "metrics" / "metrics.prom").write_text(
            "alluxio_cached_storage 100\n"
            "alluxio_cached_capacity 200\n"
            "etcd_mvcc_db_total_size_in_use_in_bytes 1048576\n"
            "etcd_server_has_leader 1\n",
            encoding="utf-8",
        )
        return bundle

    def test_directory_scan_detects_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle = self.create_fixture(Path(temp))
            summary = analyze_bundle.scan(
                bundle,
                max_file_bytes=1024 * 1024,
                max_total_bytes=4 * 1024 * 1024,
                max_members=100,
                max_evidence=3,
            )
            signal_ids = {signal.signal_id for signal in summary.signals}
            self.assertIn("memory_termination", signal_ids)
            self.assertIn("fuse_disconnected", signal_ids)
            self.assertIn("alluxio_cached_storage", summary.relevant_metrics_present)
            self.assertIn(
                "etcd_mvcc_db_total_size_in_use_in_bytes",
                summary.relevant_metrics_present,
            )
            self.assertIn("etcd_server_has_leader", summary.relevant_metrics_present)
            rendered = analyze_bundle.render_markdown(summary)
            self.assertIn("<REDACTED>", rendered)
            self.assertNotIn("should-not-leak", rendered)

    def test_tar_scan_does_not_extract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.create_fixture(root)
            archive_path = root / "bundle.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(bundle, arcname="bundle")
            summary = analyze_bundle.scan(
                archive_path,
                max_file_bytes=1024 * 1024,
                max_total_bytes=4 * 1024 * 1024,
                max_members=100,
                max_evidence=3,
            )
            self.assertEqual("tar-archive", summary.source_type)
            self.assertIsNotNone(summary.sha256)
            self.assertFalse((root / "extracted").exists())

    def test_unsafe_tar_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "unsafe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                payload = b"secret=do-not-print\n"
                info = tarfile.TarInfo("../escape.log")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            summary = analyze_bundle.scan(
                archive_path,
                max_file_bytes=1024,
                max_total_bytes=4096,
                max_members=10,
                max_evidence=3,
            )
            self.assertEqual(["../escape.log"], summary.rejected_archive_members)
            self.assertEqual(0, summary.text_files_scanned)


if __name__ == "__main__":
    unittest.main()
