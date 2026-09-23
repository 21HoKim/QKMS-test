#!/usr/bin/env python3
"""docker-compose.yml 의 QKD 목업 서비스를 도커 없이 로컬 프로세스로 띄운다.

- 설정의 단일 출처는 docker-compose.yml 이다. 서비스별 environment 를 그대로 쓰고,
  PORT 만 호스트 공개 포트(ports 의 "18081:8080" 앞쪽)로 바꾼다.
  → 도커로 띄웠을 때와 같은 주소(localhost:18081~18084)로 접근된다.
- QKMS_URL 의 호스트가 compose 서비스 이름이면 localhost:<그 서비스의 공개 포트>로 바꾸고,
  공개 포트가 없는 서비스(현재 QKMS)를 가리키면 제거한다.

사용
  python3 run_local.py        # 4개 노드 기동, Ctrl+C 로 종료
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yaml

HERE = Path(__file__).resolve().parent
SIM = HERE / "qkd_sim.py"
LOG_DIR = Path(tempfile.gettempdir()) / "qkd-sim-logs"


def find_compose():
    for d in [HERE, *HERE.parents]:
        p = d / "docker-compose.yml"
        if p.exists():
            return p
    raise SystemExit("docker-compose.yml 을 찾지 못함")


def published_ports(services):
    """서비스 이름 -> 컨테이너 8080 에 대응하는 호스트 포트"""
    out = {}
    for name, s in services.items():
        for p in s.get("ports", []):
            parts = str(p).split(":")          # "18081:8080" 또는 "127.0.0.1:18081:8080"
            if len(parts) >= 2 and parts[-1] == "8080":
                out[name] = int(parts[-2])
    return out


def load_nodes(compose_path=None):
    """compose 에서 QKD 목업 노드 목록을 읽는다 (environment 에 LINKS 가 있는 서비스)."""
    services = yaml.safe_load(open(compose_path or find_compose()))["services"]
    ports = published_ports(services)
    nodes = []
    for name, s in services.items():
        env = s.get("environment") or {}
        if "LINKS" not in env:
            continue
        if name not in ports:
            raise SystemExit(f"{name}: ports 에 '<호스트포트>:8080' 이 필요함")
        env = {k: str(v) for k, v in env.items()}
        env["PORT"] = str(ports[name])
        if "QKMS_URL" in env:
            u = urlparse(env["QKMS_URL"])
            if u.hostname in ports:
                env["QKMS_URL"] = f"{u.scheme}://127.0.0.1:{ports[u.hostname]}"
            else:
                env.pop("QKMS_URL")
        nodes.append({"name": name, "port": ports[name], "env": env})
    return nodes


def is_up(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/sim/status", timeout=0.5)
        return True
    except Exception:
        return False


def start(nodes, timeout=10.0):
    busy = [n["port"] for n in nodes if is_up(n["port"])]
    if busy:
        raise SystemExit(f"포트 {busy} 에 이미 목업이 떠 있음 (도커가 실행 중이면 docker compose down)")
    LOG_DIR.mkdir(exist_ok=True)
    procs = []
    for n in nodes:
        log = open(LOG_DIR / f"{n['name']}.log", "w")
        env = {**os.environ, **n["env"]}
        procs.append(subprocess.Popen([sys.executable, str(SIM)], env=env,
                                      stdout=log, stderr=subprocess.STDOUT))
    deadline = time.time() + timeout
    for n, p in zip(nodes, procs):
        while not is_up(n["port"]):
            if p.poll() is not None or time.time() > deadline:
                stop(procs)
                raise SystemExit(f"{n['name']} 기동 실패, 로그: {LOG_DIR / (n['name'] + '.log')}")
            time.sleep(0.1)
    return procs


def stop(procs):
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    nodes = load_nodes()
    procs = start(nodes)
    for n in nodes:
        print(f"{n['name']:8s} http://127.0.0.1:{n['port']}")
    print(f"로그: {LOG_DIR}   종료: Ctrl+C")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("일부 노드가 종료됨, 로그 확인")
    except KeyboardInterrupt:
        pass
    finally:
        stop(procs)


if __name__ == "__main__":
    main()