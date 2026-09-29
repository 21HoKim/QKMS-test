================================================================================
 코딩 규칙 (C++17 / Boost)
================================================================================

0. 개요
  - 목표: C처럼 읽히는 C++
  - 원칙 출처: Linux kernel coding style 4, 5, 6, 8, 12절
      https://www.kernel.org/doc/html/latest/process/coding-style.html
  - 포맷 출처: Google C++ Style Guide (clang-format으로 자동 적용)
      https://google.github.io/styleguide/cppguide.html
  - 판단 보조 자료: C++ Core Guidelines
      https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines
  - Google 스타일 중 제외 항목: 예외 사용 금지 규칙, CamelCase 함수 이름
    (3절, 7절의 규칙 우선)


1. 포맷
  - 기준: 저장소 루트의 .clang-format (내용: BasedOnStyle: Google)
  - 들여쓰기: 공백 2칸, 탭 문자 미사용
  - 한 줄 길이: 최대 80자
  - 정렬 방법: 커밋 전 "clang-format -i <파일>" 실행, 수동 정렬 금지


2. 파일
  - 확장자: 소스 .cpp, 헤더 .hpp
  - 헤더 첫 줄: #pragma once
  - using namespace: .cpp에서만 허용, 헤더에서 금지
  - #include 순서: clang-format 자동 정렬 결과
    (Google 스타일은 <...> 헤더를 표준/Boost 구분 없이 한 그룹으로 정렬,
     프로젝트 헤더 "..." 는 별도 그룹)
  - 프로젝트 코드 위치: namespace qkms { ... } 내부


3. 이름
  - 변수, 함수: snake_case
      예) raw_key_id, connect_to()
  - 타입(struct, class, enum class): snake_case
      예) raw_key, key_state
  - 상수(constexpr): UPPER_SNAKE_CASE
      예) KEY_BYTES, READ_BUF_BYTES
  - enum class 값: UPPER_SNAKE_CASE
      예) key_state::SYNCED
  - 네임스페이스: 소문자 한 단어
      예) qkms
  - snake_case 채택 이유: 표준 라이브러리, Boost, 커널과 동일한 형식
  - 전역 이름(함수, 상수): 의미가 드러나는 설명적 이름 (커널 4절)
  - 좁은 범위의 지역 변수: 짧은 이름 허용
      예) i, len, ec
  - 상수 이름 제한: 흔한 단어 하나로 된 이름 금지
      예) ERROR, DEBUG, MAX 금지 -> MAX_KEY_BYTES 형태 사용
      이유: 시스템 헤더 매크로와의 이름 충돌 방지


4. 상수: #define 대신 constexpr
  - 선언 형식
      constexpr std::size_t KEY_BYTES = 32;
  - 커널의 #define 사용 이유: C에 컴파일 시점 상수 선언 수단이
    #define과 enum뿐인 점 (커널 12절)
  - constexpr와 #define의 차이
      - 타입 유무: constexpr는 타입 있음(std::size_t 등),
        #define은 타입 없는 텍스트
      - 적용 범위: constexpr는 선언된 namespace 내부로 한정,
        #define은 정의 이후 모든 코드(다른 헤더 포함)에 적용
      - 치환 방식: constexpr는 값, #define은 텍스트 치환
        (#define N 1+1 일 때 N*2 = 1+1*2 = 3 이 되는 문제)
      - 디버거 표시: constexpr는 이름으로 표시, #define은 표시 불가
  - 관련 상수 여러 개: enum class 사용 (커널 12절 enum 권장 규칙의 C++판)
  - #define 허용 범위: 전처리기가 꼭 필요한 경우만
  - 함수형 매크로: 금지, 일반 함수로 대체 (커널 12절)


5. 함수
  - 기능: 함수 하나당 한 가지 기능 (커널 6절)
  - 길이: 한두 화면 이내, 대략 50줄 (커널 6절)
  - 중첩: 최대 3단계, 초과 시 조기 return 또는 함수 분리 (커널 6절)
  - 인자 전달 방식
      - 읽기 전용 큰 값(std::string, struct): const T&
          예) const std::string& host
      - 함수가 변경하는 값(출력용 포함): T&
          예) tcp::socket& sock
      - 작은 값(int, bool, std::size_t): 값 전달
          예) std::size_t len
  - 출력용 인자 위치: 인자 목록의 마지막


6. 사용 기능 / 미사용 기능
  - 사용
      - struct + 자유 함수
      - std::string, std::vector, std::array
      - 참조(&), const, constexpr
      - enum class
      - 명시적 타입 표기
      - namespace
  - 미사용 (필요 시 재논의)
      - 상속, virtual
      - new / delete, malloc / free
      - 직접 정의하는 템플릿
      - 연산자 오버로딩
      - auto (반복자, 긴 템플릿 타입만 예외)
      - #define 상수, 함수형 매크로
  - 타입 별명: 프로젝트 타입에 대한 using, typedef 별명 금지 (커널 5절)
  - 별명 예외: 라이브러리 이름 축약
      namespace asio = boost::asio;
      using asio::ip::tcp;


7. 에러 처리: error_code 방식 통일
  - 원칙: C처럼 반환값으로 에러 확인, 예외 미사용
  - Asio 호출: boost::system::error_code& 인자를 받는 오버로드 사용
    (예외 대신 인자에 에러 기록)
  - 실패 가능한 프로젝트 함수: boost::system::error_code 반환,
    결과는 출력용 참조 인자로 전달
  - 검사 시점: 호출 직후 즉시 검사, if (ec) 가 참이면 에러
  - 에러 메시지: ec.message()
  - 최종 처리 위치: main, 0이 아닌 값 반환
  - 예시 (clang-format 적용 결과와 동일)

      namespace qkms {

      constexpr std::size_t READ_BUF_BYTES = 1024;

      // host:port 로 TCP 연결한다. 성공하면 sock 이 연결된 상태가 된다.
      boost::system::error_code connect_to(tcp::resolver& resolver,
                                           const std::string& host,
                                           const std::string& port,
                                           tcp::socket& sock) {
        boost::system::error_code ec;

        tcp::resolver::results_type endpoints = resolver.resolve(host, port, ec);
        if (ec) {
          return ec;
        }

        asio::connect(sock, endpoints, ec);
        return ec;
      }

      }  // namespace qkms

      int main() {
        asio::io_context io;
        tcp::resolver resolver(io);
        tcp::socket sock(io);

        boost::system::error_code ec =
            qkms::connect_to(resolver, "localhost", "18081", sock);
        if (ec) {
          std::cerr << "connect: " << ec.message() << '\n';
          return 1;
        }
        return 0;
      }


8. 주석
  - 내용: 코드가 무엇을 하는지 기술, 어떻게 하는지는 미기술 (커널 8절)
  - 함수 주석 위치: 함수 선언 바로 위
  - 함수 주석 내용: 동작, 인자, 반환값의 의미
  - 함수 본문 내 주석: 최소화, 코드만으로 이유 파악이 불가능한 곳에 한정
      예) // 목업은 연결을 닫지 않으므로 eof 미발생
  - 표준 관련 코드: 조항 번호 표기
      예) // TTAK.KO-01.0225 7.9.5 원시키 구독


9. 빌드
  - 컴파일 옵션: -std=c++17 -Wall -Wextra
  - 경고: 전부 제거