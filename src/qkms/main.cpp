#include <iostream>
#include <string>
#include <array>
#include <thread>
#include <boost/asio.hpp>
#define CMD_MAX 100000
using boost::asio::ip::tcp;
using namespace std;

namespace console {
class console {
 private:
  string command;

 public:
  void input() {
    for (int i = 0; i < CMD_MAX; i++) {
      cout << "input command : ";
      cin >> command;
      cout << endl;
      if (command == "status") {
        /*TODO: print status value*/
      } else if (command == "keys") {
        /*TODO: print the number of keys and status for each link*/
      } else if (command == "quit") {
        break;
      } else {
        cout << "unavailable command" << endl;
      }
    }
  }
  void print() {}
  console() {
    cout << "command list" << endl;
    cout << "status: print status value" << endl;
    cout << "keys: print the number of keys and status for each link" << endl;
  }
};
}  // namespace console

int main() {
  console::console c;
  thread csl(&console::console::input, &c);
  try {
    // connect
    const string host = "localhost";
    const string port = "18081";

    boost::asio::io_context io_context;
    tcp::resolver resolver(io_context);
    tcp::resolver::results_type endpoints = resolver.resolve(host, port);

    tcp::socket socket(io_context);
    boost::asio::connect(socket, endpoints);
    cout << "connected\n";

    // request
    string request;
    request += /*TODO: request line*/;
    request += /*TODO: Host header*/;
    request += "Accept: text/event-stream\r\n";
    request += "\r\n";

    // respons
  } catch (std::exception& e) {
    cerr << "error : " << e.what() << endl;
    goto error;
  }
error:
  csl.join();
  return -1;

  return 0;
}
