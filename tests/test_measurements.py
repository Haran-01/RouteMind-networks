"""Contracts for recovery timing, especially exclusion of packets already in flight."""
import csv
from pathlib import Path
import tempfile
import unittest

from measurement_checks import verify_recovery


class RecoveryTests(unittest.TestCase):
    def fixture(self, static=False, affected=True):
        root = Path(__file__).resolve().parents[1] / "build/test-tmp"
        root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name)
        events = [(14, "link-down"), (14.06, "observed-down"), (20, "link-up"), (20.35, "observed-up")]
        if not static:
            events.append((14.06, "realtime-route-ready"))
        with (target / "events.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time", "event", "from", "to"])
            writer.writerows((time, name, 2, 5) for time, name in sorted(events))
        routes = [{"time": "0", "class": "1", "path": "0-1-2-5-6" if affected else "0-1-3-5-6"}]
        if not static:
            routes.append({"time": "14.06", "class": "1", "path": "0-1-3-5-6"})
        telemetry = [{"time": str(time), "from": "2", "to": "5", "up": str(up)}
                     for time, up in [(13.69, 1), (14.06, 0), (20.35, 1)]]
        deliveries = [(14.08, 13.99), (14.09, 14.01), (14.12, 14.07), (20.03, 19.99), (20.04, 20.01)]
        if static:
            deliveries = [(20.03, 19.99), (20.04, 20.01)]
        packets = [{"time": str(received), "tx_time": str(sent)} for received, sent in deliveries]
        summary = {"scenario": "failure", "interval_s": .37, "failure_time_s": 14,
                   "link_restoration_time_s": 20, "recovery_time_s": 20,
                   "failure_observed_time_s": 14.06, "restoration_observed_time_s": 20.35,
                   "failure_detection_delay_ms": 60, "realtime_path_affected_by_failure": affected,
                   "realtime_route_ready_time_s": None if static else 14.06,
                   "realtime_route_repair_delay_ms": 60 if affected and not static else None,
                   "realtime_first_delivery_after_failure_time_s": None if static else 14.09,
                   "realtime_first_delivery_after_route_ready_time_s": None if static else 14.12,
                   "realtime_first_delivery_after_restoration_time_s": 20.04,
                   "realtime_recovery_delay_ms": 120 if affected and not static else None}
        return target, summary, packets, routes, telemetry

    def test_inflight_packets_are_excluded_from_packet_recovery(self):
        args = self.fixture()
        verify_recovery(*args)
        args[1]["realtime_first_delivery_after_route_ready_time_s"] = 14.08
        with self.assertRaisesRegex(AssertionError, "post-ready delivery"):
            verify_recovery(*args)

    def test_unrepaired_static_path_has_null_recovery(self):
        args = self.fixture(static=True)
        verify_recovery(*args)
        args[1]["realtime_recovery_delay_ms"] = 0
        with self.assertRaisesRegex(AssertionError, "packet recovery delay"):
            verify_recovery(*args)

    def test_unaffected_path_does_not_claim_a_repair_latency(self):
        args = self.fixture(affected=False)
        verify_recovery(*args)
        args[1]["realtime_route_repair_delay_ms"] = 60
        with self.assertRaisesRegex(AssertionError, "route repair delay"):
            verify_recovery(*args)


if __name__ == "__main__":
    unittest.main()
