"""C2 to C8, C39 and C41: Subscriptions from sign-in to sign-out (DRV-1), and the helpers that judge them:
`check_subscription_rejection`, `check_subscription_credentials` and `check_subscription_environments`.

The TypeScript `checkSubscriptionRemoval` is not ported: only the Codex Driver's own test wrappers used it.
"""

from __future__ import annotations

from ..js import (
    UNDEFINED,
    JSArray,
    JSObject,
    get,
    is_number,
    join,
    loose_includes,
    parse,
    stringify,
    text_of,
    trim,
    well_formed,
)
from .support import (
    at,
    delay,
    exists,
    find,
    includes,
    item,
    mkdir,
    now_monotonic,
    now_ms,
    null_check,
    read_file,
    read_json,
    readdir,
    record,
    test,
    write_file,
)


import asyncio
import errno
import ipaddress
import os
import re
import socket
import socketserver
import threading
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from typing import Any

from ..check import ScenarioError, check, equal, object_, text
from ..harness import Scenario, ScenarioHome, fs_error
from ..js import (
    UNDEFINED,
    JSArray,
    JSObject,
    get,
    join,
    loose_includes,
    parse,
    stringify,
    text_of,
    trim,
    well_formed,
)
from .runs import stream
from .support import (
    at,
    find,
    includes,
    item,
    mkdir,
    now_ms,
    null_check,
    read_file,
    readdir,
    record,
    write_file,
)

KEY = "fixture-key-SECRET-781"

# --- JavaScript ------------------------------------------------------------------------------------------


def prop(value: Any, *keys: str | int) -> Any:
    """`value.a.b` in JavaScript: V8's TypeError on null or undefined, undefined for a field a value lacks."""
    for key in keys:
        if value is None or value is UNDEFINED:
            raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading '{key}')")
        value = get(value, key)
    return value


def array(value: Any, method: str, site: str) -> list[Any]:
    """The receiver of `site.method(...)`: V8's TypeError when it is not an array."""
    if value is None or value is UNDEFINED:
        raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading '{method}')")
    if not isinstance(value, list):
        raise ScenarioError(f"{site}.{method} is not a function")
    return value


def joined(values: Iterable[Any]) -> str:
    """Array.prototype.join(''): null and undefined print as nothing."""
    return "".join("" if value is None or value is UNDEFINED else text_of(value) for value in values)


def nullish(value: Any) -> bool:
    return value is None or value is UNDEFINED


def set_size(values: Iterable[Any]) -> int:
    """new Set(values).size: SameValueZero for primitives, identity for objects and arrays."""
    seen: list[Any] = []
    for value in values:
        if not loose_includes(seen, value):
            seen.append(value)
    return len(seen)


def iso(milliseconds: float) -> str:
    """new Date(milliseconds).toISOString()."""
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def listing(path: str) -> JSArray:
    """fs.readdir: libuv returns the names sorted by their bytes."""
    return JSArray(sorted(readdir(path), key=os.fsencode))


def files(directory: str) -> list[str]:
    """Every regular file below the folder, depth first in readdir's order; links are not followed."""
    null_check(directory)
    try:
        with os.scandir(directory) as entries:
            found = sorted(entries, key=lambda entry: os.fsencode(entry.name))
    except OSError as error:
        raise fs_error(error, "scandir", directory) from None
    result: list[str] = []
    for entry in found:
        path = join(directory, entry.name)
        if entry.is_dir(follow_symlinks=False):
            result.extend(files(path))
        elif entry.is_file(follow_symlinks=False):
            result.append(path)
    return result


# --- new URL(value).hostname, by the WHATWG URL standard -------------------------------------------------

SPECIAL = ("ftp", "file", "http", "https", "ws", "wss")
FORBIDDEN_HOST = set("\x00\t\n\r #/:<>?@[\\]^|")
FORBIDDEN_DOMAIN = FORBIDDEN_HOST | {chr(code) for code in range(0x20)} | {"%", "\x7f"}


def leading(pattern: str, value: str) -> str:
    match = re.match(pattern, value)
    return match.group(0) if match is not None else ""


def invalid_url() -> ScenarioError:
    return ScenarioError("Invalid URL")


def hostname(value: str) -> str:
    value = well_formed(value)  # a USVString: a lone surrogate reads as U+FFFD
    value = re.sub(r"^[\x00-\x20]+|[\x00-\x20]+\Z", "", value)
    value = re.sub(r"[\t\n\r]", "", value)
    match = re.match(r"([A-Za-z][A-Za-z0-9+.\-]*):", value)
    if match is None:
        raise invalid_url()
    scheme, rest = match.group(1).lower(), value[match.end():]
    special = scheme in SPECIAL
    if scheme == "file":
        if len(rest) < 2 or rest[0] not in "/\\" or rest[1] not in "/\\":
            return ""
        host = leading(r"[^/\\?#]*", rest[2:])
        if host == "" or re.fullmatch(r"[A-Za-z][:|]", host):
            return ""
        host = parse_host(host, True)
        return "" if host == "localhost" else host
    if special:
        authority = leading(r"[^/\\?#]*", rest.lstrip("/\\"))
    elif rest.startswith("//"):
        authority = leading(r"[^/?#]*", rest[2:])
    else:
        return ""
    at_sign = "@" in authority
    host_port = authority.rpartition("@")[2]
    if at_sign and host_port == "":
        raise invalid_url()
    host, port, inside = host_port, "", False
    for index, character in enumerate(host_port):
        if character == "[":
            inside = True
        elif character == "]":
            inside = False
        elif character == ":" and not inside:
            host, port = host_port[:index], host_port[index + 1:]
            if host == "":
                raise invalid_url()
            break
    if special and host == "":
        raise invalid_url()
    if port and (not re.fullmatch(r"[0-9]+", port) or int(port) > 65535):
        raise invalid_url()
    return parse_host(host, special)


def parse_host(value: str, special: bool) -> str:
    if value.startswith("["):
        if not value.endswith("]"):
            raise invalid_url()
        return "[" + ipv6(value[1:-1]) + "]"
    if not special:
        if any(character in FORBIDDEN_HOST for character in value):
            raise invalid_url()
        return "".join(character if 0x20 <= ord(character) <= 0x7E else
                       "".join(f"%{byte:02X}" for byte in character.encode("utf-8", "surrogatepass"))
                       for character in value)
    decoded = re.sub(rb"%([0-9A-Fa-f]{2})", lambda found: bytes([int(found.group(1), 16)]),
                     well_formed(value).encode("utf-8")).decode("utf-8", "replace")
    domain = domain_to_ascii(decoded)
    if domain == "" or any(character in FORBIDDEN_DOMAIN for character in domain):
        raise invalid_url()
    return ipv4(domain) if ends_in_number(domain) else domain


def domain_to_ascii(domain: str) -> str:
    """UTS 46 ToASCII as Node's URL parser (Ada) applies it: nontransitional, joiners and bidirectional text
    checked per label, an `xn--` label checked only when the domain is not all ASCII."""
    if domain.isascii():
        return domain.lower()
    parts = []
    for character in domain:
        mapping = idna_mapping(character)
        if mapping is None:
            raise invalid_url()
        parts.append(mapping)
    labels = unicodedata.normalize("NFC", "".join(parts)).split(".")
    for label in labels:
        if label.startswith("xn--"):
            try:
                decoded = label[4:].encode("ascii").decode("punycode")
            except (UnicodeError, ValueError, OverflowError):
                raise invalid_url() from None
            if decoded.isascii() or unicodedata.normalize("NFC", decoded) != decoded or not valid_label(decoded):
                raise invalid_url()
        elif not label.isascii() and not valid_label(label):
            raise invalid_url()
    return ".".join(label if label.isascii() else "xn--" + label.encode("punycode").decode("ascii") for label in labels)


def code_points(table: str) -> frozenset[str]:
    """The characters of a list of hexadecimal code points and ranges, such as `61d 870-88e`."""
    result: set[str] = set()
    for entry in table.split():
        first, _, last = entry.partition("-")
        result.update(chr(code) for code in range(int(first, 16), int(last or first, 16) + 1))
    return frozenset(result)


DEVIATIONS = frozenset("\u00df\u03c2\u200c\u200d")
IGNORED = code_points("ad 34f 115f-1160 17b4-17b5 180b-180f 200b 2060-2064 206a-206f 3164 fe00-fe0f feff ffa0 1bca0-1bca3 "
                      "1d173-1d17a e0100-e01ef")
DISALLOWED = code_points("2ff0-2fff 31ef fe12 fffc-fffd")
SEPARATORS = frozenset("\u3002\uff0e\uff61")
# Ada's own tables, which differ from Python's Unicode 16 data: the joining types of the letters it knows, the
# combining marks it does not know (so they may begin a label), and the characters whose bidirectional class
# it reads as left-to-right or as a nonspacing mark.
JOINING = {character: entry[-1] for entry in (
    "620D 622-625R 626D 627R 628D 629R 62a-62eD 62f-632R 633-63fD 641-647D 648R 649-64aD 66e-66fD 671-673R 679-687D "
    "688-699R 69a-6bfD 6c0R 6c1-6c2D 6c3-6cbR 6ccD 6cdR 6ceD 6cfR 6d0-6d1D 6d2-6d3R 6d5R 6ee-6efR 6fa-6fcD 6ffD 710R "
    "712-714D 715-719R 71a-71dD 71eR 71f-727D 728R 729D 72aR 72bD 72cR 72d-72eD 72fR 74dR 74e-758D 759-75bR 75c-766D "
    "850-853D 854R 855D 8a0D 8a2-8a9D 8aa-8acR 1820-1877D 1887-18a8D 18aaD a840-a871D a872L").split()
    for character in code_points(entry[:-1])}
UNKNOWN_MARKS = code_points(
    "897-89f 8ca-8d2 c3c cf3 ece 1715 1ac1-1ace 1dfa 10d69-10d6d 10efc-10eff 10f82-10f85 11070 11073-11074 110c2 11241 "
    "113b8-113c0 113c2 113c5 113c7-113ca 113cc-113d0 113d2 113e1-113e2 11f00-11f01 11f03 11f34-11f3a 11f3e-11f42 11f5a "
    "13440 13447-13455 1611e-1612f 1cf00-1cf2d 1cf30-1cf46 1e08f 1e2ae 1e4ec-1e4ef 1e5ee-1e5ef")
LEFT_TO_RIGHT = UNKNOWN_MARKS | code_points(
    "61d 870-88e 8b5 8c8-8c9 20c0 2427-2429 2e53-2e5d 31e4-31e5 fbc2 fd40-fd4f fdcf fdfe-fdff 10d40-10d65 10d6e-10d85 "
    "10d8e-10d8f 10ec2-10ec4 10f70-10f81 10f86-10f89 1cc00-1ccd5 1cd00-1ceb3 1d1e9-1d1ea 1f6dc-1f6df 1f774-1f776 "
    "1f77b-1f77f 1f7d9 1f7f0 1f8b2-1f8bb 1f8c0-1f8c1 1f979 1f9cc 1fa75-1fa77 1fa7b-1fa7c 1fa87-1fa89 1fa8f 1faa9-1faaf "
    "1fab7-1fabf 1fac3-1fac6 1face-1facf 1fad7-1fadc 1fadf-1fae9 1faf0-1faf8 1fbcb-1fbef")
NONSPACING = code_points("1734 1171e")
LTR_LABEL = frozenset(("L", "EN", "ES", "CS", "ET", "ON", "BN", "NSM"))
RTL_LABEL = frozenset(("R", "AL", "AN", "EN", "ES", "CS", "ET", "ON", "BN", "NSM"))


def idna_mapping(character: str) -> str | None:
    """The UTS 46 mapping of one character (NFKC_Casefold, deviations kept), or None when it is disallowed."""
    if character.isascii() or character in DEVIATIONS:
        return character.lower()
    if character in IGNORED:
        return ""
    if character in SEPARATORS:
        return "."
    if character == "\u1e9e":
        return "\u00df"
    if character in DISALLOWED or unicodedata.category(character) in ("Cn", "Co", "Cs", "Cc", "Cf", "Zs", "Zl", "Zp"):
        return None
    mapped = character
    while True:
        folded = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", mapped).casefold())
        if folded == mapped:
            break
        mapped = folded
    return None if "." in mapped or "\u3002" in mapped else mapped


def bidi_class(character: str) -> str:
    if character in NONSPACING:
        return "NSM"
    return "L" if character in LEFT_TO_RIGHT else unicodedata.bidirectional(character)


def valid_label(label: str) -> bool:
    """UTS 46 label validity as Ada checks it; a label whose first joiner is allowed is not checked further."""
    if unicodedata.category(label[0]).startswith("M") and label[0] not in UNKNOWN_MARKS:
        return False
    if any(idna_mapping(character) != character for character in label):
        return False
    for index, character in enumerate(label):
        if character in "\u200c\u200d":
            if index > 0 and unicodedata.combining(label[index - 1]) == 9:
                return True
            if character == "\u200d" or index == 0 or index + 1 >= len(label):
                return False
            return (any(JOINING.get(before) in ("L", "D") for before in label[:index])
                    and any(JOINING.get(after) in ("R", "D") for after in label[index + 1:]))
    classes = [bidi_class(character) for character in label]
    strong = [kind for kind in classes if kind != "NSM"]
    if not strong:
        return False
    if not any(kind in ("R", "AL", "AN") for kind in classes):
        return True
    if classes[0] == "L":
        return set(classes) <= LTR_LABEL and strong[-1] in ("L", "EN")
    if classes[0] in ("R", "AL"):
        return (set(classes) <= RTL_LABEL and strong[-1] in ("R", "AL", "EN", "AN")
                and not ("EN" in classes and "AN" in classes))
    return False


def ipv4_number(part: str) -> int | None:
    radix, digits = 10, "0123456789"
    if part == "":
        return None
    if part[:2] in ("0x", "0X"):
        part, radix, digits = part[2:], 16, "0123456789abcdefABCDEF"
    elif len(part) > 1 and part[0] == "0":
        part, radix, digits = part[1:], 8, "01234567"
    if part == "":
        return 0
    if any(character not in digits for character in part):
        return None
    return int(part, radix)


def ends_in_number(domain: str) -> bool:
    parts = domain.split(".")
    if parts[-1] == "":
        if len(parts) == 1:
            return False
        parts.pop()
    last = parts[-1]
    return (last != "" and all(character in "0123456789" for character in last)) or ipv4_number(last) is not None


def ipv4(domain: str) -> str:
    parts = domain.split(".")
    if parts[-1] == "" and len(parts) > 1:
        parts.pop()
    if len(parts) > 4:
        raise invalid_url()
    numbers: list[int] = []
    for part in parts:
        number = ipv4_number(part)
        if number is None:
            raise invalid_url()
        numbers.append(number)
    if any(number > 255 for number in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(numbers)):
        raise invalid_url()
    address = numbers[-1] + sum(number * 256 ** (3 - index) for index, number in enumerate(numbers[:-1]))
    return ".".join(str((address >> shift) & 255) for shift in (24, 16, 8, 0))


def ipv6(value: str) -> str:
    if "%" in value:
        raise invalid_url()
    try:
        number = int(ipaddress.IPv6Address(value))
    except ValueError:
        raise invalid_url() from None
    pieces = [(number >> (112 - 16 * index)) & 0xFFFF for index in range(8)]
    start, length, index = -1, 1, 0
    while index < 8:
        end = index
        while end < 8 and pieces[end] == 0:
            end += 1
        if end - index > length:
            start, length = index, end - index
        index = max(end, index + 1)
    words = [f"{piece:x}" for piece in pieces]
    if start < 0:
        return ":".join(words)
    return ":".join(words[:start]) + "::" + ":".join(words[start + length:])


# --- The Driver's Subscriptions ---------------------------------------------------------------------------


async def subscription(home: ScenarioHome, identifier: str) -> JSObject:
    reply = await home.call(["subscriptions", "list"])
    equal("List exit", reply["status"], 0)
    listed = array(parse(reply["stdout"]), "find", "JSON.parse(...)")
    return object_("Subscription", find(listed, lambda value: prop(value, "id") == identifier))


async def families(home: ScenarioHome) -> JSArray:
    reply = await home.call(["subscriptions", "families"])
    equal("Families exit", reply["status"], 0)
    return JSArray(object_("Family", value) for value in array(parse(reply["stdout"]), "map", "JSON.parse(...)"))


async def state(home: ScenarioHome) -> str:
    info = await home.json(["info"])
    equal("Info exit", info.process["status"], 0)
    return text("State path", info.result["stateDirectory"])


async def vendor_family(home: ScenarioHome) -> str:
    return text("Vendor family", get(find(await families(home), lambda family: family["auth"] == "vendor_login"), "id"))


@dataclass
class SignIn:
    done: JSObject
    result: JSObject
    lines: JSArray


async def sign_in(home: ScenarioHome, identifier: str, by_code: bool = False) -> SignIn:
    interaction = home.start(["subscriptions", "sign-in", identifier, *(["--by-code"] if by_code else [])])
    try:
        if by_code:
            family = (await subscription(home, identifier))["family"]
            if family == "chatgpt":
                step = await interaction.step("open_url")
                text("Device user code", step["userCode"])
            else:
                await interaction.step("enter_code")
                interaction.send({"input": "fixture-code"})
        done = await interaction.step("done")
        result = await interaction.done
        equal("Sign-in exit", result["status"], 0)
        equal("Signed in", object_("Done Subscription", done["subscription"])["state"], "signed_in")
        return SignIn(done, result, interaction.lines)
    finally:
        await interaction.dispose()


def has_step(lines: JSArray, name: str) -> bool:
    """lines.some(value => object('Step', value).step === name)."""
    return any(object_("Step", value)["step"] == name for value in lines)


# --- A loopback stand-in for the Z.AI API ----------------------------------------------------------------


class Gateway:
    """The vendor's API on 127.0.0.1, answered on a thread of its own; `mode` is 'ok', 'rejected' or 'unavailable'."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.paths = JSArray()
        self.settings: JSObject = JSObject()
        self.server = _Server(self)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def answer(self, target: str, authorization: str | None) -> tuple[int, bytes, bool]:
        """The status, body and whether the body is labelled as JSON."""
        self.paths.append(target)
        if authorization != f"Bearer {KEY}":
            return 401, b"{}", False
        if self.mode == "rejected":
            return 403, b"{}", True
        if self.mode == "unavailable":
            return 503, text_of(stringify({"message": f"Temporary outage {KEY}"})).encode("utf-8"), True
        if target == "/api/paas/v4/models":
            body: JSObject = record(data=[record(id="fixture-gateway-model", label="Fixture gateway")])
        else:
            body = record(success=True, data=record(planName="Fixture plan", limits=[
                record(type="TOKENS_LIMIT", unit=3, number=5, percentage=99, usage=100, remaining=75,
                       nextResetTime=now_ms() + 60000),
                record(type="CREDIT_LIMIT", unit=6, number=1, percentage=40),
                record(type="TIME_LIMIT", percentage=7),
            ]))
        return 200, text_of(stringify(body)).encode("utf-8"), True

    async def dispose(self) -> None:
        """server.closeAllConnections(), then server.close()."""
        with self.server.lock:
            connections = list(self.server.connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 511  # Node's listen backlog

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway
        self.connections: set[socket.socket] = set()
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _Handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # a broken connection is dropped quietly, as Node's server does


# The methods Node's HTTP parser accepts. It answers any other with 400 and closes the connection, as it does for an
# HTTP/1.1 request without Host, and it closes a CONNECT request, which no listener takes here, without an answer.
METHODS = frozenset("ACL BIND CHECKOUT COPY DELETE GET HEAD LINK LOCK M-SEARCH MERGE MKACTIVITY MKCALENDAR MKCOL MOVE "
                    "NOTIFY OPTIONS PATCH POST PROPFIND PROPPATCH PURGE PUT QUERY REBIND REPORT SEARCH SOURCE SUBSCRIBE "
                    "TRACE UNBIND UNLINK UNLOCK UNSUBSCRIBE".split())


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 5  # Node's keep-alive timeout
    server: _Server

    def setup(self) -> None:
        super().setup()
        with self.server.lock:
            self.server.connections.add(self.connection)

    def finish(self) -> None:
        with self.server.lock:
            self.server.connections.discard(self.connection)
        try:
            super().finish()
        except OSError:
            pass

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Callable[[], None]:
        if name.startswith("do_"):  # every method is answered alike
            return self.respond
        raise AttributeError(name)

    def respond(self) -> None:
        if self.command == "CONNECT":
            self.close_connection = True
            return
        if self.command not in METHODS or (self.request_version == "HTTP/1.1" and self.headers.get("Host") is None):
            self.close_connection = True
            self.wfile.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            return
        words = self.requestline.split()
        target = words[1] if len(words) > 1 else self.path
        length = self.headers.get("Content-Length")
        if length is not None and length.strip().isdigit():
            self.rfile.read(int(length.strip()))  # the body is never read; Node discards it
        elif self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
        authorization = self.headers.get("Authorization")
        status, body, json_type = self.server.gateway.answer(
            target, authorization.strip(" \t") if authorization is not None else None)
        self.send_response_only(status)
        if json_type:
            self.send_header("Content-Type", "application/json")
        self.send_header("Date", self.date_time_string())
        self.send_header("Connection", "close" if self.close_connection else "keep-alive")
        if not self.close_connection:
            self.send_header("Keep-Alive", "timeout=5")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


async def gateway_fixture(home: ScenarioHome) -> Gateway:
    gateway = Gateway()
    host, port = gateway.server.server_address[:2]
    address = record(address=host, family="IPv4", port=port)
    check("Listener address", isinstance(address, dict), "a TCP listener", address)
    source = join(home.home, "secret-source")
    write_file(source, f"#!/bin/sh\nprintf '%s\\n' '{KEY}'\n", 0o700)
    gateway.settings = JSObject(subscriptions=JSObject(zai=JSObject(
        secret=JSObject({"from": "command", "command": JSArray([source])}),
        settings=JSObject(baseUrl=f"http://127.0.0.1:{port}/gateway", modelMap=JSObject(haiku="fixture-fallback")))))
    await home.settings(gateway.settings)
    return gateway


# --- The Keychain and the process table ------------------------------------------------------------------


async def keychain(args: list[str], instruction: str | None = None) -> JSObject:
    """/usr/bin/security with only PATH set; the instruction is written to its input, which is then closed."""
    try:
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/security", *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env={"PATH": "/usr/bin:/bin"})
    except OSError as error:
        raise ScenarioError(f"spawn /usr/bin/security {errno.errorcode.get(error.errno or 0, 'UNKNOWN')}") from None
    stdout, _ = await process.communicate(None if instruction is None else well_formed(instruction).encode("utf-8"))
    status = process.returncode
    return record(status=status if status is not None and status >= 0 else None,
                  stdout=stdout.decode("utf-8", "replace"))


def security_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def store(service: str, identifier: str, value: str) -> None:
    result = await keychain(["-i"], f"add-generic-password -U -s {security_quote(service)} -a "
                                    f"{security_quote(identifier)} -w {security_quote(value)}\n")
    equal("Synthetic Keychain write", result["status"], 0)


async def running(pid: Any) -> bool:
    """`ps -p <pid> -o stat=` succeeds and names no zombie; any failure counts as not running."""
    try:
        process = await asyncio.create_subprocess_exec(
            "/bin/ps", "-p", text_of(pid), "-o", "stat=", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await process.communicate()
    except Exception:
        return False
    return process.returncode == 0 and not trim(stdout.decode("utf-8", "replace")).startswith("Z")


# --- C2 --------------------------------------------------------------------------------------------------


async def run_c2(home: ScenarioHome) -> None:
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    vendor = find(await families(home), lambda value: value["auth"] == "vendor_login")
    check("Vendor login family", vendor is not UNDEFINED, "a vendor-login family", vendor)
    identifier = text("Family identifier", vendor["id"])
    await home.part("success")
    direct = await sign_in(home, identifier)
    open_ = object_("Open URL", find(direct.lines, lambda value: object_("Step", value)["step"] == "open_url"))
    check("Host list", isinstance(open_["allowedHosts"], list)
          and includes(open_["allowedHosts"], hostname(text("URL", open_["url"]))), "URL hostname on allowedHosts", open_)
    await home.part("by-code")
    await sign_in(home, identifier, True)
    await home.part("waiting")
    first = home.start(["subscriptions", "sign-in", identifier])
    try:
        await first.step("open_url")
        equal("Pending state", (await subscription(home, identifier))["state"], "signing_in")
        changed = await home.json(["subscriptions", "update", identifier, "--label", "Changed while waiting"])
        equal("No lock across sign-in", changed.process["status"], 0)
        await home.part("success")
        await sign_in(home, identifier)
        replaced = await first.step("failed")
        equal("Replacement error", object_("Error", replaced["error"])["code"], "in_use")
        equal("Replaced exit", (await first.done)["status"], 1)
    finally:
        await first.dispose()
    if identifier == "chatgpt":
        created = await home.json(["subscriptions", "create", "--family", identifier, "--label", "Other login", "--id",
                                   "login-other"])
        equal("Create another login home", created.process["status"], 0)
        await home.part("waiting")
        machine = home.start(["subscriptions", "sign-in", identifier])
        try:
            await machine.step("open_url")
            await home.part("success")
            await sign_in(home, "login-other")
            replaced = await machine.step("failed")
            equal("Machine-wide replacement error", object_("Error", replaced["error"])["code"], "in_use")
            equal("Machine-wide replaced exit", (await machine.done)["status"], 1)
            equal("Replaced home signed out", (await subscription(home, identifier))["state"], "signed_out")
        finally:
            await machine.dispose()
        await home.part("waiting")
        device = home.start(["subscriptions", "sign-in", identifier, "--by-code"])
        try:
            step = await device.step("open_url")
            text("Device code", step["userCode"])
            await home.part("success")
            await sign_in(home, "login-other")
            equal("Device login is independent of machine login", (await subscription(home, identifier))["state"],
                  "signing_in")
            device.stop()
            equal("Device cancellation exit", (await device.done)["status"], 2)
        finally:
            await device.dispose()
    await home.part("waiting")
    home.env["ARBOL_TEST_TIME_SCALE"] = "100"
    pending = home.start(["subscriptions", "sign-in", identifier])
    try:
        await pending.step("open_url")
        expired = await pending.step("failed", 6000)
        equal("Timeout code", object_("Error", expired["error"])["code"], "limit_reached")
        equal("Timeout exit", (await pending.done)["status"], 1)
        equal("Timeout signed out", (await subscription(home, identifier))["state"], "signed_out")
    finally:
        await pending.dispose()
    if any(family["id"] == "zai" for family in await families(home)):
        await home.part("success")
        gateway = await gateway_fixture(home)
        service: str | None = None
        try:
            signed = await sign_in(home, "zai")
            check("Command key needs no store step", not has_step(signed.lines, "store_secret"), "no store_secret",
                  signed.lines)
            settings: Any = parse(text_of(stringify(gateway.settings)))
            del settings["subscriptions"]["zai"]["secret"]
            await home.settings(settings)
            prompted = home.start(["subscriptions", "sign-in", "zai"])
            try:
                step = await prompted.step("store_secret")
                service = text("Service", object_("Keychain item", step["keychain"])["service"])
                check("Isolated Keychain service", test(r"\.[a-f0-9]{12}\Z", service), "hashed test-directory service",
                      service)
                await store(service, "zai", KEY)
                await prompted.step("done")
                equal("Keychain sign-in exit", (await prompted.done)["status"], 0)
            finally:
                await prompted.dispose()
            out = await home.json(["subscriptions", "sign-out", "zai"])
            equal("Key sign-out state", out.result["state"], "signed_out")
            equal("Sign-out removes Keychain item",
                  (await keychain(["find-generic-password", "-s", service, "-a", "zai", "-w"]))["status"], 44)
            await store(service, "zai", KEY)
            prefilled = await sign_in(home, "zai")
            check("Prefilled item skips prompt", not has_step(prefilled.lines, "store_secret"), "no store_secret",
                  prefilled.lines)
            gateway.mode = "rejected"
            rejected = home.start(["subscriptions", "sign-in", "zai"])
            try:
                failed = await rejected.step("failed")
                equal("Vendor rejects key", object_("Error", failed["error"])["code"], "credential_rejected")
                await rejected.done
            finally:
                await rejected.dispose()
            equal("Vendor-rejected key removed",
                  (await keychain(["find-generic-password", "-s", service, "-a", "zai", "-w"]))["status"], 44)
            gateway.mode = "unavailable"
            await store(service, "zai", KEY)
            unreachable = await sign_in(home, "zai")
            equal("Unchecked key has no checkedAt", object_("Subscription", unreachable.done["subscription"])["checkedAt"],
                  UNDEFINED)
            equal("Unreachable vendor keeps key",
                  trim((await keychain(["find-generic-password", "-s", service, "-a", "zai", "-w"]))["stdout"]), KEY)
        finally:
            if service:
                await keychain(["delete-generic-password", "-s", service, "-a", "zai"])
            await gateway.dispose()


# --- C3 --------------------------------------------------------------------------------------------------


async def run_c3(home: ScenarioHome) -> None:
    family = find(await families(home), lambda value: value["auth"] == "key")
    if family is UNDEFINED:
        before = len(await home.received())
        refused = await home.json(["subscriptions", "create", "--family", "openai", "--label", "Unsupported key", "--id",
                                   "key-not-offered"])
        equal("Unavailable key family exit", refused.process["status"], 1)
        equal("Unavailable key family refusal",
              object_("Unavailable key family error", refused.result["error"])["code"], "invalid_input")
        equal("Unavailable key family starts no vendor", len(await home.received()), before)
        return
    identifier = text("Family id", family["id"])
    pending = home.start(["subscriptions", "sign-in", identifier])
    service: str | None = None
    try:
        step = await pending.step("store_secret")
        entry = object_("Keychain item", step["keychain"])
        service = text("Service", entry["service"])
        check("Test service is isolated", test(r"\.[a-f0-9]{12}\Z", service), "hashed test-directory service", service)
        equal("Item account", entry["account"], identifier)
        await store(service, identifier, "fixture-key“ ”—")
        failed = await pending.step("failed")
        error = object_("Error", failed["error"])
        equal("Validation error", error["code"], "invalid_input")
        message = error["message"]
        check("Offending characters named", isinstance(message, str) and "U+201C" in message and "U+00A0" in message
              and "U+2014" not in message, "up to three invalid code points", error)
        equal("Failed sign-in exit", (await pending.done)["status"], 1)
        equal("Rejected key removed",
              (await keychain(["find-generic-password", "-s", service, "-a", identifier, "-w"]))["status"], 44)
        equal("Failed state", (await subscription(home, identifier))["state"], "signed_out")
    finally:
        await pending.dispose()
        if service:
            await keychain(["delete-generic-password", "-s", service, "-a", identifier])


# --- C4 --------------------------------------------------------------------------------------------------


async def check_subscription_rejection(home: ScenarioHome, include_runs: bool = False) -> None:
    await home.part("success")
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    for family in await families(home):
        identifier = text("Family id", family["id"])
        gateway: Gateway | None = None
        if family["auth"] == "key":
            gateway = await gateway_fixture(home)
        try:
            await sign_in(home, identifier)
            if gateway is not None:
                gateway.mode = "rejected"
            else:
                await home.part("rejected")
            rejected = await home.json(["subscriptions", "check", identifier])
            equal("Check exit", rejected.process["status"], 0)
            equal("Rejected state", rejected.result["state"], "needs_attention")
            problem = object_("Problem", rejected.result["problem"])
            equal("Credential code", problem["code"], "credential_rejected")
            text("Remedy", problem["remedy"])
            before = len(await home.received())
            refused = await home.json(["subscriptions", "models", identifier])
            equal("Models refuse attention state", object_("Error", refused.result["error"])["code"], "not_signed_in")
            equal("Refused catalog starts no tool", len(await home.received()), before)
            if gateway is not None:
                gateway.mode = "ok"
            else:
                await home.part("success")
            recovered = await home.json(["subscriptions", "check", identifier])
            equal("Check recovers attention state", recovered.result["state"], "signed_in")
            equal("Problem cleared", recovered.result["problem"], UNDEFINED)
            if include_runs:
                events = stream(await home.call(["run", "--subscription", identifier, "answer"]), "failed")
                equal("Run rejected", prop(at(events, -1), "error", "code"), "credential_rejected")
                marked = await subscription(home, identifier)
                equal("Run marks Subscription", marked["state"], "needs_attention")
                equal("Run problem stored", marked["problem"], at(events, -1)["error"])
        finally:
            if gateway is not None:
                await gateway.dispose()


async def run_c4(home: ScenarioHome) -> None:
    await check_subscription_rejection(home, True)


# --- C5 --------------------------------------------------------------------------------------------------


async def run_c5(home: ScenarioHome) -> None:
    root = await state(home)
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    identifier = await vendor_family(home)
    for operation in ("sign-out", "remove"):
        await home.part("success")
        await sign_in(home, identifier)
        await home.part("hold")
        active = home.start(["run", "--subscription", identifier, "--tools", "all", "--cwd", home.home, "--control",
                             "answer"])
        try:
            deadline = now_monotonic() + 5000
            while not any(prop(event, "type") == "started" for event in active.lines):
                check("Run starts", now_monotonic() < deadline, "within five seconds", active.lines)
                await delay(10)
            refused = await home.json(["subscriptions", operation, identifier])
            equal("Busy refusal", object_("Error", refused.result["error"])["code"], "in_use")
            equal("Busy exit", refused.process["status"], 1)
            equal("Refusal retains login", (await subscription(home, identifier))["state"], "signed_in")
            forced = await home.call(["subscriptions", operation, identifier, "--force"])
            equal("Forced exit", forced["status"], 0)
            stream(await active.done, "cancelled")
            equal("Run record removed", listing(join(root, "runs")), [])
            equal("Run folder removed", listing(join(root, "tmp")), [])
            seen = at([entry for entry in await home.received() if entry["stage"] == "input"], -1)
            for pid in (prop(seen, "checks", "toolPid"), prop(seen, "checks", "backgroundPid")):
                if is_number(pid):
                    equal("Tool and shell leftovers ended", await running(pid), False)
            equal("Credential removed", (await subscription(home, identifier))["state"], "signed_out")
            if operation == "remove":
                equal("Home removed", not exists(join(root, "subscriptions", identifier, "home")), True)
        finally:
            await active.dispose()


# --- C6 --------------------------------------------------------------------------------------------------


async def run_c6(home: ScenarioHome) -> None:
    root = await state(home)
    await home.part("waiting")
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    identifier = await vendor_family(home)
    for signal in ("SIGTERM", "SIGKILL"):
        pending = home.start(["subscriptions", "sign-in", identifier])
        try:
            await pending.step("open_url")
            progress = read_json(join(root, "subscriptions", identifier, "sign-in.json"))
            pending.stop(signal)
            result = await pending.done
            if signal == "SIGTERM":
                equal("Cancelled exit", result["status"], 2)
                check("Failed final step", has_step(pending.lines, "failed"), "failed step", pending.lines)
            equal("Dead sign-in is signed out", (await subscription(home, identifier))["state"], "signed_out")
            await home.json(["subscriptions", "update", identifier, "--label", "After cancellation"])
            equal("Progress removed", not exists(join(root, "subscriptions", identifier, "sign-in.json")), True)
            alive = await running(prop(progress, "tool", "pid"))
            equal("Login child is gone", alive, False)
        finally:
            await pending.dispose()


# --- C7 --------------------------------------------------------------------------------------------------


async def check_subscription_credentials(home: ScenarioHome, include_runs: bool = False) -> None:
    root = await state(home)
    await home.part("success")
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    all_families = await families(home)
    gateway = await gateway_fixture(home) if any(family["id"] == "zai" for family in all_families) else None
    outputs: list[str] = []
    codex = (await home.json(["info"])).result["driver"] == "codex"
    try:
        for family in all_families:
            identifier = text("Family identifier", family["id"])
            signed = await sign_in(home, identifier)
            outputs += [signed.result["stdout"], signed.result["stderr"]]
            for command in ("check", "usage", "models"):
                result = await home.call(["subscriptions", command, identifier])
                equal("Subscription operation exit", result["status"], 0)
                outputs += [result["stdout"], result["stderr"]]
        if include_runs and codex:
            mkdir(join(home.home, ".codex"), mode=0o700)
            write_file(join(home.home, ".codex/config.toml"), '[mcp_servers.fixture]\ncommand = "fixture-server"\n'
                       '[mcp_servers.fixture.env]\nFIXTURE_TOKEN = "' + KEY + '"\n', 0o600)
        for part in ("plain", "failed", "stderr") if include_runs else ():
            await home.part(part)
            if gateway is not None:
                await home.settings(gateway.settings)
            key_family = get(find(all_families, lambda family: family["auth"] == "key"), "id")
            identifier = text("Run family", get(item(all_families, 0), "id") if nullish(key_family) else key_family)
            extra = ["--tools", "all", "--cwd", home.home] if codex else []
            result = await home.call(["run", "--subscription", identifier, *extra, "answer"])
            events = stream(result, "completed" if part == "plain" else "failed")
            outputs += [result["stdout"], result["stderr"]]
            if codex:
                await check_scrubbed(home, events, part)
            if part == "plain":
                plain = await home.call(["run", "--subscription", identifier, *extra, "--output", "text", "answer"])
                equal("Text run completes", plain["status"], 0)
                outputs += [plain["stdout"], plain["stderr"]]
        for path in files(root):
            content = read_file(path)
            check("No gateway key in state", KEY not in content, "no key value", path)
            if "/home/" not in path:
                check("No copied vendor credential", "fixture-vendor-secret" not in content,
                      "credential only in vendor home", path)
        outputs.append(read_file(join(home.tool, "received.jsonl")))
        for output in outputs:
            check("No credential in outputs or arguments", KEY not in output and "fixture-vendor-secret" not in output,
                  "no credential values", "output checked")
    finally:
        if gateway is not None:
            await gateway.dispose()


async def check_scrubbed(home: ScenarioHome, events: JSArray, part: str) -> None:
    """The Codex stand-in's private literal is redacted in every kind of event."""
    def first(predicate: Callable[[JSObject], bool], *path: str) -> Any:
        return prop(find(events, predicate), *path)

    def deltas(kind: str) -> str:
        return joined(event["text"] for event in events if event["type"] == kind)

    equal("Answer private literal scrubbed", first(lambda event: event["type"] == "text", "text"), "answer [redacted]")
    equal("Reasoning private literal scrubbed", first(lambda event: event["type"] == "thinking", "text"),
          "thinking [redacted]")
    equal("Split answer deltas scrubbed", deltas("text_delta"), "answer [redacted]")
    equal("Split reasoning deltas scrubbed", deltas("thinking_delta"), "thinking [redacted]")
    equal("Split tool deltas scrubbed", deltas("tool_output_delta"), "output [redacted]")
    equal("Shell private literal scrubbed",
          first(lambda event: event["type"] == "tool_started" and event["name"] == "shell", "input", "command"),
          "echo [redacted]")
    equal("Shell output private literal scrubbed",
          first(lambda event: event["type"] == "tool_finished" and event["callId"] == "fixture-call", "result",
                "output"), "output [redacted]")
    equal("Structured tool argument private literal scrubbed",
          first(lambda event: event["type"] == "tool_started" and event["name"] == "mcpToolCall", "input", "arguments",
                "private"), "[redacted]")
    equal("Structured tool result private literal scrubbed",
          first(lambda event: event["type"] == "tool_finished" and event["callId"] == "credential-mcp", "result",
                "structuredContent", "private"), "[redacted]")
    equal("Notice private literal scrubbed", first(lambda event: event["type"] == "notice", "message"),
          "Private diagnostic [redacted]")
    equal("Credential fixture actually emitted",
          len([entry for entry in await home.received()
               if entry["stage"] == "credential-output" and entry["part"] == part]), 1)


async def run_c7(home: ScenarioHome) -> None:
    await check_subscription_credentials(home, True)


# --- C8 --------------------------------------------------------------------------------------------------


async def check_subscription_environments(home: ScenarioHome, include_run: bool = False) -> None:
    await home.part("success")
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    home.env.update({"ANTHROPIC_API_KEY": KEY, "CLAUDECODE": "1", "CLAUDE_SESSION_ID": KEY, "OPENAI_API_KEY": KEY,
                     "OPENAI_BASE_URL": "http://127.0.0.1:9", "CODEX_HOME": "/wrong-home", "CODEX_API_KEY": KEY})
    identifier = await vendor_family(home)
    await sign_in(home, identifier)
    for command in ("check", "usage", "models"):
        equal("Subscription operation exit", (await home.call(["subscriptions", command, identifier]))["status"], 0)
    if include_run:
        stream(await home.call(["run", "--subscription", identifier, "answer"]))
    for received in [entry for entry in await home.received() if entry["stage"] != "input"]:
        equal("No inherited selectors", received["checks"]["injectedVariablesAbsent"], True)
        arguments = received["arguments"]
        if arguments[0] != "--version" and not includes(arguments, "--input-format"):
            equal("Both homes private", received["checks"]["privateHome"], True)


async def run_c8(home: ScenarioHome) -> None:
    await check_subscription_environments(home, True)


# --- C39 -------------------------------------------------------------------------------------------------


async def run_c39(home: ScenarioHome) -> None:
    await home.part("success")
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    family = await vendor_family(home)
    created = await home.json(["subscriptions", "create", "--family", family, "--label", "Second", "--id", "second"])
    equal("Creation exit", created.process["status"], 0)
    await sign_in(home, family)
    await sign_in(home, "second")
    homes = set_size(entry["checks"]["home"] for entry in await home.received() if entry["arguments"][0] != "--version")
    equal("Distinct vendor homes", homes, 2)
    await home.call(["subscriptions", "sign-out", family])
    equal("First is out", (await subscription(home, family))["state"], "signed_out")
    equal("Second still works", (await home.json(["subscriptions", "check", "second"])).result["state"], "signed_in")


# --- C41 -------------------------------------------------------------------------------------------------

RESOURCES = ("tokens", "credits", "calls")


def check_resources(site: str, windows: Any) -> None:
    """DRV-1.27: a window says what it counts, `tokens`, `credits` or `calls`, or leaves `resource` absent; it never
    carries another value."""
    for index, window in enumerate(array(windows, "forEach", site)):
        resource = get(object_(f"{site}[{index}]", window), "resource")
        check(f"{site}[{index}].resource", resource is UNDEFINED or resource in RESOURCES,
              "tokens, credits, calls or absent", resource)


def operations(records: list[JSObject]) -> JSArray:
    """The operations the stand-in was asked for, setup requests left out."""
    return JSArray(entry["checks"]["operation"] for entry in records
                   if entry["stage"] == "request" and entry["checks"]["operation"] != "setup")


async def check_chatgpt_usage(home: ScenarioHome) -> None:
    await home.part("success")
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    identifier = "chatgpt"
    equal("Unsigned usage", (await home.json(["subscriptions", "usage", identifier])).result["outcome"], "needs_sign_in")
    await sign_in(home, identifier)
    account = object_("Vendor account", (await subscription(home, identifier))["account"])
    equal("Vendor email", account["email"], "fixture@example.invalid")
    equal("Vendor plan", account["plan"], "fixture")
    before = len(await home.received())
    await home.call(["subscriptions", "list"])
    equal("List does not poll", len(await home.received()), before)
    catalog = await home.json(["subscriptions", "models", identifier])
    equal("Catalog exit", catalog.process["status"], 0)
    equal("Catalog source", catalog.result["source"], "tool")
    equal("Only catalog pages requested", operations((await home.received())[before:]), ["models", "models"])
    models = [object_("Model", value) for value in array(catalog.result["models"], "map", "catalog.result.models")]
    equal("Every model page read", [value["id"] for value in models], ["gpt-6.1-sol", "gpt-6-astra"])
    equal("Vendor model label", get(item(models, 0), "label"), "GPT-6.1-Sol")
    equal("Vendor effort words", get(item(models, 0), "efforts"), ["low", "medium", "high", "xhigh", "max", "ultra"])
    equal("Default effort", get(item(models, 0), "defaultEffort"), "low")
    equal("Service tiers", get(item(models, 0), "serviceTiers"), ["priority"])
    equal("Default model", get(item(models, 0), "isDefault"), True)
    before_usage = len(await home.received())
    usage = await home.json(["subscriptions", "usage", identifier])
    equal("Usage exit", usage.process["status"], 0)
    equal("Usage outcome", usage.result["outcome"], "ok")
    equal("Usage plan", usage.result["plan"], "fixture")
    equal("Only requested usage", operations((await home.received())[before_usage:]), ["usage"])
    windows = [object_("Window", value) for value in array(usage.result["windows"], "map", "usage.result.windows")]
    check_resources("usage.result.windows", usage.result["windows"])
    equal("Window kind follows duration", [value["kind"] for value in windows], ["weekly", "session"])
    equal("Window labels", [value["label"] for value in windows], ["Weekly window", "5-hour window"])
    equal("Used percentage", get(item(windows, 0), "usedPercent"), 25)
    equal("Weekly length", get(item(windows, 0), "windowMinutes"), 10080)
    equal("Vendor reset in UTC", get(item(windows, 0), "resetsAt"), iso(1791640848 * 1000))
    equal("Unknown reset absent", get(item(windows, 1), "resetsAt"), UNDEFINED)
    equal("Exhausted window", get(item(windows, 1), "limitReached"), True)
    equal("Vendor details URL", usage.result["detailsUrl"], "https://chatgpt.com/codex/settings/usage")
    equal("Good usage cached", (await subscription(home, identifier))["lastUsage"], usage.result)
    await home.part("unavailable")
    unavailable = await home.json(["subscriptions", "usage", identifier])
    equal("Unavailable usage", unavailable.result["outcome"], "unavailable")
    equal("Unavailable windows empty", unavailable.result["windows"], [])
    text("Unavailable reason", unavailable.result["message"])
    equal("Last good report preserved", (await subscription(home, identifier))["lastUsage"], usage.result)
    fallback = await home.json(["subscriptions", "models", identifier])
    equal("Fallback source", fallback.result["source"], "builtin")
    fallback_models = fallback.result["models"]
    check("Fallback remains in ChatGPT family", isinstance(fallback_models, list) and len(fallback_models) > 0
          and all(text("Model", object_("Model entry", value)["id"]).startswith("gpt-") for value in fallback_models),
          "ChatGPT models", fallback_models)
    await home.part("unknown-windows")
    unknown = await home.json(["subscriptions", "usage", identifier])
    equal("Unknown-window usage", unknown.result["outcome"], "ok")
    other = [object_("Window", value) for value in array(unknown.result["windows"], "map", "unknown.result.windows")]
    check_resources("unknown.result.windows", unknown.result["windows"])
    equal("Unknown length is absent", get(item(other, 0), "windowMinutes"), UNDEFINED)
    equal("Unknown length kind", get(item(other, 0), "kind"), "other")
    equal("Unknown reset is absent", get(item(other, 0), "resetsAt"), UNDEFINED)
    equal("Other duration kind", get(item(other, 1), "kind"), "other")
    equal("Other duration", get(item(other, 1), "windowMinutes"), 1440)
    await home.part("rejected")
    equal("Rejected usage", (await home.json(["subscriptions", "usage", identifier])).result["outcome"], "needs_sign_in")
    rejected = await subscription(home, identifier)
    equal("Rejected login needs attention", rejected["state"], "needs_attention")
    equal("Rejected credential code", object_("Problem", rejected["problem"])["code"], "credential_rejected")
    await home.part("success")
    equal("Recovery check", (await home.json(["subscriptions", "check", identifier])).result["state"], "signed_in")
    out = await home.json(["subscriptions", "sign-out", identifier])
    equal("Sign-out exit", out.process["status"], 0)
    equal("Account gone", out.result["account"], UNDEFINED)
    equal("Cached usage gone", out.result["lastUsage"], UNDEFINED)


async def run_c41(home: ScenarioHome) -> None:
    offered = await families(home)
    if any(value["id"] == "chatgpt" for value in offered):
        await check_chatgpt_usage(home)
        return
    if [value["id"] for value in offered] == ["anthropic"]:
        await home.part("success")
        equal("Unsigned usage", (await home.json(["subscriptions", "usage", "anthropic"])).result["outcome"],
              "needs_sign_in")
        await sign_in(home, "anthropic")
        account = object_("Vendor account", (await subscription(home, "anthropic"))["account"])
        equal("Vendor plan", account["plan"], "fixture")
        before = len(await home.received())
        await home.call(["subscriptions", "list"])
        equal("List does not poll", len(await home.received()), before)
        unsupported = await home.json(["subscriptions", "usage", "anthropic"])
        equal("Usage unsupported before run", unsupported.result["outcome"], "unsupported")
        check_resources("unsupported.result.windows", unsupported.result["windows"])
        equal("Tool catalog source", (await home.json(["subscriptions", "models", "anthropic"])).result["source"],
              "tool")
        await home.part("unavailable")
        fallback = await home.json(["subscriptions", "models", "anthropic"])
        equal("Unavailable catalog marked builtin", fallback.result["source"], "builtin")
        check("Fallback is nonempty", isinstance(fallback.result["models"], list) and bool(fallback.result["models"]),
              "Anthropic models", fallback.result)
        for model in array(fallback.result["models"], "map", "models"):
            check("No retired model", not text("Model id", object_("Model", model)["id"]).startswith("glm"),
                  "Anthropic model", model)
        await home.part("success")
        out = await home.json(["subscriptions", "sign-out", "anthropic"])
        equal("Account gone", out.result["account"], UNDEFINED)
        equal("Cached usage gone", out.result["lastUsage"], UNDEFINED)
        before = len(await home.received())
        for command in ("check", "usage", "models", "sign-in"):
            stale = await home.json(["subscriptions", command, "zai"])
            equal("Retired route refused", stale.result["error"]["code"], "invalid_input")
        equal("Retired requests never reach native tool", len(await home.received()), before)
        return
    await home.part("success")
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    gateway = await gateway_fixture(home)
    try:
        equal("Unsigned usage", (await home.json(["subscriptions", "usage", "zai"])).result["outcome"], "needs_sign_in")
        await sign_in(home, "zai")
        gateway.paths.clear()
        await home.call(["subscriptions", "list"])
        equal("List does not poll", gateway.paths, [])
        catalog = await home.json(["subscriptions", "models", "zai"])
        equal("Vendor source", catalog.result["source"], "vendor")
        equal("Only models request", gateway.paths, ["/api/paas/v4/models"])
        gateway.paths.clear()
        usage = await home.json(["subscriptions", "usage", "zai"])
        equal("Usage outcome", usage.result["outcome"], "ok")
        equal("Only requested usage", gateway.paths, ["/api/monitor/usage/quota/limit"])
        windows = usage.result["windows"]
        check_resources("usage.result.windows", windows)
        equal("Computed percentage", get(prop(windows, 0), "usedPercent"), 25)
        equal("Unknown reset absent", get(prop(windows, 1), "resetsAt"), UNDEFINED)
        equal("Unknown length absent", get(prop(windows, 2), "windowMinutes"), UNDEFINED)
        equal("Good usage cached", (await subscription(home, "zai"))["lastUsage"], usage.result)
        gateway.mode = "unavailable"
        unavailable = await home.json(["subscriptions", "usage", "zai"])
        equal("Unavailable usage", unavailable.result["outcome"], "unavailable")
        check("Error redacted", KEY not in unavailable.process["stdout"], "no key", "output checked")
        equal("Last good report preserved", (await subscription(home, "zai"))["lastUsage"], usage.result)
        fallback = await home.json(["subscriptions", "models", "zai"])
        equal("Fallback source", fallback.result["source"], "builtin")
        equal("Own family only", fallback.result["models"], [record(id="fixture-fallback", label="fixture-fallback")])
        await sign_in(home, "anthropic")
        account = object_("Vendor account", (await subscription(home, "anthropic"))["account"])
        equal("Vendor plan", account["plan"], "fixture")
        equal("Anthropic usage unsupported before run",
              (await home.json(["subscriptions", "usage", "anthropic"])).result["outcome"], "unsupported")
        equal("Tool catalog source", (await home.json(["subscriptions", "models", "anthropic"])).result["source"], "tool")
        await home.part("unavailable")
        await home.settings(gateway.settings)
        tool_fallback = await home.json(["subscriptions", "models", "anthropic"])
        equal("Tool fallback marked builtin", tool_fallback.result["source"], "builtin")
        tool_models = tool_fallback.result["models"]
        check("Tool fallback is its own family", isinstance(tool_models, list) and all(
            not text("Model", object_("Model entry", value)["id"]).startswith("fixture-") for value in tool_models),
            "Anthropic names", tool_models)
        await home.part("success")
        await home.settings(gateway.settings)
        out = await home.json(["subscriptions", "sign-out", "anthropic"])
        equal("Account gone", out.result["account"], UNDEFINED)
        equal("Cached usage gone", out.result["lastUsage"], UNDEFINED)
        gateway.mode = "rejected"
        equal("Rejected usage", (await home.json(["subscriptions", "usage", "zai"])).result["outcome"], "needs_sign_in")
        equal("Rejected key needs attention", (await subscription(home, "zai"))["state"], "needs_attention")
    finally:
        await gateway.dispose()


c2 = Scenario("C2", "Sign-in steps, replacement and expiry",
              "vendor login, code, command key and Keychain step; replacement and five-minute expiry",
              ["DRV-1.5", "DRV-1.6", "DRV-1.25", "DRV-6.9"], run_c2)
c3 = Scenario("C3", "Refusing a malformed Keychain key",
              "store_secret, invalid Unicode, deletion and isolated Keychain service; typed refusal where no key family "
              "is offered", ["DRV-1.4", "DRV-1.26"], run_c3)
c4 = Scenario("C4", "Rejected credentials and recovery",
              "check and run rejection, all families, and attention-state recovery",
              ["DRV-1.7", "DRV-4.7", "DRV-1.11 (attention check)"], run_c4)
c5 = Scenario("C5", "Sign-out and removal while a real run uses the account",
              "live run refusal, forced cancellation, shell cleanup and account removal", ["DRV-1.12"], run_c5)
c6 = Scenario("C6", "Cancelling and killing a pending sign-in",
              "signal cancellation, dead-owner recovery and orphaned login child", ["DRV-1.24", "DRV-1.25", "DRV-0.8"],
              run_c6)
c7 = Scenario("C7", "Credentials stay out of Driver data and output",
              "subscription operations, streamed text/thinking, tools, errors, stderr, text output and tool-owned login",
              ["DRV-0.3", "DRV-1.3", "DRV-1.8"], run_c7)
c8 = Scenario("C8", "Clean environments for every tool child", "sign-in, status, catalog and inference children",
              ["DRV-0.5"], run_c8)
c39 = Scenario("C39", "Two accounts of one family stay independent",
               "independent login, homes and sign-out; conversation separation covered by C14",
               ["DRV-1.2 (subscriptions)"], run_c39)
c41 = Scenario("C41", "Usage, model catalogs and vendor account details",
               "available usage outcomes, cached reports, unknown fields, what each window counts, family fallback and "
               "account clearing; run-derived usage covered by C30",
               ["DRV-1.16", "DRV-1.17", "DRV-1.18", "DRV-1.19", "DRV-1.20", "DRV-1.21", "DRV-1.22", "DRV-1.27"], run_c41)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
