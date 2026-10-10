#include "kma.hpp"

#include <boost/json.hpp>
#include <iostream>
#include <sstream>

namespace asio = boost::asio;
namespace http = boost::beast::http;
namespace json = boost::json;
using asio::ip::tcp;
using namespace std;

namespace qkms::kma {

constexpr char ALIAS[] = "QKD01";
constexpr char QKD_ALIAS[] = "q7UotM2fJ2uSm6xdq1AdiA==";

// host:port TCP 연결
// resolver: 주소 변환기, host/port: 접속 대상, sock: 연결 대상 소켓(출력)
// 반환: 성공 시 빈 error_code, 실패 시 에러 정보
boost::system::error_code connect_socket(tcp::resolver& resolver,
                                         const string& host, const string& port,
                                         tcp::socket& sock) {
  boost::system::error_code ec;
  tcp::resolver::results_type endpoints = resolver.resolve(host, port, ec);
  if (ec) {
    return ec;
  }

  asio::connect(sock, endpoints, ec);
  return ec;
}

// QKD 등록 요청(HTTP POST) 문자열 생성
// host/port: Host 헤더에 기록할 접속 대상
// 반환: 헤더와 본문을 포함한 요청 문자열
string make_registration_request(const string& host, const string& port,
                                 const string& qkd_alias) {
  json::object input;
  input["qkd_alias"] = qkd_alias;

  json::object body;
  body["qkdn-rpc-qkd-registration:input"] = input;

  http::request<http::string_body> req;
  req.method(http::verb::post);
  req.target("/QKD_API/operations/qkdn-rpc-qkd-registration");
  req.version(11);
  req.set(http::field::host, host + ":" + port);
  req.set(http::field::content_type, "application/yang-data+json");
  req.set(http::field::accept, "application/yang-data+json");
  req.set(http::field::connection, "close");
  req.body() = json::serialize(body);
  req.prepare_payload();  // Content-Length 자동 설정

  ostringstream oss;
  oss << req;
  return oss.str();
}

// 동기 방식으로 연결 요청 전송
// buffer: 전송할 요청 데이터, sock: 연결된 소켓
// 반환: 성공 시 빈 error_code, 실패 시 에러 정보
boost::system::error_code send_request(const asio::const_buffer& buffer,
                                       tcp::socket& sock) {
  boost::system::error_code ec;
  asio::write(sock, buffer, ec);
  return ec;
}

bool check_registration(const registration_result& result,
                        const string& alias) {
  if (result.registration_response != "OK") {
    cout << "registration failed: " << result.registration_response << endl;
    return false;
  }
  if (result.qkd_alias != alias) {
    cout << "registration failed: " << result.qkd_alias << endl;
    return false;
  }
  return true;
}

// 응답 헤더 수신 및 상태 줄 검증
// sock: 현재 연결된 소켓
// result: json파싱 값 담음
boost::system::error_code read_response(tcp::socket& sock,
                                        registration_result& result) {
  boost::system::error_code ec;
  boost::beast::flat_buffer buf;

  http::response<http::string_body> res;
  http::read(sock, buf, res, ec);
  if (ec) {
    return ec;
  }
  if (res.result() != http::status::ok) {  // 200여부 검사
    cout << "Protocol Error: NOT 200 OK" << endl;
    ec = boost::system::errc::make_error_code(
        boost::system::errc::protocol_error);
    return ec;
  }

  // 성공시 json 파싱
  json::value jv = json::parse(res.body(), ec);
  if (ec) {
    return ec;
  }

  const json::value* alias =
      jv.find_pointer("/qkdn-rpc-qkd-registration:output/qkd_alias", ec);
  if (ec) {
    return ec;
  }
  const json::value* response = jv.find_pointer(
      "/qkdn-rpc-qkd-registration:output/registration_response", ec);
  if (ec) {
    return ec;
  }
  if (alias == NULL || response == NULL) {
    cout << "Protocol Error: no registration_response" << endl;
    ec = boost::system::errc::make_error_code(
        boost::system::errc::protocol_error);
    return ec;
  }
  result.qkd_alias = string(alias->as_string());
  result.registration_response = string(response->as_string());
  return ec;
}

std::string make_subscribe_request(const string& host, const string& port) {
  http::request<http::empty_body> req;
  req.method(http::verb::get);
  req.target("/QKD_API/data/kt-qkd-node:raw-key");
  req.version(11);
  req.set(http::field::host, host + ":" + port);
  req.set(http::field::accept, "text/event-stream");
  req.set(http::field::cache_control, "no-cache");
  req.set(http::field::connection, "keep-alive");

  ostringstream oss;
  oss << req;
  return oss.str();
}

// 구독 응답 헤더 수신 및 상태 검사
// sock: 연결된 소켓, buf: 수신 버퍼(헤더 이후 바이트 유지),
// parser: 응답 파서(계속 수신)
// 반환: 성공 시 빈 error_code, 실패 시 에러 정보
boost::system::error_code read_subscribe_header(
    tcp::socket& sock, boost::beast::flat_buffer& buf,
    http::response_parser<http::buffer_body>& parser) {
  boost::system::error_code ec;
  http::read_header(sock, buf, parser, ec);
  if (ec) {
    return ec;
  }
  if (parser.get().result() != http::status::ok) {
    cout << "subscribe failed: " << parser.get().result_int() << endl;
    ec = boost::system::errc::make_error_code(
        boost::system::errc::permission_denied);
    return ec;
  }
  return ec;
}

// QKD 등록 요청 전송 및 응답 수신
// host/port: 접속 대상
// 반환: 성공 시 빈 error_code, 실패 시 에러 정보
boost::system::error_code register_qkd(const string& host, const string& port) {
  asio::io_context io_context;
  tcp::resolver resolver(io_context);
  tcp::socket sock(io_context);
  boost::system::error_code ec;
  ec = kma::connect_socket(resolver, host, port, sock);
  if (ec) {
    return ec;
  }
  cout << "connected" << endl;

  string request = kma::make_registration_request(host, port, QKD_ALIAS);

  // 동기 방식으로 연결 요청을 등록
  asio::const_buffer req_buffer = asio::buffer(request);
  ec = kma::send_request(req_buffer, sock);
  if (ec) {
    return ec;
  }

  // HTTP 응답 수신
  registration_result result;
  ec = kma::read_response(sock, result);
  if (ec) {
    return ec;
  }

  // 응답 검증
  if (!check_registration(result, ALIAS)) {
    cout << "registration failed: value error" << endl;
    ec = boost::system::errc::make_error_code(boost::system::errc::bad_message);
    return ec;
  }

  // 소켓 종료
  sock.shutdown(tcp::socket::shutdown_both, ec);
  sock.close(ec);
  return boost::system::error_code();
}

// 원시키 구독 시작 (새 연결, 요청 전송, 응답 헤더 확인)
// resolver: 주소 변환기, host/port: 접속 대상, sock: 구독 연결(출력),
// buf/parser: 이후 본문 수신에 쓸 버퍼와 파서(출력)
// 반환: 성공 시 빈 error_code, 실패 시 에러 정보
boost::system::error_code subscribe_raw_key(
    tcp::resolver& resolver, const string& host, const string& port,
    tcp::socket& sock, boost::beast::flat_buffer& buf,
    http::response_parser<http::buffer_body>& parser) {
  boost::system::error_code ec = connect_socket(resolver, host, port, sock);
  if (ec) {
    return ec;
  }

  string request = make_subscribe_request(host, port);
  ec = send_request(asio::buffer(request), sock);
  if (ec) {
    return ec;
  }
  return read_subscribe_header(sock, buf, parser);
}

}  // namespace qkms::kma