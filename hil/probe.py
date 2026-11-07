# Read-only health probe for a the CubeSAt establishing that 
# the remote connection and the runtime are working fine 

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from dataclasses import asdict, dataclass


@dataclass
class CommandResult:
    command: str        # cubesatsim.service;  transmit.service;    .mode;    .cfg;    i2c;     payload
    returncode: int     
    stdout: str
    stderr: str


def run_remote_batch(
    target: str, commands: dict[str, str], timeout: float) -> tuple[int, dict[str, CommandResult], str]:
    script_parts = ["set +e"]   #to keep alive batch through errors 

    #bash script constructor
    for name, command in commands.items():
        #to avoid {n} different calls on ssh:
        script_parts.append(f"printf '\\n__HIL_BEGIN_{name}__\\n'")
        script_parts.append(command)
        script_parts.append(f"printf '\\n__HIL_RC_{name}__%s\\n' \"$?\"")


    result = subprocess.run(
        ["ssh", target, "\n".join(script_parts)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    #Output parsing:
    output = result.stdout
    parsed: dict[str, CommandResult] = {}
    for name, command in commands.items():  
        begin = f"__HIL_BEGIN_{name}__\n"   
        end_prefix = f"\n__HIL_RC_{name}__"

        if begin not in output or end_prefix not in output:
            continue

        section = output.split(begin, 1)[1]
        body, returncode = section.split(end_prefix, 1)
        parsed[name] = CommandResult(
            command=command,
            returncode =int(returncode.splitlines()[0]),
            stdout=body.strip(),
            stderr=result.stderr.strip(),
        )
    return result.returncode, parsed, result.stderr.strip()


def parse_bus_devices(result: CommandResult) -> dict[str, bool]:
    devices = set(result.stdout.split())
    return {str(bus): f"/dev/i2c-{bus}" in devices for bus in (0, 1, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="cubesatsim.local")
    parser.add_argument("--user", default="pi")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    target = f"{args.user}@{args.host}"
    commands = {
        "cubesatsim_service": "systemctl is-active cubesatsim.service",
        "transmit_service": "systemctl is-active transmit.service",
        "mode": "cat /home/pi/CubeSatSim/.mode",
        "sim_config": "awk '{print $1, $2, $3, $4, $5, $6, $7, $8, $9}' /home/pi/CubeSatSim/sim.cfg",
        "bus_devices": "ls -1 /dev/i2c-* 2>/dev/null",
        "sim_mode_auto": "test -e /home/pi/CubeSatSim/sim_mode_auto",
        "payload_device": "test -r /dev/ttyAMA0",
    }

    try:
        ssh_returncode, results, ssh_stderr = run_remote_batch(
            target, commands, args.timeout
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"HIL probe failed: {error}", file=sys.stderr)
        return 2

    report = {
        "target": target,
        "ssh_ok": ssh_returncode == 0 and len(results) == len(commands),
        "ssh_stderr": ssh_stderr,
        "services": {
                        name: result.stdout + " \n"
                        for name, result in results.items()
                        if name.endswith("_service")
                    },
        "mode": results["mode"].stdout,
        "sim_config": results["sim_config"].stdout,
        "bus_devices": parse_bus_devices(results["bus_devices"]),
        "simulation_auto": results["sim_mode_auto"].returncode == 0,
        "payload_device_readable": results["payload_device"].returncode == 0,
        "commands": {name: asdict(result) for name, result in results.items()},
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Target: {target}")
        print(f"SSH: {'OK' if report['ssh_ok'] else 'FAILED'}")
        print(f"Services: {report['services']}")
        print(f"Mode: {report['mode'] or 'unknown'}")
        print(f"I2C devices: {report['bus_devices']}")
        print(f"Automatic simulation: {report['simulation_auto']}")
        print(f"Payload UART readable: {report['payload_device_readable']}")

    return 0 if report["ssh_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
