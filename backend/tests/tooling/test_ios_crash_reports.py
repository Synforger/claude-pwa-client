"""iPhone の crash の記録から、 落ちた理由と場所を取り出す (= `shell/ios/tools/crash-reports/crash-reports.py`)。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "shell" / "ios" / "tools" / "crash-reports" / "crash-reports.py"
spec = importlib.util.spec_from_file_location("crash_reports", SCRIPT)
crash_reports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crash_reports)


def test_a_report_shows_why_and_where_the_app_ended(tmp_path):
    # iOS の .ips は、 1 行目が見出しの JSON、 2 行目からが本体の JSON
    head = {"bundleID": "com.example.app", "app_version": "1.0", "build_version": "1", "timestamp": "2026-10-15 03:16:48"}
    body = {
        "exception": {"type": "EXC_CRASH", "signal": "SIGABRT"},
        "termination": {"namespace": "TCC", "details": ["… must contain an NSCameraUsageDescription key …"]},
        "faultingThread": 1,
        "usedImages": [{"name": "libsystem_kernel.dylib"}, {"name": "TCC"}],
        "threads": [{"frames": []}, {"queue": "com.apple.root.default-qos", "frames": [
            {"imageIndex": 0, "symbol": "__abort_with_payload"},
            {"imageIndex": 1, "symbol": "__TCC_CRASHING_DUE_TO_PRIVACY_VIOLATION__"}]}],
    }
    report = tmp_path / "App-2026-10-15-031648.ips"
    report.write_text(json.dumps(head) + "\n" + json.dumps(body))
    text = crash_reports.summary(report)
    assert "exception: EXC_CRASH SIGABRT" in text
    assert "ended by: TCC — … must contain an NSCameraUsageDescription key …" in text
    assert "thread 1 com.apple.root.default-qos" in text
    assert "TCC  __TCC_CRASHING_DUE_TO_PRIVACY_VIOLATION__" in text


def test_only_the_app_reports_are_listed(monkeypatch):
    listing = "\n".join([
        "App-2026-10-15-025411.ips                Writable, Readable   36 KB   2026/10/15, 2:54",
        "SiriSearchFeedback-2026-10-04-012122.ips Writable, Readable  356 bytes 2026/10/04, 1:21",
        "App-2026-10-14-120000.ips                Writable, Readable   30 KB   2026/10/14, 12:00",
    ])

    class Done:
        returncode = 0
        stdout = listing
        stderr = ""

    monkeypatch.setattr(crash_reports.subprocess, "run", lambda *a, **k: Done())
    assert crash_reports.listing("UDID") == [("App-2026-10-14-120000.ips", "2026-10-14"),
                                             ("App-2026-10-15-025411.ips", "2026-10-15")]


def test_an_unreachable_iphone_says_why_instead_of_a_traceback(monkeypatch, capsys):
    class Done:
        returncode = 1
        stdout = ""
        stderr = "ERROR: The device is not able to fulfill the requested usage assertion requirements.\n  more"

    monkeypatch.setattr(crash_reports.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(crash_reports.sys, "argv", ["crash-reports.py", "--device", "UDID"])
    assert crash_reports.main() == 1
    err = capsys.readouterr().err
    assert "could not reach the iPhone: ERROR: The device is not able to fulfill" in err
    assert "more" not in err


def test_without_a_date_only_the_newest_report_is_chosen():
    found = [("App-2026-10-14-120000.ips", "2026-10-14"), ("App-2026-10-15-025411.ips", "2026-10-15")]
    assert crash_reports.choose(found, None) == ["App-2026-10-15-025411.ips"]
    assert crash_reports.choose(found, "2026-10-14") == ["App-2026-10-14-120000.ips", "App-2026-10-15-025411.ips"]
    assert crash_reports.choose([], None) == []
