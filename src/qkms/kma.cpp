#include "kma.hpp"

namespace asio = boost::asio;
// namespace http = beast::http;
namespace json = boost::json;
using asio::ip::tcp;
using namespace std;

namespace kma {

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
string make_registration_request(const string& host, const string& port) {
  string request;
  string body = /*TODO*/ {};
  request += "POST /QKD_API/operations/qkdn-rpc-qkd-registration HTTP/1.1\r\n";
  request += "Host: " + host + ":" + port + "\r\n";
  request += "Content-Type: application/yang-data+json\r\n";
  request += "Accept: application/yang-data+json\r\n";
  request += "Connection: close\r\n";
  request += "Content-Length: " + to_string(body.size()) + "\r\n";
  request += "\r\n";  // 헤더 종료
  request += body;
  return request;
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

// 응답 헤더 수신 및 상태 줄 검증
// sock: 연결된 소켓, buf: 수신 버퍼(성공 시 헤더 이후 바이트 유지),
// status_code: HTTP 상태 코드(출력)
// 반환: 성공 시 빈 error_code, 실패 시 에러 정보
boost::system::error_code read_response_head(tcp::socket& sock,
                                             asio::streambuf& buf,
                                             int& status_code) {
  boost::system::error_code ec;
  asio::read_until(sock, buf, "\r\n\r\n", ec);
  if (ec) {
    return ec;
  }
  istream res_buf(&buf);
  string version;
  string line;

  res_buf >> version >> status_code;
  /*TODO: is.fail() 검사, 실패 시 에러 반환*/

  getline(res_buf, line);
  while (getline(res_buf, line) && line != "\r") {
    /*TODO: 이름, 값 분리, 필요 헤더 저장*/
  }
  /*TODO: status_code!=200이면 에러 반환*/
  return ec;
}

// QKD 등록 요청 전송 및 응답 수신
// host/port: 접속 대상
// 반환: 성공 시 빈 error_code, 실패 시 에러 정보
boost::system::error_code start_connect(const string& host,
                                        const string& port) {
  asio::io_context io_context;
  tcp::resolver resolver(io_context);
  tcp::socket sock(io_context);
  boost::system::error_code ec;
  ec = kma::connect_socket(resolver, host, port, sock);
  if (ec) {
    return ec;
  }
  cout << "connected" << endl;

  string request = kma::make_registration_request(host, port);

  // 동기 방식으로 연결 요청을 등록
  asio::const_buffer req_buffer = asio::buffer(request);
  ec = kma::send_request(req_buffer, sock);
  if (ec) {
    return ec;
  }

  // HTTP 응답 수신
  asio::streambuf res_buffer;
  int status;
  ec = kma::read_response_head(sock, res_buffer, status);
  if (ec) {
    return ec;
  }

  // 200 OK일 경우

  return ec;
}

}  // namespace kma