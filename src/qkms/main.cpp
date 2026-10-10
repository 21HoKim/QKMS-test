#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

#include "kma.hpp"
using namespace std;

namespace asio = boost::asio;
namespace http = boost::beast::http;
using asio::ip::tcp;

namespace qkms {

static string status;

// QKD_URL 미설정 시 접속 대상 (호스트에서 직접 실행, 목업 qkd-a1)
constexpr char DEFAULT_QKD_HOST[] = "localhost";
constexpr char DEFAULT_QKD_PORT[] = "18081";

// 환경변수 QKD_URL(예: http://qkd-a1:8080)에서 접속 대상 추출
// host/port: 접속 대상(출력), QKD_URL 미설정 시 기본값
void read_qkd_url(string& host, string& port) {
  const char* env = getenv("QKD_URL");
  host = DEFAULT_QKD_HOST;
  port = DEFAULT_QKD_PORT;
  if (env == nullptr) {
    return;
  }

  string url = env;
  const string scheme = "http://";
  if (url.compare(0, scheme.size(), scheme) == 0) {
    url = url.substr(scheme.size());
  }
  if (!url.empty() && url.back() == '/') {
    url.pop_back();
  }

  size_t colon = url.find(':');
  if (colon == string::npos) {
    host = url;
    port = "80";
    return;
  }
  host = url.substr(0, colon);
  port = url.substr(colon + 1);
}

void print_error(const boost::system::error_code& ec) {
  cout << "error occurred!" << endl;
  cout << "value: " << ec.value() << endl;
  cout << "category: " << ec.category().name() << endl;
  cout << "message: " << ec.message() << endl;
  cout << ec.default_error_condition() << endl;
}

constexpr int MAX_COMMAND_COUNT = 100000;
// 사용 가능한 콘솔 명령 목록 출력
void print_command_list() {
  cout << "command list" << endl;
  cout << "status: print status value" << endl;
  cout << "keys: print the number of keys and status for each link" << endl;
}

// 콘솔 명령 입력 및 처리
void run_console() {
  string command;

  for (int i = 0; i < MAX_COMMAND_COUNT; i++) {
    cout << "input command: ";
    cin >> command;
    cout << endl;

    if (command == "quit") {
      return;
    }
    if (command == "status") {
      /*TODO: print status value*/
    } else if (command == "keys") {
      /*TODO: print the number of keys and status for each link*/
    } else {
      cout << "unavailable command" << endl;
    }
  }
}
}  // namespace qkms

int main() {
  string host;
  string port;
  qkms::read_qkd_url(host, port);
  cout << "qkd: " << host << ":" << port << endl;

  qkms::print_command_list();
  thread console_thread(qkms::run_console);
  boost::system::error_code ec = qkms::kma::register_qkd(host, port);
  if (ec) {
    qkms::print_error(ec);
    console_thread.join();
    return -1;
  }
  cout << "registered" << endl;

  asio::io_context io_context;
  tcp::resolver resolver(io_context);
  tcp::socket sub_sock(io_context);
  boost::beast::flat_buffer buf;
  http::response_parser<http::buffer_body> parser;

  ec =
      qkms::kma::subscribe_raw_key(resolver, host, port, sub_sock, buf, parser);
  if (ec) {
    qkms::print_error(ec);
    console_thread.join();
    return -1;
  }
  cout << "subscribed" << endl;
  console_thread.join();
  return 0;
}