#!/usr/bin/env bash
# QKMS 개발용 도커·테스트 명령 모음. 저장소 루트에 두고 실행 (chmod +x dev.sh)
#
#   ./dev.sh check          전체 점검: 빌드 → 목업 기동 → QKMS 등록·구독 확인 → 목업 테스트
#   ./dev.sh up             QKD 목업 4개만 빌드·기동
#   ./dev.sh up-all         목업 + QKMS 4개 빌드·기동
#   ./dev.sh test           떠 있는 목업 대상으로 test_qkd.py 실행
#   ./dev.sh local          도커 없이 로컬로 목업을 띄워 test_qkd.py 실행
#   ./dev.sh fixtures       fixtures/ 재생성
#   ./dev.sh ps             컨테이너 상태
#   ./dev.sh logs [서비스]  로그 따라가기 (예: ./dev.sh logs qkms-a1)
#   ./dev.sh shell <노드>   QKMS 컨테이너 쉘 (a1|a2|b1|b2)
#   ./dev.sh down           전부 종료
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
QKD_DIR="$ROOT/src/qkd"
MOCK_PORTS=(18081 18082 18083 18084)
QKMS_NODES=(a1 a2 b1 b2)

# docker compose v2 플러그인이 없으면 docker-compose 사용
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    COMPOSE=()
fi

# 가상환경(.venv)이 있으면 그 파이썬 사용
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY="$ROOT/.venv/bin/python"
else
    PY=python3
fi

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*"; }

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

need_docker() {
    if [[ ${#COMPOSE[@]} -eq 0 ]]; then
        fail "docker compose 를 찾지 못함"
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        fail "도커 데몬에 접근할 수 없음 (sudo systemctl start docker / docker 그룹 확인)"
        exit 1
    fi
}

dc()     { "${COMPOSE[@]}" "$@"; }
dc_all() { "${COMPOSE[@]}" --profile qkms "$@"; }

wait_mocks() {
    local deadline=$((SECONDS + 30)) port
    for port in "${MOCK_PORTS[@]}"; do
        until curl -sf "http://127.0.0.1:${port}/sim/status" >/dev/null; do
            if (( SECONDS > deadline )); then
                fail "목업 응답 없음: 포트 ${port} (./dev.sh logs 로 확인)"
                return 1
            fi
            sleep 0.5
        done
    done
    ok "목업 4개 응답 확인"
}

run_mock_test() {
    (cd "$QKD_DIR" && "$PY" test_qkd.py "$@")
}

show_qkms_state() {
    local node id state
    for node in "${QKMS_NODES[@]}"; do
        id="$(dc_all ps -aq "qkms-${node}" 2>/dev/null | head -n1)"
        if [[ -n "$id" ]]; then
            state="$(docker inspect -f '{{.State.Status}} (exit {{.State.ExitCode}})' "$id")"
        else
            state="컨테이너 없음"
        fi
        info "qkms-${node}: ${state}"
    done
}

# QKMS 컨테이너 네트워크에서 자기 노드 목업에 접근되는지 확인 (Phase 0-2 완료 기준)
# curl 없이 bash 의 /dev/tcp 로 요청하므로 이미지에 추가 패키지가 필요 없음
check_qkms_reach() {
    local node rc=0
    for node in "${QKMS_NODES[@]}"; do
        if dc_all run --rm --no-deps -T --entrypoint bash "qkms-${node}" -c "
            exec 3<>/dev/tcp/qkd-${node}/8080 || exit 1
            printf 'GET /sim/status HTTP/1.0\r\nHost: qkd-${node}\r\n\r\n' >&3
            timeout 3 cat <&3 | grep -q '\"node\"'
        " >/dev/null 2>&1; then
            ok "qkms-${node} → qkd-${node}:8080 접근"
        else
            fail "qkms-${node} → qkd-${node}:8080 접근 실패"
            rc=1
        fi
    done
    return $rc
}

# 목업 /sim/status 에서 "registered subscribers" 출력 (조회 실패 시 빈 문자열)
mock_link_state() {
    curl -sf "http://127.0.0.1:$1/sim/status" 2>/dev/null \
        | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(d["registered"], d["subscribers"])' \
        2>/dev/null || true
}

# QKMS 로그에서 마지막으로 도달한 단계 (main.cpp 의 출력 기준)
qkms_last_stage() {
    local logs
    logs="$(dc_all logs --no-color "qkms-$1" 2>/dev/null || true)"
    if   grep -q "subscribed" <<<"$logs"; then echo "구독 완료(subscribed)"
    elif grep -q "registered" <<<"$logs"; then echo "등록 완료(registered), 구독 전"
    elif grep -q "connected"  <<<"$logs"; then echo "TCP 연결(connected), 등록 전"
    elif grep -q "qkd: "      <<<"$logs"; then echo "시작됨, TCP 연결 전"
    else echo "출력 없음 (실행 안 됨)"
    fi
}

# QKMS ↔ 목업 실제 연결 확인: 목업이 등록 완료이고 구독자가 1 이상이어야 통과
# 목업 테스트(test_qkd.py)도 등록을 하므로 반드시 그보다 먼저 실행해야 의미가 있음
check_qkms_link() {
    local deadline=$((SECONDS + 20)) i node port st done_all rc=0
    local -A result=()
    while :; do
        done_all=1
        for i in "${!QKMS_NODES[@]}"; do
            node="${QKMS_NODES[$i]}"; port="${MOCK_PORTS[$i]}"
            st="$(mock_link_state "$port")"
            result[$node]="$st"
            [[ "$st" == "True "[1-9]* ]] || done_all=0
        done
        (( done_all )) && break
        (( SECONDS > deadline )) && break
        sleep 1
    done

    for i in "${!QKMS_NODES[@]}"; do
        node="${QKMS_NODES[$i]}"
        st="${result[$node]}"
        if [[ "$st" == "True "[1-9]* ]]; then
            ok "qkms-${node} ↔ qkd-${node}: 등록 + 원시키 구독 연결"
            continue
        fi
        rc=1
        if [[ -z "$st" ]]; then
            fail "qkms-${node}: 목업 qkd-${node} 상태 조회 실패"
        elif [[ "$st" == False* ]]; then
            fail "qkms-${node}: 등록 미완료 (목업 registered=false)"
        else
            fail "qkms-${node}: 등록은 됐지만 원시키 구독 연결 없음 (목업 subscribers=0)"
        fi
        info "  컨테이너: $(docker inspect -f '{{.State.Status}} (exit {{.State.ExitCode}})' \
            "$(dc_all ps -aq "qkms-${node}" | head -n1)" 2>/dev/null || echo '없음')"
        info "  마지막 단계: $(qkms_last_stage "$node")"
        info "  최근 로그:"
        dc_all logs --no-color --tail=10 "qkms-${node}" 2>/dev/null | sed 's/^/      /' || true
    done
    return $rc
}

cmd_check() {
    need_docker
    local rc=0 node services=()
    for node in "${QKMS_NODES[@]}"; do services+=("qkms-${node}"); done

    info "1/5 이미지 빌드 (QKMS 컴파일 포함)"
    dc_all build
    info "2/5 목업 새로 기동 (이전 등록 상태 초기화)"
    dc_all rm -sf "${services[@]}" >/dev/null 2>&1 || true
    dc up -d --force-recreate
    wait_mocks || return 1
    info "3/5 QKMS 기동 및 목업 연결 확인"
    check_qkms_reach || rc=1
    dc_all up -d --no-deps "${services[@]}"
    check_qkms_link || rc=1
    show_qkms_state
    info "4/5 목업 테스트"
    run_mock_test || rc=1
    info "5/5 결과"
    if (( rc == 0 )); then
        ok "전체 점검 통과 (종료: ./dev.sh down)"
    else
        fail "일부 실패 (로그: ./dev.sh logs <서비스>)"
    fi
    return $rc
}

cmd="${1:-help}"
shift || true
case "$cmd" in
    check)    cmd_check ;;
    up)       need_docker; dc up -d --build; wait_mocks ;;
    up-all)   need_docker; dc_all up -d --build; wait_mocks ;;
    test)     run_mock_test "$@" ;;
    local)    run_mock_test --local "$@" ;;
    fixtures) (cd "$QKD_DIR" && "$PY" gen_fixtures.py) ;;
    ps)       need_docker; dc_all ps -a ;;
    logs)     need_docker; dc_all logs -f "$@" ;;
    shell)
        need_docker
        node="${1:?노드 이름 필요: a1|a2|b1|b2}"
        dc_all run --rm --entrypoint bash "qkms-${node}"
        ;;
    down)     need_docker; dc_all down ;;
    help|-h|--help) usage ;;
    *)        fail "알 수 없는 명령: $cmd"; usage; exit 1 ;;
esac
