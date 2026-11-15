#!/usr/bin/env python3
"""Discover CubeSatSim resources over SSH without assuming a fixed payload."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict

from probe import CommandResult, run_remote_batch


I2C_SCAN_LINE = re.compile(r"^\s*([0-9a-f]{2}):\s+(.+)$", re.IGNORECASE)
POWER_RE = re.compile(
    r"^\s*(\+X|\+Y|\+Z|-X|-Y|-Z|Bat2?|BAT2?)\s*\|\s*"
    r"([+-]?\d+(?:\.\d+)?)\s+V\s+([+-]?\d+(?:\.\d+)?)\s+mA\s*$",
    re.MULTILINE,
)


def parse_i2c_scan(stdout: str) -> list[str]:
    addresses: list[str] = []
    for match in I2C_SCAN_LINE.finditer(stdout):
        row = int(match.group(1), 16) << 4
        for column, token in enumerate(match.group(2).split()[:16]):
            if re.fullmatch(r"[0-9a-f]{2}", token, re.IGNORECASE):
                addresses.append(f"0x{row + column:02x}")
    return addresses


def parse_i2c_devices(result: CommandResult) -> list[dict]:
    devices = []
    for line in result.stdout.splitlines():
        path = line.strip()
        match = re.fullmatch(r"/dev/i2c-(\d+)", path)
        if match:
            devices.append({"bus": int(match.group(1)), "device": path})
    return devices


def parse_power_adapter(result: CommandResult) -> dict:
    combined = f"{result.stdout}\n{result.stderr}"
    dependency_error = (
        "No module named 'gpiod'" in combined
        or "platform library 'gpiod' was not found" in combined
    )
    bus_error = "bus has a problem" in combined
    readings = {}
    if not dependency_error and not bus_error:
        for label, voltage, current in POWER_RE.findall(result.stdout):
            readings[label] = {
                "voltage_v": float(voltage),
                "current_ma": float(current),
                "status": "ok",
            }

    return {
        "adapter": "cubesatsim.config-v",
        "status": "ok" if readings else "unavailable",
        "reason": (
            "missing_python_dependency"
            if dependency_error
            else "read_failed" if bus_error or not readings else None
        ),
        "readings": readings,
        "raw_output": result.stdout,
        "raw_error": result.stderr,
    }


def parse_payload_adapter(result: CommandResult) -> dict:
    return {
        "adapter": "cubesatsim.config-p",
        "status": "observed" if result.stdout else "unavailable",
        "raw_output": result.stdout,
        "raw_error": result.stderr,
    }


def discover_report(
    target: str,
    results: dict[str, CommandResult],
    ssh_returncode: int,
    ssh_stderr: str,
    adapters: bool,
) -> dict:
    i2c_devices = parse_i2c_devices(results["i2c_devices"])
    buses = []
    for device in i2c_devices:
        key = f"i2c_scan_{device['bus']}"
        scan = results.get(key)
        buses.append(
            {
                **device,
                "addresses": parse_i2c_scan(scan.stdout) if scan else [],
                "scan_status": (
                    "ok" if scan and scan.returncode == 0 else "unavailable"
                ),
                "raw_scan": scan.stdout if scan else "",
                "raw_error": scan.stderr if scan else "",
            }
        )

    report = {
        "schema": "cubesatsim.hil.inventory.v2",
        "target": target,
        "ssh_ok": ssh_returncode == 0,
        "ssh_stderr": ssh_stderr,
        "components": {
            "i2c": {"status": "observed", "buses": buses},
            "serial": {
                "status": "observed",
                "devices": [
                    line.strip()
                    for line in results["serial_devices"].stdout.splitlines()
                    if line.strip()
                ],
            },
            "services": {
                "status": "observed",
                "running": [
                    line.strip()
                    for line in results["services"].stdout.splitlines()
                    if line.strip()
                ],
            },
        },
        "capabilities": {
            name: result.returncode == 0
            for name, result in (
                ("config", results["config_exists"]),
                ("i2cdetect", results["i2cdetect_exists"]),
            )
        },
        "raw": {name: asdict(result) for name, result in results.items()},
    }

    if adapters:
        report["adapters"] = {
            "power": parse_power_adapter(results["power_read"]),
            "payload": parse_payload_adapter(results["payload_check"]),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="cubesatsim.local")
    parser.add_argument("--user", default="pi")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--adapters",
        action="store_true",
        help="run CubeSatSim-specific config -v and config -p adapters",
    )
    args = parser.parse_args()

    target = f"{args.user}@{args.host}"
    commands = {
        "identity": "uname -a; printf '\\n--- os-release ---\\n'; cat /etc/os-release",
        "i2c_devices": "find /dev -maxdepth 1 -type c -name 'i2c-*' -printf '%p\\n' 2>/dev/null | sort -V",
        "serial_devices": "find /dev -maxdepth 1 \\( -name 'tty*' -o -name 'serial*' \\) -printf '%p\\n' 2>/dev/null | sort",
        "services": "systemctl list-units --type=service --state=running --no-legend --no-pager",
        "config_exists": "test -x /home/pi/CubeSatSim/config",
        "i2cdetect_exists": "command -v i2cdetect",
    }
    if args.adapters:
        commands.update(
            {
                "power_read": "cd /home/pi/CubeSatSim && timeout 5 ./config -v 2>&1",
                "payload_check": "cd /home/pi/CubeSatSim && timeout 5 ./config -p 2>&1",
            }
        )

    try:
        ssh_returncode, results, ssh_stderr = run_remote_batch(
            target, commands, args.timeout
        )
        i2c_devices = parse_i2c_devices(results["i2c_devices"])
        scan_commands = {
            f"i2c_scan_{device['bus']}": f"i2cdetect -y {device['bus']} 2>&1"
            for device in i2c_devices
        }
        if scan_commands:
            scan_returncode, scans, scan_stderr = run_remote_batch(
                target, scan_commands, args.timeout
            )
            results.update(scans)
            ssh_returncode = max(ssh_returncode, scan_returncode)
            ssh_stderr = "\n".join(filter(None, (ssh_stderr, scan_stderr)))
    except Exception as error:
        print(f"HIL inventory failed: {error}", file=sys.stderr)
        return 2

    report = discover_report(
        target, results, ssh_returncode, ssh_stderr, args.adapters
    )
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Target: {target}")
        print(f"SSH: {'OK' if report['ssh_ok'] else 'FAILED'}")
        for bus in report["components"]["i2c"]["buses"]:
            addresses = ", ".join(bus["addresses"]) or "none"
            print(f"I2C bus {bus['bus']}: {addresses}")
        print(
            f"Serial devices: "
            f"{len(report['components']['serial']['devices'])}"
        )
        print(
            f"Running services: "
            f"{len(report['components']['services']['running'])}"
        )
        if args.adapters:
            print(f"Power adapter: {report['adapters']['power']['status']}")
            print(f"Payload adapter: {report['adapters']['payload']['status']}")

    return 0 if report["ssh_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
