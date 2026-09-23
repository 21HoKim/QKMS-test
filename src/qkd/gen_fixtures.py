#!/usr/bin/env python3
"""QKMS 가 QKD 와 주고받는 실제 메시지를 목업에서 캡처해 fixtures/ 에 저장한다.

- 손으로 쓴 예시가 아니라 목업이 실제로 보낸 바이트를 그대로 저장한다.
  목업이나 docker-compose.yml 을 바꾸면 이 스크립트를 다시 실행하면 된다.
- 도커와 포트가 겹치지 않도록 compose 포트 + 1000 (19081~) 으로 따로 띄운다.
  도커가 떠 있어도 실행할 수 있다.
- 캡처 대상: qkd-a2 (링크 2개), 링크 양 끝 비교용으로 qkd-b1.

사용
  python3 gen_fixtures.py          # src/qkd/fixtures/ 생성(덮어씀)
"""
import asyncio
import base64
import json
import os
import shutil
from pathlib import Path

import run_local
from test_qkd import Node, parse_event

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures"
PORT_OFFSET = 1000
CAPTURE_PORT = 19180              # QKMS 역할을 대신하는 캡처 서버 (7.9.2 노드 정보 POST 수신)
TARGET, PEER = "qkd-a2", "qkd-b1"
STREAM_SECONDS = 4.0


# ---- raw HTTP 유틸 -----------------------------------------------------------

def build_request(method, path, host, headers=None, body=b""):
    h = {"Host": host, **(headers or {})}
    if body:
        h["Content-Length"] = str(len(body))
    lines = [f"{method} {path} HTTP/1.1"] + [f"{k}: {v}" for k, v in h.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


async def exchange(port, request, seconds=None):
    """요청을 보내고 응답 바이트를 그대로 받는다. seconds 가 있으면 그 시간만큼만 읽는다(스트림용)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    data = b""
    loop = asyncio.get_running_loop()
    end = loop.time() + (seconds or 10)
    while (remain := end - loop.time()) > 0:
        try:
            chunk = await asyncio.wait_for(reader.read(65536), remain)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        data += chunk
    writer.close()
    return data


def split_response(raw):
    head, _, body = raw.partition(b"\r\n\r\n")
    return head.decode(), body


def dechunk(body):
    out = b""
    while body:
        line, _, rest = body.partition(b"\r\n")
        if not line:
            break
        size = int(line.split(b";")[0], 16)
        if size == 0:
            break
        out += rest[:size]
        if len(rest) < size:          # 캡처 종료 시점에 잘린 chunk
            break
        body = rest[size + 2:]
    return out


def events_from_sse(text):
    return [obj for obj, _ in (parse_event(b) for b in text.split("\n\n")) if obj]


# ---- 캡처 서버 (QKMS 대역) ---------------------------------------------------

async def start_capture_server():
    captured = asyncio.get_running_loop().create_future()

    async def handle(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        for line in head.decode().split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1])
        body = await reader.readexactly(length)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        if not captured.done():
            captured.set_result(head + body)

    server = await asyncio.start_server(handle, "127.0.0.1", CAPTURE_PORT)
    return server, captured


# ---- 저장 --------------------------------------------------------------------

def save_bytes(name, data):
    (OUT / name).write_bytes(data)


def save_json(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


README = r"""# fixtures — QKMS가 주고받는 실제 메시지

`gen_fixtures.py`가 QKD 목업(qkd-a2, qkd-b1)에서 **실제로 오간 바이트**를 캡처해 만든 파일이다.
목업이나 `docker-compose.yml`을 바꿨다면 `python3 gen_fixtures.py`로 다시 만든다.
키 값, 시각, `raw_key_id` 번호는 실행할 때마다 달라진다.

## 파일 목록

| 파일 | 방향 | 시점 | QKMS가 할 일 |
|---|---|---|---|
| `01_registration_request.http` | QKMS → QKD | 최초 등록 (0225 7.9.1) | 이 요청을 **만들어 보냄**. alias는 PSK로 AES-256-CBC 암호화 후 base64 |
| `02_registration_response_ok.http` / `.json` | QKD → QKMS | 01의 응답 | `registration_response == "OK"`면 등록 완료로 처리 |
| `03_registration_response_nok.json` | QKD → QKMS | alias가 틀렸을 때 | 등록 실패 처리, 재시도 정책 결정 |
| `04_rawkey_subscribe_request.http` | QKMS → QKD | 등록 후 원시키 구독 (7.9.5) | 이 요청을 보내고 연결을 계속 유지 |
| `05_rawkey_response_403.http` | QKD → QKMS | 등록 전에 구독했을 때 | 등록부터 하도록 처리 |
| `06_rawkey_stream_wire.txt` | QKD → QKMS | 04의 응답, **소켓에서 받은 그대로** | HTTP 헤더 + chunked 인코딩. Beast 파서 시험용 |
| `07_rawkey_stream.sse` | QKD → QKMS | 06에서 chunk를 벗긴 본문 | SSE 이벤트 분리, `data:` 줄 결합 시험용 |
| `08_rawkey_event.json` | — | 07의 이벤트 하나를 파싱한 결과 | JSON 필드 추출 시험용 (표 7-12의 5개 필드) |
| `09_node_info_push.http` / `.json` | QKD → QKMS | 등록 성공 직후 (7.9.2) | QKMS의 HTTP **서버**가 이 POST를 받아 노드 정보 저장, 200 응답 |
| `10_node_info_get.json` | QKD → QKMS | QKMS가 노드 정보 조회 시 | 형상 정보 갱신 (09와 같은 구조) |
| `11_interfaces_get.json` | QKD → QKMS | QKMS가 인터페이스 조회 시 (7.9.4) | 인터페이스 상태 갱신 |
| `12_rawkey_pair_qlink-ab.json` | — | a2와 b1이 같은 ID로 받은 키 쌍 | QKMS 간 동기화(ID·해시 비교) 단위 테스트용. `hex`는 키 바이트의 16진 표기 |

## 파싱할 때 주의할 점

- HTTP 헤더 줄 끝은 `\r\n`(CRLF), SSE 본문 줄 끝은 `\n`(LF)이다. 편집기에서 `^M`이 보이면 CR이다
- `Content-Type`은 `application/yang-data+json; charset=utf-8`처럼 파라미터가 붙을 수 있다. 문자열 전체 비교 대신 앞부분만 비교한다
- 원시키 응답은 `Transfer-Encoding: chunked`다
  - chunk 경계와 SSE 이벤트 경계는 일치한다는 보장이 없다. 받은 바이트를 버퍼에 쌓고 빈 줄(`\n\n`) 단위로 자른다
  - `06`은 캡처를 끊은 시점에서 잘려 있으므로 마지막 이벤트가 불완전할 수 있다 (실제 연결이 끊겼을 때와 같은 상황)
- SSE 이벤트 하나는 `data:` 줄 여러 개로 온다
  - 각 줄에서 `data:`와 그 뒤 공백 하나를 떼고 `\n`으로 이어 붙인 뒤 JSON으로 파싱한다
  - `:`로 시작하는 줄은 주석이다. 목업은 15초 동안 보낼 키가 없으면 `: keepalive` 줄을 보낸다 (이 캡처에는 없음)
- JSON 키에 YANG 모듈 접두어가 붙는다 (`"qkd-node:raw-key"`, `"ietf-restconf:notification"`). 콜론까지 포함한 문자열 그대로 키로 쓴다
- `raw_key`는 base64이고, 디코딩하면 32바이트다 (compose의 `KEY_BYTES`)
- `raw_key_id` 형식은 `<link_id>:<seq>`다 (목업 가정). 링크가 2개인 노드는 접두어로 어느 링크의 키인지 구분한다
- `09`의 `Host` 헤더는 도커 환경 기준(`qkms-a2:8080`)으로 바꿔 기록했다. 나머지는 캡처 그대로다
- `09`, `10`의 노드 정보 필드명 일부(`qkd_node_id`, `qkd_links`, `local`)는 목업의 추정이다. 표준 7.2 표와 대조할 것

## C++ 테스트에서 쓰는 방법 (예)

- `07_rawkey_stream.sse`를 읽어 임의 크기(예: 7바이트씩)로 잘라 SSE 파서에 넣고, 이벤트 수와 `raw_key_id` 목록이 맞는지 확인
- `06_rawkey_stream_wire.txt`를 `http::response_parser`에 넣어 헤더와 chunked 본문이 제대로 풀리는지 확인
- `09_node_info_push.http`를 QKMS 서버 포트로 그대로 보내 수신 처리 확인: `nc localhost 8080 < 09_node_info_push.http`
"""


# ---- 메인 --------------------------------------------------------------------

async def capture(nodes):
    a2 = next(n for n in nodes if n.name == TARGET)
    b1 = next(n for n in nodes if n.name == PEER)
    host = f"{TARGET}:8080"          # 도커 환경에서 QKMS 가 쓰는 주소 기준으로 기록
    reg_path = "/QKD_API/operations/qkdn-rpc-qkd-registration"
    raw_path = "/QKD_API/data/kt-qkd-node:raw-key"
    yang = {"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"}

    server, pushed = await start_capture_server()
    try:
        # 1) 등록 전 구독 → 403
        sub_req = build_request("GET", raw_path, host, {
            "Accept": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive"})
        save_bytes("04_rawkey_subscribe_request.http", sub_req)
        r403 = await exchange(a2.port, build_request("GET", raw_path, host, {
            "Accept": "text/event-stream", "Connection": "close"}))
        save_bytes("05_rawkey_response_403.http", r403)

        # 2) 틀린 alias → NOK
        wrong = json.dumps(a2.alias_payload(base64.b64encode(os.urandom(16)).decode()), indent=1).encode()
        nok = await exchange(a2.port, build_request("POST", reg_path, host, {**yang, "Connection": "close"}, wrong))
        save_json("03_registration_response_nok.json", json.loads(split_response(nok)[1]))

        # 3) 올바른 alias → OK (그리고 목업이 QKMS 로 노드 정보 POST)
        body = json.dumps(a2.alias_payload(a2.encrypted_alias()), indent=1).encode()
        req = build_request("POST", reg_path, host, {**yang, "Connection": "close"}, body)
        save_bytes("01_registration_request.http", req)
        ok = await exchange(a2.port, req)
        save_bytes("02_registration_response_ok.http", ok)
        save_json("02_registration_response_ok.json", json.loads(split_response(ok)[1]))

        push = await asyncio.wait_for(pushed, 5)
        # 캡처 서버 주소 대신 도커 환경 기준 Host 로 바꿔 기록 (길이 무관 헤더라 본문 영향 없음)
        push = push.replace(f"Host: 127.0.0.1:{CAPTURE_PORT}".encode(), b"Host: qkms-a2:8080", 1)
        save_bytes("09_node_info_push.http", push)
        save_json("09_node_info_push.json", json.loads(push.partition(b"\r\n\r\n")[2]))

        # 4) 조회
        for name, path, key in [("10_node_info_get.json", "/QKD_API/data/qkd-node:qkd_node", None),
                                ("11_interfaces_get.json", "/QKD_API/data/qkd-node:qkd_node/qkd_interfaces", None)]:
            raw = await exchange(a2.port, build_request("GET", path, host, {**yang, "Connection": "close"}))
            save_json(name, json.loads(split_response(raw)[1]))

        # 5) 원시키 스트림 (a2, b1 동시 구독)
        reg_b1 = json.dumps(b1.alias_payload(b1.encrypted_alias())).encode()
        await exchange(b1.port, build_request("POST", reg_path, f"{PEER}:8080",
                                              {**yang, "Connection": "close"}, reg_b1))
        wire_a2, wire_b1 = await asyncio.gather(
            exchange(a2.port, sub_req, STREAM_SECONDS),
            exchange(b1.port, build_request("GET", raw_path, f"{PEER}:8080",
                                            {"Accept": "text/event-stream"}), STREAM_SECONDS))
        save_bytes("06_rawkey_stream_wire.txt", wire_a2)
        sse_a2 = dechunk(split_response(wire_a2)[1]).decode()
        sse_b1 = dechunk(split_response(wire_b1)[1]).decode()
        (OUT / "07_rawkey_stream.sse").write_text(sse_a2, encoding="utf-8")

        ev_a2, ev_b1 = events_from_sse(sse_a2), events_from_sse(sse_b1)
        if ev_a2:
            save_json("08_rawkey_event.json", ev_a2[0])

        def keys(evs):
            out = {}
            for e in evs:
                rk = e["ietf-restconf:notification"]["qkd-node:raw-key"]
                out[rk["raw_key_id"]] = rk["raw_key"]
            return out

        ka, kb = keys(ev_a2), keys(ev_b1)
        common = sorted((i for i in set(ka) & set(kb) if i.startswith("qlink-ab:")),
                        key=lambda i: int(i.split(":")[1]))
        save_json("12_rawkey_pair_qlink-ab.json", {
            "_comment": f"같은 raw_key_id 에 대해 {TARGET} 쪽과 {PEER} 쪽이 받은 키. 동기화 로직 단위 테스트용",
            "pairs": [{"raw_key_id": i, TARGET: ka[i], PEER: kb[i],
                       "hex": base64.b64decode(ka[i]).hex(), "equal": ka[i] == kb[i]} for i in common]})
        return len(ev_a2), len(common)
    finally:
        server.close()
        await server.wait_closed()


def main():
    raw_nodes = [d for d in run_local.load_nodes() if d["name"] in (TARGET, PEER)]
    for d in raw_nodes:
        d["port"] += PORT_OFFSET
        d["env"]["PORT"] = str(d["port"])
        d["env"].pop("QKMS_URL", None)
        if d["name"] == TARGET:
            d["env"]["QKMS_URL"] = f"http://127.0.0.1:{CAPTURE_PORT}"
    nodes = [Node(d) for d in raw_nodes]

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    procs = run_local.start(raw_nodes)
    try:
        asyncio.run(asyncio.sleep(3))            # 버퍼에 키가 쌓이도록 대기
        n_events, n_pairs = asyncio.run(capture(nodes))
    finally:
        run_local.stop(procs)
    (OUT / "README.md").write_text(README, encoding="utf-8")
    print(f"fixtures 생성 완료: {OUT}")
    print(f"  원시키 이벤트 {n_events}개, qlink-ab 비교 쌍 {n_pairs}개")
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name}")


if __name__ == "__main__":
    main()