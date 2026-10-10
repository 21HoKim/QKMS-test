#pragma once
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <string>

namespace qkms::kma {

struct registration_result {
  std::string qkd_alias;
  std::string registration_response;
};

boost::system::error_code connect_socket(
    boost::asio::ip::tcp::resolver& resolver, const std::string& host,
    const std::string& port, boost::asio::ip::tcp::socket& sock);

std::string make_registration_request(const std::string& host,
                                      const std::string& port,
                                      const std::string& qkd_alias);

boost::system::error_code send_request(const boost::asio::const_buffer& buffer,
                                       boost::asio::ip::tcp::socket& sock);

boost::system::error_code read_response(boost::asio::ip::tcp::socket& sock,
                                        registration_result& result);

bool check_registration(const registration_result& result,
                        const std::string& alias);

std::string make_subscribe_request(const std::string& host,
                                   const std::string& port);

boost::system::error_code read_subscribe_header(
    boost::asio::ip::tcp::socket& sock, boost::beast::flat_buffer& buf,
    boost::beast::http::response_parser<boost::beast::http::buffer_body>&
        parser);

boost::system::error_code register_qkd(const std::string& host,
                                       const std::string& port);

boost::system::error_code subscribe_raw_key(
    boost::asio::ip::tcp::resolver& resolver, const std::string& host,
    const std::string& port, boost::asio::ip::tcp::socket& sock,
    boost::beast::flat_buffer& buf,
    boost::beast::http::response_parser<boost::beast::http::buffer_body>&
        parser);
}  // namespace qkms::kma