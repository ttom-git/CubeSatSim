#Collect a the CubeSatSim sensors inventory over SSH

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict

from probe import run_remote_batch


POWER_RE = re.compile(
    r"^\s*(\+X|\+Y|\+Z|-X|-Y|-Z|Bat2?|BAT2?)\s*\|\s*"
    r"([+-]?\d+(?:\.\d+)?)\s+V\s+([+-]?\d+(?:\.\d+)?)\s+mA\s*$",
    re.MULTILINE,
)


def parse_power_output(stdout: str, stderr: str) -> dict:
    combined = f"{stdout}\n{stderr}"
    dependency_error = "ModuleNotFoundError: No module named 'gpiod'" in combined
    runtime_dependency_error = "platform library 'gpiod' was not found" in combined
    bus_error = "bus has a problem" in combined

    if dependency_error or runtime_dependency_error or bus_error:
        reason = (
            "missing_python_dependency"
            if dependency_error or runtime_dependency_error
            else "read_failed"
        )
        return {
            "status": "unavailable",
            "readings": {
                label: {"status": "unavailable", "reason": reason}
                for label in ("+X", "+Y", "+Z", "-X", "-Y", "-Z", "Bat", "Bat2")
            },
            "raw_output": stdout,
            "raw_error": stderr,
        }

    readings = {}
    for label, voltage, current in POWER_RE.findall(stdout):
        readings[label] = {
            "voltage_v": float(voltage),
            "current_ma": float(current),
            "status": "ok",
        }


#    combined = f"{stdout}\n{stderr}"
#    dependency_error = "ModuleNotFoundError: No module named 'gpiod'" in combined
#    bus_error = "bus has a problem" in combined
#    if dependency_error or bus_error or not readings:
#        reason = "missing_python_dependency" if dependency_error else "read_failed"

    if not readings:
        for label in ("+X", "+Y", "+Z", "-X", "-Y", "-Z", "Bat", "Bat2"):
            #readings.setdefault(label, {"status": "unavailable", "reason": reason})
            readings[label] = {"status": "unavailable", "reason": "read_failed"}

    return {
        "status": "ok" if readings and all(v["status"] == "ok" for v in readings.values()) else "unavailable",
        "readings": readings,
        "raw_output": stdout,
        "raw_error": stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="cubesatsim.local")
    parser.add_argument("--user", default="pi")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    target = f"{args.user}@{args.host}"
    commands = {
        "bus_1_scan": "i2cdetect -y 1 2>&1",
        "bus_3_scan": "i2cdetect -y 3 2>&1",
        "power_read": "cd /home/pi/CubeSatSim && timeout 5 ./config -v 2>&1",
        "payload_check": "cd /home/pi/CubeSatSim && timeout 5 ./config -p 2>&1",
    }

    try:
        ssh_returncode, results, ssh_stderr = run_remote_batch(
            target, commands, args.timeout
        )
    except Exception as error:
        print(f"HIL inventory failed: {error}", file=sys.stderr)
        return 2

    power = results.get("power_read")
    report = {
        "target": target,
        "ssh_ok": ssh_returncode == 0 and len(results) == len(commands),
        "power": parse_power_output(
            power.stdout if power else "",
            power.stderr if power else ssh_stderr,
        ),
        "bus_scans": {
            name: asdict(results[name])
            for name in ("bus_1_scan", "bus_3_scan")
            if name in results
        },
        "payload": (
            {
                "status": "observed",
                "raw_output": results["payload_check"].stdout,
                "raw_error": results["payload_check"].stderr,
            }
            if "payload_check" in results
            else {"status": "unavailable"}
        ),
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Target: {target}")
        print(f"SSH: {'OK' if report['ssh_ok'] else 'FAILED'}")
        print(f"Power telemetry: {report['power']['status']}")
        for label, reading in report["power"]["readings"].items():
            if reading["status"] == "ok":
                print(
                    f"{label}: {reading['voltage_v']:.3f} V "
                    f"{reading['current_ma']:.1f} mA"
                )
            else:
                print(f"  {label}: unavailable ({reading['reason']})")
        print(f"Payload check: {report['payload']['status']}")

    return 0 if report["ssh_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
