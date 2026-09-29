#include <array>
#include <boost/asio.hpp>
#include <iostream>
#include <string>
#include <thread>

namespace asio = boost::asio;
using asio::ip::tcp;
using namespace std;

namespace qkms {

constexpr int MAX_COMMAND_COUNT = 100000;

// 사용 가능한 콘솔 명령 목록을 출력한다.
void print_command_list() {
  cout << "command list" << endl;
  cout << "status: print status value" << endl;
  cout << "keys: print the number of keys and status for each link" << endl;
}

// 콘솔 명령을 읽어 처리한다. "quit" 입력 시 반환한다.
void run_console() {
  string command;

  for (int i = 0; i < MAX_COMMAND_COUNT; i++) {
    cout << "input command : ";
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

// host:port 로 TCP 연결한다. 성공하면 sock 이 연결된 상태가 된다.
boost::system::error_code connect_to(tcp::resolver& resolver,
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

// 원시키 구독 요청(HTTP GET) 문자열을 만든다. (TTAK.KO-01.0225 7.9.5)
string make_subscribe_request(const string& host, const string& port) {
  string request;

  request += /*TODO: request line*/;
  request += /*TODO: Host header*/;
  request += "Accept: text/event-stream\r\n";
  request += "\r\n";
  return request;
}

}  // namespace qkms

int main() {
  const string host = "localhost";
  const string port = "18081";

  qkms::print_command_list();
  thread console_thread(qkms::run_console);

  asio::io_context io_context;
  tcp::resolver resolver(io_context);
  tcp::socket sock(io_context);

  boost::system::error_code ec = qkms::connect_to(resolver, host, port, sock);
  if (ec) {
    cerr << "connect: " << ec.message() << endl;
    console_thread.join();
    return 1;
  }
  cout << "connected" << endl;

  string request = qkms::make_subscribe_request(host, port);
  /*TODO: send request*/

  /*TODO: read response*/

  console_thread.join();
  return 0;
}