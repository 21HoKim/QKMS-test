# 다단계 빌드: 컨테이너 안에서 기존 makefile로 빌드하고, 실행에 필요한 것만 런타임 이미지로 옮긴다.
FROM ubuntu:24.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        g++ make libboost-all-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*
# 저장소 구조(src/qkms, build)를 그대로 재현해서 makefile의 상대 경로가 맞게 한다.
WORKDIR /work/src/qkms
COPY . .
RUN mkdir -p /work/build && make
# 산출물 main 의 위치(build/ 또는 src/qkms/)와 관계없이 찾아서 고정 경로로 복사
RUN set -e; BIN="$(find /work -type f -name main -perm -u+x | head -n 1)"; \
    test -n "$BIN" || { echo "빌드 산출물 main 을 찾지 못함" >&2; exit 1; }; \
    cp "$BIN" /qkms
# 링크된 공유 라이브러리(Boost, OpenSSL 등)를 자동 수집
RUN mkdir -p /deps && ldd /qkms | awk '/=> \// {print $3}' | xargs -r -I{} cp --parents {} /deps

FROM ubuntu:24.04
COPY --from=build /deps/ /
COPY --from=build /qkms /usr/local/bin/qkms
ENTRYPOINT ["/usr/local/bin/qkms"]