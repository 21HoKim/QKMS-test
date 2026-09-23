# fixtures — QKMS가 주고받는 실제 메시지

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
