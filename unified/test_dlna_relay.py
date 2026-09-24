import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from unified import dlna_relay


PAYLOAD = (b"snap-room-range-test-" * 32768)[:512000]


class FlakyRangeHandler(BaseHTTPRequestHandler):
    requests = 0

    def log_message(self, *_):
        pass

    def do_GET(self):
        type(self).requests += 1
        start = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
        body = PAYLOAD[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Type", "audio/mp4")
        self.send_header("Content-Length", str(len(body)))
        if start:
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
        self.end_headers()
        if type(self).requests == 1:
            cutoff = len(body) // 3
            self.wfile.write(body[:cutoff])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.wfile.write(body)


class DlnaRelayTest(unittest.TestCase):
    def setUp(self):
        FlakyRangeHandler.requests = 0
        self.source = ThreadingHTTPServer(("127.0.0.1", 0), FlakyRangeHandler)
        self.source_thread = threading.Thread(target=self.source.serve_forever, daemon=True)
        self.source_thread.start()
        self.relay = ThreadingHTTPServer(("127.0.0.1", 0), dlna_relay.RelayHandler)
        self.relay_thread = threading.Thread(target=self.relay.serve_forever, daemon=True)
        self.relay_thread.start()

    def tearDown(self):
        self.relay.shutdown(); self.relay.server_close(); self.relay_thread.join(timeout=2)
        self.source.shutdown(); self.source.server_close(); self.source_thread.join(timeout=2)

    def test_mpd_add_and_addid_urls_are_rewritten(self):
        registry = dlna_relay.RelayRegistry()
        with patch.object(dlna_relay, "RELAY_HTTP_PORT", 1790):
            add = dlna_relay.rewrite_command(b'add "https://media.example/a.mp4?x=1"\n', registry)
            addid = dlna_relay.rewrite_command(b'addid "http://media.example/b.flac" 4\n', registry)
        self.assertRegex(add, rb'^add "http://127\.0\.0\.1:1790/stream/[0-9a-f]{32}"\n$')
        self.assertRegex(addid, rb'^addid "http://127\.0\.0\.1:1790/stream/[0-9a-f]{32}" 4\n$')
        self.assertEqual(dlna_relay.rewrite_command(b'add "file:///media/a.flac"\n', registry), b'add "file:///media/a.flac"\n')

    def test_interrupted_upstream_resumes_with_range(self):
        source_url = f"http://127.0.0.1:{self.source.server_port}/media.mp4"
        token = dlna_relay.REGISTRY.register(source_url).rsplit("/", 1)[1]
        relay_url = f"http://127.0.0.1:{self.relay.server_port}/stream/{token}"
        with patch.object(dlna_relay, "MAX_RETRIES", 3), patch.object(dlna_relay, "READ_TIMEOUT", 2), patch.object(dlna_relay, "validate_relay_target", side_effect=lambda url: url):
            self.assertEqual(urllib.request.urlopen(relay_url, timeout=5).read(), PAYLOAD)
        self.assertGreaterEqual(FlakyRangeHandler.requests, 2)

    def test_invalid_token_is_not_a_general_proxy(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"http://127.0.0.1:{self.relay.server_port}/stream/missing", timeout=2)
        error.exception.close()

    @staticmethod
    def resolved(address):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, 80))]

    def assert_target_rejected(self, address, message):
        with patch.object(dlna_relay.socket, "getaddrinfo", return_value=self.resolved(address)), self.assertRaisesRegex(dlna_relay.RelayTargetError, message):
            dlna_relay.validate_relay_target("http://media.example/audio")

    def test_reject_loopback_and_ipv6_loopback(self):
        self.assert_target_rejected("127.0.0.1", "loopback")
        self.assert_target_rejected("::1", "loopback")

    def test_reject_link_local_multicast_and_unspecified(self):
        self.assert_target_rejected("169.254.169.254", "link-local")
        self.assert_target_rejected("224.0.0.1", "multicast")
        self.assert_target_rejected("0.0.0.0", "unspecified")

    def test_allow_configured_lan_and_public_address(self):
        allowed = dlna_relay._networks("192.168.2.0/24")
        with patch.object(dlna_relay, "ALLOWED_LAN_NETWORKS", allowed), patch.object(dlna_relay.socket, "getaddrinfo", return_value=self.resolved("192.168.2.20")):
            self.assertEqual(dlna_relay.validate_relay_target("http://nas.lan/music"), "http://nas.lan/music")
        with patch.object(dlna_relay.socket, "getaddrinfo", return_value=self.resolved("8.8.8.8")):
            self.assertEqual(dlna_relay.validate_relay_target("https://radio.example/live"), "https://radio.example/live")

    def test_reject_unconfigured_private_network_and_gateway(self):
        self.assert_target_rejected("10.20.30.40", "outside the allowed LAN")
        with patch.object(dlna_relay, "ALLOWED_LAN_NETWORKS", dlna_relay._networks("192.168.2.0/24")), patch.object(dlna_relay, "GATEWAY_ADDRESSES", frozenset({dlna_relay.ipaddress.ip_address("192.168.2.126")})), patch.object(dlna_relay.socket, "getaddrinfo", return_value=self.resolved("192.168.2.126")), self.assertRaisesRegex(dlna_relay.RelayTargetError, "gateway"):
            dlna_relay.validate_relay_target("http://gateway.lan/admin")

    def test_redirect_target_is_revalidated(self):
        handler = dlna_relay.ValidatingRedirectHandler()
        request = urllib.request.Request("https://public.example/audio")
        with patch.object(dlna_relay, "validate_relay_target", side_effect=dlna_relay.RelayTargetError("loopback target is blocked")) as validate, self.assertRaises(dlna_relay.RelayTargetError):
            handler.redirect_request(request, Mock(), 302, "Found", {}, "http://127.0.0.1/private")
        validate.assert_called_once_with("http://127.0.0.1/private")


if __name__ == "__main__":
    unittest.main()
