#include <iostream>
#include <string>
#include <thread>
#include "kma.hpp"
using namespace std;

namespace qkms {
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
}  // qkms namespace

int main() {
  const string host = "localhost";
  const string port = "18081";

  qkms::print_command_list();
  thread console_thread(qkms::run_console);

  if(kma::start_connect(host, port)){
    console_thread.join();
    return -1;
  }

  

  console_thread.join();
  return 0;
}