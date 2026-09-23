#!/usr/bin/env python3
"""QKD 장치 시뮬레이터 — TTAK.KO-01.0225/R1 의 QKD 측 최소 구현 (QKMS 개발용 목업).

한 프로세스 = QKD 노드 하나. 노드는 양자 링크(인터페이스)를 여러 개 가질 수 있다 (LINKS).

"양자 채널" 가정
  링크 양 끝의 두 QKD 가 같은 link_id / seed 와 같은 SIM_EPOCH 를 가진다.
  벽시계 기반 블록 번호 seq 에 대해 key = HMAC-SHA256(seed, link_id || seq) 를 각자 계산하므로,
  두 QKD 사이 네트워크 연결 없이도 같은 raw_key_id 에 같은 키가 생긴다.
  (키 값은 개념상 후처리까지 끝난 최종 키. 표준 명칭이 raw_key 일 뿐이다.)

raw_key_id 규칙 (목업 가정)
  "<link_id>:<seq>". 표 7-12 raw-key 모듈에는 링크/인터페이스 필드가 없으므로,
  링크가 여러 개인 노드에서 QKMS 는 raw_key_id 접두어로 링크를 구분한다.

장애 주입
  drop_rate : 이 쪽에서만 블록을 잃음  → 양 끝 QKMS 의 키 ID 집합이 어긋남
  flip_rate : 이 쪽 키에서만 1비트 반전 → 같은 ID, 다른 값
  POST /sim/link {"link_id": "...", "up": false} : 이 쪽 해당 링크 생성 중단

환경변수
  QKD_NODE_ID (필수), LINKS (필수, JSON 배열), PORT, SIM_EPOCH, KEY_BYTES, KEY_INTERVAL,
  BUFFER_BLOCKS, DROP_RATE, FLIP_RATE, QKD_ALIAS, ALIAS_PSK, ALIAS_IV, REQUIRE_REGISTRATION, QKMS_URL
  LINKS 원소: {"link_id","seed"(hex),"qkdi_id","peer_node_id","peer_qkdi_id","role",
               "drop_rate"(선택),"flip_rate"(선택)}
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from aiohttp import ClientSession, web

E = os.environ.get
NODE_ID = E("QKD_NODE_ID", "")
SIM_EPOCH = float(E("SIM_EPOCH", "1767225600"))      # 2026-01-01T00:00Z, 전 노드 동일
KEY_BYTES = int(E("KEY_BYTES", "32"))
KEY_INTERVAL = float(E("KEY_INTERVAL", "1.0"))       # 링크당 블록 주기(s), SKR ≈ KEY_BYTES*8/KEY_INTERVAL
BUFFER_BLOCKS = int(E("BUFFER_BLOCKS", "256"))       # QKMS 미접속 시 보관량, 넘치면 오래된 것부터 폐기
DROP_RATE = float(E("DROP_RATE", "0"))               # 링크별 값이 없을 때 기본값
FLIP_RATE = float(E("FLIP_RATE", "0"))
QKD_ALIAS = E("QKD_ALIAS", "QKD01")
ALIAS_PSK = E("ALIAS_PSK")                           # hex 32B. 없으면 qkd_alias 를 평문으로 받음
ALIAS_IV = bytes.fromhex(E("ALIAS_IV", "00" * 16))   # 가정: 표준 예시에 IV 전달 방법이 없어 사전 공유로 둠
REQUIRE_REG = E("REQUIRE_REGISTRATION", "1") == "1"  # 등록 전에는 원시키 구독 거부
QKMS_URL = E("QKMS_URL")                             # 있으면 등록 성공 후 노드 정보를 QKMS 로 POST (7.9.2)


@dataclass
class Link:
    link_id: str
    seed: bytes
    qkdi_id: str
    peer_node_id: str
    peer_qkdi_id: str
    role: str
    drop_rate: float
    flip_rate: float
    up: bool = True
    seq: int = 0
    generated: int = 0


def load_links():
    links = []
    for c in json.loads(E("LINKS", "[]")):
        links.append(Link(
            link_id=c["link_id"], seed=bytes.fromhex(c["seed"]), qkdi_id=c["qkdi_id"],
            peer_node_id=c.get("peer_node_id", ""), peer_qkdi_id=c.get("peer_qkdi_id", ""),
            role=c.get("role", "transmitter"),
            drop_rate=float(c.get("drop_rate", DROP_RATE)),
            flip_rate=float(c.get("flip_rate", FLIP_RATE))))
    return links


LINKS = {}                             # link_id -> Link
state = {"registered": not REQUIRE_REG}
pending = deque(maxlen=BUFFER_BLOCKS)  # 아직 QKMS 에 전달되지 않은 notification (전 링크 공용)
subscribers = set()                    # 구독 중인 QKMS 연결별 asyncio.Queue
background = set()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_seq():
    return int((time.time() - SIM_EPOCH) // KEY_INTERVAL)


def derive_key(link, seq):
    msg = link.link_id.encode() + seq.to_bytes(8, "big")
    out, ctr = b"", 0
    while len(out) < KEY_BYTES:
        out += hmac.new(link.seed, msg + ctr.to_bytes(4, "big"), hashlib.sha256).digest()
        ctr += 1
    return out[:KEY_BYTES]


def make_notification(link, seq, key):
    return {"ietf-restconf:notification": {
        "eventTime": now_iso(),
        "qkd-node:raw-key": {
            "qkd_node_id": NODE_ID,
            "raw_key_id": f"{link.link_id}:{seq}",
            "raw_key": base64.b64encode(key).decode(),
            "padding": 0,
            "enc_flag": False,
        }}}


def sse_encode(obj):
    # 표준 7.9.5 예시처럼 여러 줄 JSON 을 줄마다 "data: " 로 보냄.
    # 수신측은 빈 줄이 나올 때까지 data 줄들을 "\n" 으로 이어 붙인 뒤 파싱해야 한다.
    lines = json.dumps(obj, indent=1).splitlines()
    return ("".join(f"data: {line}\n" for line in lines) + "\n").encode()


def yang(obj, status=200):
    return web.json_response(obj, status=status, content_type="application/yang-data+json")


def interface_info(link):
    act = "ACT" if link.up else "DEACT"
    return {"qkdi_id": link.qkdi_id,
            "capabilities": {"role_support": link.role},
            "interface_status": {"operation_status": act, "admin_status": "ACT"}}


def node_info():
    # 간략화 버전. 7.2 qkd-node 모듈 표를 보고 필드명/구조를 맞춰 채울 것
    # (특히 qkd_node_id, qkd_links, local 키 이름은 표 확인 필요).
    links = []
    for l in LINKS.values():
        skr = int(KEY_BYTES * 8 / KEY_INTERVAL) if l.up else 0
        links.append({
            "local": {"interface": l.qkdi_id},
            "remote": {"qkd_node": l.peer_node_id, "interface": l.peer_qkdi_id},
            "performance": {"skr": skr, "eskr": skr},
            "link_attribute": "Quantum"})
    return {"qkd-node:qkd_node": {
        "qkd_node_id": NODE_ID,
        "qkd_interfaces": [interface_info(l) for l in LINKS.values()],
        "qkd_links": links}}


def emit(n):
    if subscribers:
        for q in subscribers:
            q.put_nowait(n)
    else:
        pending.append(n)


async def generator():
    start = current_seq()
    for l in LINKS.values():
        l.seq = start
    while True:
        target = current_seq()
        for l in LINKS.values():
            while l.seq < target:
                l.seq += 1
                if not l.up or random.random() < l.drop_rate:
                    continue
                key = bytearray(derive_key(l, l.seq))
                if random.random() < l.flip_rate:
                    key[random.randrange(KEY_BYTES)] ^= 1 << random.randrange(8)
                l.generated += 1
                emit(make_notification(l, l.seq, bytes(key)))
        await asyncio.sleep(min(KEY_INTERVAL, 0.2))


# ---- TTAK.KO-01.0225 엔드포인트 -------------------------------------------------

async def raw_key_stream(request):
    if not state["registered"]:
        return yang({"error": "QKD not registered"}, status=403)
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                       "Cache-Control": "no-cache"})
    await resp.prepare(request)
    q = asyncio.Queue()
    while pending:                      # 밀린 키 먼저
        q.put_nowait(pending.popleft())
    subscribers.add(q)
    try:
        while True:
            try:
                n = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                await resp.write(b": keepalive\n\n")   # SSE 주석 줄, 수신측은 무시해야 함
                continue
            await resp.write(sse_encode(n))
    except ConnectionResetError:
        pass
    finally:
        subscribers.discard(q)
        left = []
        while not q.empty():
            left.append(q.get_nowait())
        pending.extendleft(reversed(left))       # 못 보낸 키는 다음 구독자에게
    return resp


def decrypt_alias(b64):
    if not ALIAS_PSK:
        return b64
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    d = Cipher(algorithms.AES(bytes.fromhex(ALIAS_PSK)), modes.CBC(ALIAS_IV)).decryptor()
    padded = d.update(base64.b64decode(b64)) + d.finalize()
    u = padding.PKCS7(128).unpadder()
    return (u.update(padded) + u.finalize()).decode()


async def registration(request):
    try:
        body = await request.json()
        alias = decrypt_alias(body["qkdn-rpc-qkd-registration:input"]["qkd_alias"])
    except Exception:
        alias = None
    ok = alias == QKD_ALIAS
    if ok:
        state["registered"] = True
        if QKMS_URL:
            t = asyncio.create_task(push_node_info())
            background.add(t)
            t.add_done_callback(background.discard)
    # 가정: 실패 응답 형식은 표준 예시에 없어 "NOK" 로 둠
    return yang({"qkdn-rpc-qkd-registration:output": {
        "qkd_alias": alias or "",
        "registration_response": "OK" if ok else "NOK"}})


async def push_node_info():
    url = f"{QKMS_URL}/QKD_API/data/qkd-node:qkd_node"
    try:
        async with ClientSession() as s:
            async with s.post(url, data=json.dumps(node_info()),
                              headers={"Content-Type": "application/yang-data+json"}) as r:
                print(f"[node-info] POST {url} -> {r.status}", flush=True)
    except Exception as e:
        print(f"[node-info] POST {url} failed: {e}", flush=True)


async def get_node(request):
    return yang(node_info())


async def get_interfaces(request):
    return yang({"qkd-node:qkd_interfaces": [interface_info(l) for l in LINKS.values()]})


# ---- 시뮬레이터 제어 (표준 아님) -------------------------------------------------

async def sim_link(request):
    body = await request.json()
    target = body.get("link_id")
    if target is not None and target not in LINKS:
        return web.json_response({"error": f"unknown link {target}"}, status=404)
    for l in LINKS.values():
        if target is None or l.link_id == target:
            l.up = bool(body.get("up", True))
    return web.json_response({l.link_id: l.up for l in LINKS.values()})


async def sim_status(request):
    return web.json_response({
        "node": NODE_ID, "registered": state["registered"],
        "pending": len(pending), "subscribers": len(subscribers),
        "links": [{"link_id": l.link_id, "role": l.role, "up": l.up, "seq": l.seq,
                   "generated": l.generated, "drop_rate": l.drop_rate, "flip_rate": l.flip_rate}
                  for l in LINKS.values()]})


async def on_startup(app):
    t = asyncio.create_task(generator())
    background.add(t)


def main():
    if not NODE_ID:
        raise SystemExit("환경변수 필요: QKD_NODE_ID")
    for l in load_links():
        LINKS[l.link_id] = l
    if not LINKS:
        raise SystemExit("환경변수 필요: LINKS (JSON 배열, 링크 1개 이상)")
    print(f"[qkd-sim] node={NODE_ID} links={list(LINKS)}", flush=True)
    app = web.Application()
    app.add_routes([
        web.post("/QKD_API/operations/qkdn-rpc-qkd-registration", registration),
        web.get("/QKD_API/data/qkd-node:qkd_node", get_node),
        web.get("/QKD_API/data/qkd-node:qkd_node/qkd_interfaces", get_interfaces),
        web.get("/QKD_API/data/kt-qkd-node:raw-key", raw_key_stream),  # 표준 예시 경로
        web.get("/QKD_API/data/qkd-node:raw-key", raw_key_stream),
        web.post("/sim/link", sim_link),
        web.get("/sim/status", sim_status),
    ])
    app.on_startup.append(on_startup)
    web.run_app(app, port=int(E("PORT", "8080")), print=None)


if __name__ == "__main__":
    main()
