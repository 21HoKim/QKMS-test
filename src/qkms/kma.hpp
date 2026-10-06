#pragma once
#include <array>
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/json.hpp>
#include <iostream>
#include <string>

namespace kma {
void print_error(boost::system::error_code ec);

boost::system::error_code connect_socket(
    boost::asio::ip::tcp::resolver& resolver, const std::string& host,
    const std::string& port, boost::asio::ip::tcp::socket& sock);

std::string make_registration_request(const std::string& host,
                                      const std::string& port);

boost::system::error_code send_request(boost::asio::const_buffer& buffer,
                                       boost::asio::ip::tcp::socket& sock);

boost::system::error_code read_response_head(boost::asio::ip::tcp::socket& sock,
                                             boost::asio::streambuf& buf,
                                             int& status_code);

int start_connect(const std::string host, const std::string port);
}  // namespace kma