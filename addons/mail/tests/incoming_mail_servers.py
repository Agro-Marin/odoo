import socketserver
import ssl
import threading
from typing import Any, Self


class _Mailbox:
    def __init__(self, messages: list[tuple[int, bytes, list[str]]]) -> None:
        self.messages = [[uid, raw, set(flags)] for uid, raw, flags in messages]
        self.log: list[str] = []
        self.expunged: list[int] = []
        self.deleted: set[int] = set()
        self.credentials: dict[str, str] = {}
        self.quit_received = False
        self.literal_less: set[int] = set()

    @property
    def uids(self) -> list[int]:
        return [message[0] for message in self.messages]

    def flags(self) -> dict[int, list[str]]:
        return {uid: sorted(flags) for uid, _raw, flags in self.messages}

    def expunge_uid(self, uid: int) -> None:
        self.messages = [m for m in self.messages if m[0] != uid]
        self.expunged.append(uid)


class _ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    mailbox: _Mailbox
    ssl_context: ssl.SSLContext | None = None

    def get_request(self) -> tuple[Any, Any]:
        sock, addr = super().get_request()
        if self.ssl_context is not None:
            sock = self.ssl_context.wrap_socket(sock, server_side=True)
        return sock, addr


class _IMAPHandler(socketserver.StreamRequestHandler):
    def _send(self, text: str | bytes) -> None:
        self.wfile.write(text if isinstance(text, bytes) else text.encode())
        self.wfile.flush()

    def handle(self) -> None:
        mailbox = self.server.mailbox
        self._send("* OK [CAPABILITY IMAP4rev1] test imap ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            mailbox.log.append(line.strip().decode(errors="replace"))
            parts = line.strip().split()
            tag = parts[0].decode()
            command = parts[1].upper() if len(parts) > 1 else b""
            args = parts[2:]
            if command == b"UID":
                command, args = b"UID_" + args[0].upper(), args[1:]
            handler = getattr(self, f"_cmd_{command.decode().lower()}", None)
            if handler is None:
                self._send(f"{tag} BAD unknown command\r\n")
                continue
            if handler(tag, args, mailbox) is False:
                return

    def _cmd_capability(self, tag, _args, _mailbox) -> None:
        self._send("* CAPABILITY IMAP4rev1\r\n")
        self._send(f"{tag} OK CAPABILITY done\r\n")

    def _cmd_login(self, tag, args, mailbox) -> None:
        mailbox.credentials = {
            "user": args[0].decode().strip('"'),
            "password": args[1].decode().strip('"'),
        }
        self._send(f"{tag} OK LOGIN done\r\n")

    def _cmd_select(self, tag, _args, mailbox) -> None:
        self._send(f"* {len(mailbox.messages)} EXISTS\r\n")
        self._send("* FLAGS (\\Seen \\Deleted)\r\n")
        self._send(f"{tag} OK [READ-WRITE] SELECT done\r\n")

    def _cmd_uid_search(self, tag, args, mailbox) -> None:
        criteria = b" ".join(args).upper()
        hits = [
            uid
            for uid, _raw, flags in mailbox.messages
            if b"UNSEEN" not in criteria or "\\Seen" not in flags
        ]
        self._send("* SEARCH " + " ".join(map(str, hits)) + "\r\n")
        self._send(f"{tag} OK UID SEARCH done\r\n")

    def _find(self, mailbox, uid: int):
        for message in mailbox.messages:
            if message[0] == uid:
                return message
        return None

    def _cmd_uid_fetch(self, tag, args, mailbox) -> None:
        uid = int(args[0])
        if uid in mailbox.literal_less:
            self._send(f"* 1 FETCH (UID {uid} FLAGS ())\r\n".encode())
            self._send(f"{tag} OK UID FETCH done\r\n")
            return
        message = self._find(mailbox, uid)
        if message is None:
            self._send(f"{tag} OK UID FETCH done (no such uid)\r\n")
            return
        item = b" ".join(args[1:]).upper()
        peek = b"PEEK" in item
        if not peek:
            message[2].add("\\Seen")
        body = message[1]
        flags = " ".join(sorted(message[2]))
        name = "BODY[]" if peek else "RFC822"
        self._send(
            f"* 1 FETCH (UID {message[0]} {name} {{{len(body)}}}\r\n".encode()
            + body
            + f" FLAGS ({flags}))\r\n".encode()
        )
        self._send(f"{tag} OK UID FETCH done\r\n")

    def _cmd_uid_store(self, tag, args, mailbox) -> None:
        message = self._find(mailbox, int(args[0]))
        if message is None:
            self._send(f"{tag} OK UID STORE done (no such uid)\r\n")
            return
        operation, flag = args[1].decode(), args[2].decode().strip("()")
        if operation.startswith("+"):
            message[2].add(flag)
        elif operation.startswith("-"):
            message[2].discard(flag)
        self._send(f"{tag} OK UID STORE done\r\n")

    def _cmd_close(self, tag, _args, mailbox) -> None:
        for message in list(mailbox.messages):
            if "\\Deleted" in message[2]:
                mailbox.expunge_uid(message[0])
        self._send(f"{tag} OK CLOSE done\r\n")

    def _cmd_unselect(self, tag, _args, _mailbox) -> None:
        self._send(f"{tag} OK UNSELECT done\r\n")

    def _cmd_logout(self, tag, _args, _mailbox) -> bool:
        self._send("* BYE\r\n")
        self._send(f"{tag} OK LOGOUT done\r\n")
        return False


class _POP3Handler(socketserver.StreamRequestHandler):
    def _send(self, text: str | bytes) -> None:
        self.wfile.write(text if isinstance(text, bytes) else text.encode())
        self.wfile.flush()

    def _numbered(self, mailbox):
        return dict(enumerate(mailbox.messages, 1))

    def handle(self) -> None:
        mailbox = self.server.mailbox
        self._send("+OK test pop3 ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            mailbox.log.append(line.strip().decode(errors="replace"))
            parts = line.strip().split()
            if not parts:
                continue
            command = parts[0].upper()
            numbered = self._numbered(mailbox)
            live = {
                number: message
                for number, message in numbered.items()
                if message[0] not in mailbox.deleted
            }
            if command == b"USER":
                mailbox.credentials["user"] = parts[1].decode()
                self._send("+OK\r\n")
            elif command == b"PASS":
                mailbox.credentials["password"] = parts[1].decode()
                self._send("+OK\r\n")
            elif command == b"STAT":
                self._send(
                    f"+OK {len(live)} {sum(len(m[1]) for m in live.values())}\r\n"
                )
            elif command == b"LIST":
                self._send("+OK\r\n")
                for number, message in sorted(live.items()):
                    self._send(f"{number} {len(message[1])}\r\n")
                self._send(".\r\n")
            elif command == b"RETR":
                message = live.get(int(parts[1]))
                if message is None:
                    self._send("-ERR no such message\r\n")
                    continue
                body = message[1]
                self._send(f"+OK {len(body)} octets\r\n")
                for raw in body.rstrip(b"\r\n").split(b"\r\n"):
                    self._send(
                        (b".." + raw[1:] if raw.startswith(b".") else raw) + b"\r\n"
                    )
                self._send(".\r\n")
            elif command == b"DELE":
                message = live.get(int(parts[1]))
                if message is None:
                    self._send("-ERR no such message\r\n")
                    continue
                mailbox.deleted.add(message[0])
                self._send("+OK\r\n")
            elif command == b"QUIT":
                mailbox.quit_received = True
                self._send("+OK bye\r\n")
                return
            else:
                self._send("-ERR unknown command\r\n")


class FakeMailServer:
    def __init__(
        self,
        protocol: str,
        messages: list[tuple[int, bytes, list[str]]] | None = None,
        certificate: tuple[str, str] | None = None,
    ) -> None:
        handler = {"imap": _IMAPHandler, "pop": _POP3Handler}[protocol]
        self._server = _ThreadedServer(("127.0.0.1", 0), handler)
        self._server.mailbox = _Mailbox(messages or [])
        if certificate is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*certificate)
            self._server.ssl_context = context
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def mailbox(self) -> _Mailbox:
        return self._server.mailbox

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
