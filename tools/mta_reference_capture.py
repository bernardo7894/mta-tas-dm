"""Control the local TAS reference-capture workflow through MTA's HTTP API.

The MTA server must have the patched ``tas`` resource running.  Set
MTA_HTTP_USER and MTA_HTTP_PASSWORD to an authenticated MTA HTTP account, or
pass --user/--password explicitly.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _auth_header(user: str, password: str) -> str:
    token = f"{user}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("ascii")


def call_api(host: str, port: int, user: str, password: str, function: str, args: list[object]):
    url = f"http://{host}:{port}/tas/call/{function}"
    request = Request(
        url,
        data=json.dumps(args).encode("utf-8"),
        headers={
            "Authorization": _auth_header(user, password),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"MTA HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"could not connect to MTA HTTP server: {error.reason}") from error

    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"MTA returned non-JSON data: {body[:500]}") from error


def result_value(reply):
    """MTA HTTP exports wrap their return values in a JSON array."""
    if isinstance(reply, list) and len(reply) == 1:
        return reply[0]
    return reply


def require_success(reply):
    value = result_value(reply)
    if isinstance(value, dict) and value.get("ok") is False:
        raise RuntimeError(str(value.get("error", "unknown server error")))
    return value


def print_json(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("MTA_HTTP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MTA_HTTP_PORT", "22005")))
    parser.add_argument("--user", default=os.getenv("MTA_HTTP_USER"))
    parser.add_argument("--password", default=os.getenv("MTA_HTTP_PASSWORD"))

    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="change map, load a TAS file, and capture playback telemetry")
    start.add_argument("map_name")
    start.add_argument("record_name")
    start.add_argument("output_name")
    start.add_argument("--target-player")

    run = subparsers.add_parser("run", help="start a capture and wait for it to finish")
    run.add_argument("map_name")
    run.add_argument("record_name")
    run.add_argument("output_name")
    run.add_argument("--target-player")
    run.add_argument("--timeout", type=float, default=900.0)
    run.add_argument("--interval", type=float, default=1.0)

    subparsers.add_parser("status", help="print the current capture status")

    args = parser.parse_args()
    if not args.user or args.password is None:
        parser.error("set MTA_HTTP_USER and MTA_HTTP_PASSWORD, or pass --user and --password")

    try:
        if args.command == "status":
            reply = call_api(args.host, args.port, args.user, args.password, "getReferenceCaptureStatus", [])
            status = require_success(reply)
            print_json(status)
            return 0

        request_args = [args.map_name, args.record_name, args.output_name, args.target_player]
        reply = call_api(args.host, args.port, args.user, args.password, "startReferenceCapture", request_args)
        accepted = require_success(reply)
        print_json(accepted)

        if args.command == "start":
            return 0

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            time.sleep(args.interval)
            status_reply = call_api(
                args.host,
                args.port,
                args.user,
                args.password,
                "getReferenceCaptureStatus",
                [],
            )
            status = require_success(status_reply)
            print_json(status)
            if isinstance(status, dict) and status.get("state") in TERMINAL_STATES:
                return 0 if status["state"] == "completed" else 1

        print(f"capture did not finish within {args.timeout:g} seconds", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
