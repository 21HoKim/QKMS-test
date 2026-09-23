# 다단계 빌드: 호스트(Fedora 44)와 같은 배포판으로 빌드해 패키지 이름·버전을 맞춘다.
FROM fedora:44 AS build
RUN dnf -y install gcc-c++ make findutils gawk \
        boost-devel openssl-devel \
        soci-devel soci-mysql-devel mariadb-connector-c-devel \
    && dnf clean all
WORKDIR /work/src/qkms
COPY . .
RUN mkdir -p /work/build && make
# 산출물 main 의 위치(build/ 또는 src/qkms/)와 관계없이 찾아서 고정 경로로 복사
RUN set -e; BIN="$(find /work -type f -name main -perm -u+x | head -n 1)"; \
    test -n "$BIN" || { echo "빌드 산출물 main 을 찾지 못함" >&2; exit 1; }; \
    cp "$BIN" /qkms
# 링크된 공유 라이브러리를 실제 경로(/usr/lib64)로 풀어서 수집 (Fedora는 /lib64 가 심볼릭 링크)
RUN mkdir -p /deps && ldd /qkms | awk '/=> \// {print $3}' \
    | xargs -r readlink -f | xargs -r -I{} cp --parents {} /deps

FROM fedora:44
# SOCI MySQL 백엔드(MariaDB 접속용)는 실행 중에 동적으로 불러올 수 있으므로 패키지로 설치
RUN dnf -y install soci soci-mysql && dnf clean all
COPY --from=build /deps/ /
COPY --from=build /qkms /usr/local/bin/qkms
ENTRYPOINT ["/usr/local/bin/qkms"]