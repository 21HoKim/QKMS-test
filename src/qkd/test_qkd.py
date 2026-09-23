#!/usr/bin/env python3
"""QKD 목업 통합 테스트. 목업을 도커로 띄웠든 로컬로 띄웠든 같은 코드로 동작한다.

- 노드, 포트, 링크, PSK 등 모든 기대값은 docker-compose.yml 에서 읽는다.
- 목업이 떠 있으면(도커든 run_local.py 든) 그대로 사용하고,
  하나도 떠 있지 않으면 run_local 로 직접 띄운 뒤 끝나면 내린다.

사용
  python3 test_qkd.py               # 자동
  python3 test_qkd.py --local       # 반드시 로컬로 기동 (도커가 떠 있으면 중단)
  python3 test_qkd.py --seconds 8   # 키 비교용 구독 시간(초), 기본 5

주의: 테스트는 목업 상태를 바꾼다 (등록 완료, 구독으로 받은 키는 버퍼에서 빠짐).
"""
import argparse
import asyncio
import base64
import json
import os
import sys

import aiohttp
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import run_local

RAW_KEY_FIELDS = {"qkd_node_id", "raw_key_id", "raw_key", "padding", "enc_flag"}
YANG = {"Content-Type": "application/yang-data+json"}


# ---- 준비 --------------------------------------------------------------------

class Node:
    def __init__(self, d):
        self.name = d["name"]
        self.port = d["port"]
        self.env = d["env"]
        self.base = f"http://127.0.0.1:{self.port}"
        self.node_id = self.env["QKD_NODE_ID"]
        self.links = json.loads(self.env["LINKS"])

    def alias_payload(self, alias_b64):
        return {"qkdn-rpc-qkd-registration:input": {"qkd_alias": alias_b64}}

    def encrypted_alias(self):
        alias = self.env.get("QKD_ALIAS", "QKD01").encode()
        psk = self.env.get("ALIAS_PSK")
        if not psk:
            return alias.decode()
        iv = bytes.fromhex(self.env.get("ALIAS_IV", "00" * 16))
        p = padding.PKCS7(128).padder()
        data = p.update(alias) + p.finalize()
        e = Cipher(algorithms.AES(bytes.fromhex(psk)), modes.CBC(iv)).encryptor()
        return base64.b64encode(e.update(data) + e.finalize()).decode()


def link_pairs(nodes):
    """link_id -> [(node, link설정), (node, link설정)]"""
    pairs = {}
    for n in nodes:
        for l in n.links:
            pairs.setdefault(l["link_id"], []).append((n, l))
    return pairs


# ---- SSE ---------------------------------------------------------------------

def parse_event(block):
    """SSE 이벤트 하나 -> (JSON 객체 또는 None, data 줄 수)"""
    lines = []
    for line in block.split("\n"):
        if line.startswith(":") or not line:
            continue                      # 주석(keepalive)
        if line.startswith("data:"):
            v = line[5:]
            lines.append(v[1:] if v.startswith(" ") else v)
    if not lines:
        return None, 0
    return json.loads("\n".join(lines)), len(lines)


async def collect(session, node, seconds):
    """seconds 동안 원시키를 구독해 raw_key_id -> (raw_key, notification) 반환"""
    keys, problems = {}, []
    url = f"{node.base}/QKD_API/data/kt-qkd-node:raw-key"
    async with session.get(url, headers={"Accept": "text/event-stream"}) as r:
        if r.status != 200:
            return keys, [f"구독 응답 {r.status}"]
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        buf = ""
        while True:
            remain = end - loop.time()
            if remain <= 0:
                break
            try:
                chunk = await asyncio.wait_for(r.content.readany(), remain)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            buf += chunk.decode()
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                obj, n_lines = parse_event(block)
                if obj is None:
                    continue
                rk = obj["ietf-restconf:notification"]["qkd-node:raw-key"]
                if set(rk) != RAW_KEY_FIELDS:
                    problems.append(f"필드 불일치: {sorted(rk)}")
                if rk["qkd_node_id"] != node.node_id:
                    problems.append(f"qkd_node_id 불일치: {rk['qkd_node_id']}")
                if n_lines < 2:
                    problems.append("data 줄이 1줄뿐 (다중 줄 형식 아님)")
                keys[rk["raw_key_id"]] = rk["raw_key"]
    return keys, problems


# ---- 테스트 ------------------------------------------------------------------

class Result:
    def __init__(self):
        self.failed = 0

    def check(self, ok, msg):
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        if not ok:
            self.failed += 1

    def info(self, msg):
        print(f"  [INFO] {msg}")


async def t_status(s, nodes, res):
    print("1. 노드 상태")
    for n in nodes:
        async with s.get(f"{n.base}/sim/status") as r:
            st = await r.json()
        res.check(st["node"] == n.node_id, f"{n.name}: node_id 일치")
        want = sorted(l["link_id"] for l in n.links)
        got = sorted(l["link_id"] for l in st["links"])
        res.check(want == got, f"{n.name}: 링크 {got}")


async def t_registration(s, nodes, res):
    print("2. 등록 (TTAK 0225 7.9.1)")
    wrong = base64.b64encode(os.urandom(16)).decode()
    for n in nodes:
        async with s.get(f"{n.base}/sim/status") as r:
            registered = (await r.json())["registered"]
        if not registered:
            async with s.get(f"{n.base}/QKD_API/data/kt-qkd-node:raw-key") as r:
                res.check(r.status == 403, f"{n.name}: 등록 전 구독 거부 ({r.status})")
        else:
            res.info(f"{n.name}: 이미 등록됨, 등록 전 구독 거부 확인은 건너뜀")
        url = f"{n.base}/QKD_API/operations/qkdn-rpc-qkd-registration"
        async with s.post(url, data=json.dumps(n.alias_payload(wrong)), headers=YANG) as r:
            out = (await r.json())["qkdn-rpc-qkd-registration:output"]
        res.check(out["registration_response"] == "NOK", f"{n.name}: 틀린 alias → NOK")
        async with s.post(url, data=json.dumps(n.alias_payload(n.encrypted_alias())), headers=YANG) as r:
            out = (await r.json())["qkdn-rpc-qkd-registration:output"]
        res.check(out["registration_response"] == "OK", f"{n.name}: 올바른 alias → OK ({out['qkd_alias']})")


async def t_node_info(s, nodes, res):
    print("3. 노드·인터페이스 정보 (7.9.2, 7.9.4)")
    for n in nodes:
        async with s.get(f"{n.base}/QKD_API/data/qkd-node:qkd_node/qkd_interfaces") as r:
            ifs = (await r.json())["qkd-node:qkd_interfaces"]
        want = sorted(l["qkdi_id"] for l in n.links)
        res.check(sorted(i["qkdi_id"] for i in ifs) == want, f"{n.name}: 인터페이스 {len(ifs)}개")
        async with s.get(f"{n.base}/QKD_API/data/qkd-node:qkd_node") as r:
            node = (await r.json())["qkd-node:qkd_node"]
        res.check(len(node.get("qkd_links", [])) == len(n.links), f"{n.name}: 링크 정보 {len(n.links)}개")


async def t_keys(s, nodes, res, seconds):
    print(f"4. 원시키 스트림과 링크 양 끝 일치 ({seconds}초 동시 구독)")
    results = await asyncio.gather(*(collect(s, n, seconds) for n in nodes))
    keys = {n.name: k for n, (k, _) in zip(nodes, results)}
    for n, (k, probs) in zip(nodes, results):
        res.check(not probs, f"{n.name}: {len(k)}개 수신, 형식 이상 {len(set(probs))}종"
                  + (f" {sorted(set(probs))[:2]}" if probs else ""))
    for link_id, ends in link_pairs(nodes).items():
        if len(ends) != 2:
            res.check(False, f"{link_id}: 끝점이 {len(ends)}개 (2개여야 함)")
            continue
        (na, la), (nb, lb) = ends
        pre = link_id + ":"
        ka = {i: v for i, v in keys[na.name].items() if i.startswith(pre)}
        kb = {i: v for i, v in keys[nb.name].items() if i.startswith(pre)}
        common = set(ka) & set(kb)
        diff = [i for i in common if ka[i] != kb[i]]
        faulty = any(float(l.get(f, 0)) > 0 for l in (la, lb) for f in ("drop_rate", "flip_rate")) \
            or any(float(n.env.get(v, 0)) > 0 for n in (na, nb) for v in ("DROP_RATE", "FLIP_RATE"))
        res.check(len(common) > 0, f"{link_id}: {na.name} {len(ka)}개 / {nb.name} {len(kb)}개 / 공통 {len(common)}개")
        if faulty:
            res.info(f"{link_id}: 장애 주입 설정됨, 값 불일치 {len(diff)}개 (정보만 표시)")
        else:
            res.check(not diff, f"{link_id}: 공통 ID 값 불일치 {len(diff)}개")


async def t_link_toggle(s, nodes, res):
    print("5. 링크 on/off (/sim/link)")
    n = nodes[0]
    link_id = n.links[0]["link_id"]
    interval = float(n.env.get("KEY_INTERVAL", "1.0"))

    async def generated():
        async with s.get(f"{n.base}/sim/status") as r:
            st = await r.json()
        return next(l["generated"] for l in st["links"] if l["link_id"] == link_id)

    try:
        async with s.post(f"{n.base}/sim/link", json={"link_id": link_id, "up": False}) as r:
            res.check((await r.json())[link_id] is False, f"{n.name}/{link_id}: down 설정")
        g1 = await generated()
        await asyncio.sleep(interval * 3)
        res.check(await generated() == g1, f"{n.name}/{link_id}: down 동안 생성 멈춤")
    finally:
        async with s.post(f"{n.base}/sim/link", json={"link_id": link_id, "up": True}) as r:
            res.check((await r.json())[link_id] is True, f"{n.name}/{link_id}: up 복구")
    g2 = await generated()
    await asyncio.sleep(interval * 3)
    res.check(await generated() > g2, f"{n.name}/{link_id}: up 후 생성 재개")


async def run_tests(nodes, seconds):
    res = Result()
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=3)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        await t_status(s, nodes, res)
        await t_registration(s, nodes, res)
        await t_node_info(s, nodes, res)
        await t_keys(s, nodes, res, seconds)
        await t_link_toggle(s, nodes, res)
    return res.failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="반드시 로컬 프로세스로 기동")
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    raw = run_local.load_nodes()
    nodes = [Node(d) for d in raw]
    up = [run_local.is_up(n.port) for n in nodes]

    procs = []
    if args.local or not any(up):
        procs = run_local.start(raw)
        print(f"목업을 로컬로 기동함 ({len(nodes)}개, 로그: {run_local.LOG_DIR})\n")
    elif not all(up):
        down = [n.name for n, u in zip(nodes, up) if not u]
        raise SystemExit(f"일부 노드만 떠 있음: {down} 가 응답 없음")
    else:
        print(f"이미 떠 있는 목업 사용 ({len(nodes)}개, 도커 또는 run_local)\n")

    try:
        failed = asyncio.run(run_tests(nodes, args.seconds))
    finally:
        run_local.stop(procs)
    print(f"\n결과: {'모두 통과' if failed == 0 else f'{failed}건 실패'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()