#!/usr/bin/env python3
"""Standalone HTTPS telemetry listener run on the ptfhost."""
import argparse
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _read_fail_status(control_file):
    """Return an HTTP status to reject POSTs with, or None to accept normally."""
    try:
        with open(control_file) as f:
            content = f.read().strip()
    except OSError:
        return None
    if not content:
        return None
    try:
        return int(content)
    except ValueError:
        return 503


def _make_handler(events_file, control_file):
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""

            # Simulate a temporarily unavailable endpoint
            fail_status = _read_fail_status(control_file)
            if fail_status is not None:
                self.send_response(fail_status)
                self.end_headers()
                return

            try:
                payload = json.loads(body.decode("utf-8")) if body else []
                events = payload if isinstance(payload, list) else [payload]
                with open(events_file, "a") as f:
                    for event in events:
                        f.write(json.dumps(event) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                self.send_response(200)
            except Exception:
                self.send_response(400)
            self.end_headers()

        def log_message(self, fmt, *args):
            # Silence default stderr access logging.
            return

    return _Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--certfile", required=True)
    parser.add_argument("--keyfile", required=True)
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--control-file", required=True)
    parser.add_argument("--port-file", required=True)
    parser.add_argument("--pid-file", required=True)
    args = parser.parse_args()

    with open(args.pid_file, "w") as f:
        f.write(str(os.getpid()))

    # Ensure the events file exists so readers never race on a missing file.
    open(args.events_file, "a").close()

    httpd = ThreadingHTTPServer(
        ("0.0.0.0", args.port), _make_handler(args.events_file, args.control_file)
    )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=args.certfile, keyfile=args.keyfile)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    bound_port = httpd.socket.getsockname()[1]
    with open(args.port_file, "w") as f:
        f.write(str(bound_port))

    httpd.serve_forever()


if __name__ == "__main__":
    main()
