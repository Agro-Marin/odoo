import logging
import poplib
import ssl
from collections.abc import Iterator
from imaplib import IMAP4, IMAP4_SSL
from poplib import POP3, POP3_SSL
from typing import Literal, Protocol

_logger = logging.getLogger(__name__)

MAIL_TIMEOUT = 60

poplib._MAXLINE = 65536

type MessageRef = bytes | int

type Encryption = Literal["none", "starttls", "starttls_strict", "ssl", "ssl_strict"]

ENCRYPTION_SELECTION = [
    ("none", "None"),
    ("starttls_strict", "TLS (STARTTLS), encryption and validation"),
    ("starttls", "TLS (STARTTLS), encryption only"),
    ("ssl_strict", "SSL/TLS, encryption and validation"),
    ("ssl", "SSL/TLS, encryption only"),
]

MAILBOX_PROTOCOLS = ("imap", "pop")

DEFAULT_PORTS = {
    ("imap", False): 143,
    ("imap", True): 993,
    ("pop", False): 110,
    ("pop", True): 995,
}


def ssl_context_for_encryption(encryption: Encryption) -> ssl.SSLContext | None:
    if encryption == "none":
        return None
    context = ssl.create_default_context()
    if encryption in ("ssl", "starttls"):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def default_port(server_type: str, encryption: Encryption) -> int:
    return DEFAULT_PORTS.get((server_type, encryption in ("ssl", "ssl_strict")), 0)


class IncomingMailConnection(Protocol):
    def check_unread_messages(self) -> int:
        pass

    def retrieve_unread_messages(self) -> Iterator[tuple[MessageRef, bytes]]:
        pass

    def handled_message(self, num: MessageRef) -> None:
        pass

    def disconnect(self) -> None:
        pass


class NotSelectedError(RuntimeError):
    pass


class OdooIMAP4(IMAP4):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._unread_messages: list[bytes] | None = None

    def _check(self, typ: str, data: list, command: str) -> list:
        if typ != "OK":
            raise IMAP4.error(f"{command} failed: {typ} {data!r}")
        return data

    def check_unread_messages(self) -> int:
        typ, data = self.select()
        self._check(typ, data, "SELECT")
        typ, data = self.uid("SEARCH", None, "(UNSEEN)")
        self._check(typ, data, "UID SEARCH")
        self._unread_messages = list(
            reversed(data[0].split() if data and data[0] else [])
        )
        return len(self._unread_messages)

    def retrieve_unread_messages(self) -> Iterator[tuple[bytes, bytes]]:
        if self._unread_messages is None:
            raise NotSelectedError("check_unread_messages() must run first")
        while self._unread_messages:
            num = self._unread_messages.pop()
            typ, data = self.uid("FETCH", num, "(RFC822)")
            self._check(typ, data, "UID FETCH")
            if not data or not isinstance(data[0], tuple | list) or len(data[0]) < 2:
                _logger.debug("IMAP message uid %r vanished before FETCH.", num)
                continue
            self.uid("STORE", num, "-FLAGS", "(\\Seen)")
            yield num, data[0][1]

    def handled_message(self, num: bytes) -> None:
        typ, data = self.uid("STORE", num, "+FLAGS", "(\\Seen)")
        self._check(typ, data, "UID STORE")

    def disconnect(self) -> None:
        try:
            if self._unread_messages is not None:
                self.unselect()
        finally:
            self.logout()


class OdooIMAP4_SSL(OdooIMAP4, IMAP4_SSL):
    pass


class OdooPOP3(POP3):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._unread_messages: list[int] | None = None

    def check_unread_messages(self) -> int:
        (num_messages, _total_size) = self.stat()
        self._unread_messages = list(range(num_messages, 0, -1))
        return num_messages

    def retrieve_unread_messages(self) -> Iterator[tuple[int, bytes]]:
        if self._unread_messages is None:
            raise NotSelectedError("check_unread_messages() must run first")
        while self._unread_messages:
            num = self._unread_messages.pop()
            (_header, lines, _octets) = self.retr(num)
            yield num, b"\r\n".join(lines)

    def handled_message(self, num: int) -> None:
        self.dele(num)

    def disconnect(self) -> None:
        self.quit()


class OdooPOP3_SSL(OdooPOP3, POP3_SSL):
    pass


def connect(
    server_type: Literal["imap", "pop"],
    host: str,
    port: int,
    encryption: Encryption,
) -> OdooIMAP4 | OdooPOP3:
    context = ssl_context_for_encryption(encryption)
    implicit_tls = encryption in ("ssl", "ssl_strict")
    if server_type == "imap":
        if implicit_tls:
            connection = OdooIMAP4_SSL(
                host, port, ssl_context=context, timeout=MAIL_TIMEOUT
            )
        else:
            connection = OdooIMAP4(host, port, timeout=MAIL_TIMEOUT)
            if context is not None:
                connection.starttls(context)
        return connection
    if server_type == "pop":
        if implicit_tls:
            connection = OdooPOP3_SSL(host, port, context=context, timeout=MAIL_TIMEOUT)
        else:
            connection = OdooPOP3(host, port, timeout=MAIL_TIMEOUT)
            if context is not None:
                connection.stls(context)
        return connection
    raise ValueError(
        f"unsupported incoming mail protocol {server_type!r}, "
        f"expected one of {MAILBOX_PROTOCOLS}"
    )
