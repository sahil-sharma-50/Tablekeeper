#!/usr/bin/env python3
"""Measure cold container-to-health time and run Stage 1 checks offline."""
from __future__ import annotations

import argparse
import subprocess
import time
import uuid
from pathlib import Path


def run(command: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n"
                           f"{result.stderr.strip()}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="tablekeeper-stage-1")
    parser.add_argument("--startup-limit", type=float, default=60)
    args = parser.parse_args()

    name = "tablekeeper-s1-probe-" + uuid.uuid4().hex[:12]
    container_started = False
    started = time.perf_counter()
    try:
        run(["docker", "run", "--rm", "--detach", "--name", name,
             "--network", "none", "--cpus=2", "--memory=2g", args.image])
        container_started = True

        health_command = ["docker", "exec", name, "python", "-c",
                          "from urllib.request import urlopen; r=urlopen('http://127.0.0.1:8080/health', timeout=3); print(r.status, r.read().decode())"]
        deadline = started + args.startup_limit
        while time.perf_counter() < deadline:
            probe = subprocess.run(health_command, capture_output=True, text=True,
                                   timeout=5)
            if probe.returncode == 0 and probe.stdout.strip() == '200 {"status":"ok"}':
                break
            time.sleep(0.05)
        else:
            raise TimeoutError(f"container did not become healthy within {args.startup_limit}s")
        startup_ms = (time.perf_counter() - started) * 1000

        cpu = run(["docker", "inspect", name, "--format", "{{.HostConfig.NanoCpus}}"]).stdout.strip()
        memory = run(["docker", "inspect", name, "--format", "{{.HostConfig.Memory}}"]).stdout.strip()
        network = run(["docker", "inspect", name, "--format", "{{.HostConfig.NetworkMode}}"]).stdout.strip()
        environment = run(["docker", "inspect", name, "--format",
                           "{{range .Config.Env}}{{println .}}{{end}}"] ).stdout.splitlines()
        assert cpu == "2000000000" and memory == "2147483648" and network == "none"
        assert "PORT=8080" in environment and "PYTHONTZPATH=" in environment

        zones = run(["docker", "exec", name, "python", "-c",
                     "from zoneinfo import ZoneInfo; print(ZoneInfo('Europe/Berlin').key, ZoneInfo('America/New_York').key)"])
        checks = Path(__file__).with_name("stage1_independent.py")
        run(["docker", "cp", str(checks), f"{name}:/tmp/stage1_independent.py"])
        independent = run(["docker", "exec", name, "python", "/tmp/stage1_independent.py",
                           "--base-url", "http://127.0.0.1:8080"], timeout=180)

        print(f"STARTUP first_healthy_ms={startup_ms:.1f} limit_ms={args.startup_limit * 1000:.0f}")
        print(f"LIMITS NanoCPUs={cpu} memory_bytes={memory} network={network} PORT=8080")
        print(f"OFFLINE_TZ {zones.stdout.strip()}")
        print(independent.stdout.strip())
    finally:
        if container_started:
            subprocess.run(["docker", "stop", name], capture_output=True,
                           text=True, timeout=15)


if __name__ == "__main__":
    main()
