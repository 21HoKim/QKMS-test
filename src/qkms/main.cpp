#include<array>
#include<iostream>
#include<boost/asio.hpp>
#include<string>


using boost::asio::ip::tcp;
using namespace std;

int main() {
	try{
		//connect
		const string host = "localhost";
		const string port = "18081";
		
		boost::asio::io_context io_context;
		tcp::resolver resolver(io_context);
		tcp::resolver::results_type endpoints = resolver.resolve(host, port);
		
		tcp::socket socket(io_context);
		boost::asio::connect(socket, endpoints);
		cout << "connected\n";

		//request
		string request;
		request += /*TODO: request line*/;
		request += /*TODO: Host header*/;
		request += "Accept: text/event-stream\r\n";
        request += "\r\n";

		//respons


	}
	catch(std::exception& e){
		cerr << "error : " << e.what() << endl;
		return -1;
	}
	return 0;
}

