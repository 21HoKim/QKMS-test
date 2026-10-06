#include "kma.hpp"

namespace asio = boost::asio;
// namespace http = beast::http;
namespace json = boost::json;
using asio::ip::tcp;
using namespace std;

namespace kma {

boost::system::error_code ec;

void print_error(boost::system::error_code ec) {
  cout << "error occurred!" << endl;
  cout << "value: " << ec.value() << endl;
  cout << "category: " << ec.category().name() << endl;
  cout << "message: " << ec.message() << endl;
  cout << ec.default_error_condition() << endl;
}

// host:port TCP 연결, 성공 시 sock 연결 상태
boost::system::error_code connect_socket(tcp::resolver& resolver,
                                         const string& host, const string& port,
                                         tcp::socket& sock) {
  tcp::resolver::results_type endpoints = resolver.resolve(host, port, ec);
  if (ec) {
    return ec;
  }

  asio::connect(sock, endpoints, ec);
  return ec;
}

// QKD 등록 요청(HTTP POST) 문자열 생성
string make_registration_request(const string& host, const string& port) {
  string request;
  string body = /*TODO*/{};
  request += "POST /QKD_API/operations/qkdn-rpc-qkd-registration HTTP/1.1\r\n";
  request += "Host: " + host + ":" + port + "\r\n";
  request += "Content-Type: application/yang-data+json\r\n";
  request += "Accept: application/yang-data+json\r\n";
  request += "Connection: close\r\n";
  request += "Content-Length: " + to_string(body.size());
  request += "\r\n";  // end Header
  request += body;
  return request;
}

// 동기 방식으로 연결 요청 전송
boost::system::error_code send_request(asio::const_buffer& buffer,
                                       tcp::socket& sock) {
  asio::write(sock, buffer, ec);
  return ec;
}

// 응답 헤더 수신 및 상태 줄 검증, 성공 시 헤더 이후 바이트 buf에 유지
boost::system::error_code read_response_head(tcp::socket& sock,
                                             asio::streambuf& buf,
                                             int& status_code) {
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

int start_connect(const string host, const string port) {
  asio::io_context io_context;
  tcp::resolver resolver(io_context);
  tcp::socket sock(io_context);

  ec = kma::connect_socket(resolver, host, port, sock);
  if (ec) {
    kma::print_error(ec);
    return -1;
  }
  cout << "connected" << endl;

  string request = kma::make_registration_request(host, port);

  // 동기 방식으로 연결 요청을 등록
  asio::const_buffer req_buffer = asio::buffer(request);
  ec = kma::send_request(req_buffer, sock);
  if (ec) {
    kma::print_error(ec);
    return -1;
  }

  // HTTP 응답 수신
  asio::streambuf res_buffer;
  int status;
  ec = kma::read_response_head(sock, res_buffer, status);
  if (ec) {
    kma::print_error(ec);
    return -1;
  }

  // 200 OK일 경우

  return 0;
}

}  // namespace kma