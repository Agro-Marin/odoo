import base64
import contextlib
import mimetypes
from io import BytesIO
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Any
from zlib import adler32

from werkzeug.utils import send_file as _send_file

from odoo.tools import config, file_path

from .constants import STATIC_CACHE_LONG
from .core import request


class Stream:
    """
    Send the content of a file, an attachment or a binary field via HTTP

    This utility is safe, cache-aware and uses the best available
    streaming strategy. Works best with the --x-sendfile cli option.

    Create a Stream via one of the constructors :meth:`~from_path` or
    :meth:`~from_binary_field`, then generate the corresponding HTTP response
    via :meth:`~get_response`.

    Instantiating a Stream object manually without using one of the
    dedicated constructors is discouraged.
    """

    type: str = ""  # 'data' or 'path' or 'url'
    data: bytes | None = None
    path: str | None = None
    url: str | None = None

    mimetype: str | None = None
    as_attachment: bool = False
    download_name: str | None = None
    conditional: bool = True
    etag: bool | str = True
    last_modified: float | None = None
    max_age: int | None = None
    immutable: bool = False
    size: int | None = None
    public: bool = False

    # Whitelist of kwargs accepted by ``__init__`` (kept in sync with the class
    # attributes above). Without it, a typo like ``Stream(as_attatchment=True)``
    # silently set a bogus attribute, leaving ``as_attachment`` at its default.
    _ALLOWED_KWARGS: frozenset[str] = frozenset(
        {
            "type",
            "data",
            "path",
            "url",
            "mimetype",
            "as_attachment",
            "download_name",
            "conditional",
            "etag",
            "last_modified",
            "max_age",
            "immutable",
            "size",
            "public",
        }
    )

    def __init__(self, **kwargs: Any) -> None:
        unknown = kwargs.keys() - self._ALLOWED_KWARGS
        if unknown:
            msg = f"Stream got unexpected keyword arguments: {sorted(unknown)}"
            raise TypeError(msg)
        self.__dict__.update(kwargs)

    @classmethod
    def from_path(
        cls, path: str, filter_ext: tuple[str, ...] = ("",), public: bool = False
    ) -> Stream:
        """
        Create a :class:`~Stream` from an addon resource.

        :param path: See :func:`~odoo.tools.file_path`
        :param filter_ext: See :func:`~odoo.tools.file_path`
        :param bool public: Advertise the resource as being cachable by
            intermediate proxies, otherwise only let the browser cache
            it.
        """
        # Validate that ``path`` resolves under a known ``addons_path`` dir
        # (raises FileNotFoundError if missing), then build from the trusted path.
        path = file_path(path, filter_ext)
        return cls._from_trusted_path(path, public=public)

    @classmethod
    def _from_trusted_path(cls, path: str, public: bool = False) -> Stream:
        """Build a ``type='path'`` :class:`~Stream` from an absolute path the
        caller has ALREADY validated as under the addons tree (e.g. via
        :func:`~odoo.tools.file_path` or :meth:`Application.get_static_file`).

        Skips re-running that resolution (the biggest per-request static cost) but
        still stats the file for etag/mtime/size. ``stat()`` runs first so a
        vanished file surfaces as an ``OSError`` (404 in
        :meth:`Request._serve_static`), not a misleading ``ValueError``.
        """
        p = Path(path)
        st = p.stat()  # FileNotFoundError (OSError) if the file vanished
        if not S_ISREG(st.st_mode):
            # A directory (or socket/fifo/device) is not streamable. Raise an
            # OSError (not ``ValueError``) so callers mapping OSError → 404
            # (:meth:`Request._serve_static`) degrade gracefully; a ``ValueError``
            # would turn a directory-URL probe (``/web/static/src``) into a 500.
            msg = f"Path {path!r} is not a regular file"
            if S_ISDIR(st.st_mode):
                raise IsADirectoryError(msg)
            raise OSError(msg)
        check = adler32(path.encode())
        # ``st_mtime_ns`` (not ``int(st_mtime)``) so a same-second rewrite of
        # same-length content still busts the cache. The size+adler32(path) suffix
        # preserves the original collision resistance.
        return cls(
            type="path",
            path=path,
            mimetype=mimetypes.guess_type(path)[0],
            download_name=p.name,
            etag=f"{st.st_mtime_ns}-{st.st_size}-{check}",
            last_modified=st.st_mtime,
            size=st.st_size,
            public=public,
        )

    @classmethod
    def from_binary_field(cls, record: Any, field_name: str) -> Stream:
        """Create a :class:`~Stream` from a binary field."""
        data = record[field_name] or b""

        # Image fields enforce base64 encoding. Binary fields don't enforce
        # anything: raw bytes are fine, expected even. People nonetheless write
        # base64-encoded bytes inside binary fields and expect automatic
        # decoding when read, crazy! So attempt to decode and fall back to the
        # raw bytes if it isn't valid base64.
        with contextlib.suppress(ValueError):
            data = base64.b64decode(
                # Some libs add a linefeed every X (< 79) chars in the base64
                # (email mime). validate=True rejects those, so strip them.
                data.replace(b"\r", b"").replace(b"\n", b""),
                validate=True,
            )
        return cls(
            type="data",
            data=data,
            etag=request.env["ir.attachment"]._content_checksum(data),
            last_modified=record.write_date if record._log_access else None,
            size=len(data),
            public=record.env.user._is_public(),  # good enough
        )

    def read(self) -> bytes:
        """Get the stream content as bytes.

        Mirrors :meth:`get_response`'s validation so the ``-> bytes`` contract
        holds: a stream with its backing attribute unset raises ``ValueError``
        instead of returning ``None``.
        """
        if self.type == "url":
            msg = "Cannot read an URL"
            raise ValueError(msg)

        if self.type == "data":
            if self.data is None:
                msg = "There is nothing to stream, missing 'data' attribute."
                raise ValueError(msg)
            return self.data

        if self.type == "path":
            with Path(self.path).open("rb") as file:
                return file.read()

        msg = f"Invalid type: {self.type!r}, should be 'url', 'data' or 'path'."
        raise ValueError(msg)

    def get_response(
        self,
        as_attachment: bool | None = None,
        immutable: bool | None = None,
        content_security_policy: str | None = "default-src 'none'",
        **send_file_kwargs: Any,
    ) -> Any:
        """
        Create the corresponding :class:`~Response` for the current stream.

        :param bool|None as_attachment: Indicate to the browser that it
            should offer to save the file instead of displaying it.
        :param bool|None immutable: Add the ``immutable`` directive to
            the ``Cache-Control`` response header, allowing intermediary
            proxies to aggressively cache the response. This option also
            sets the ``max-age`` directive to 1 year.
        :param str|None content_security_policy: Optional value for the
            ``Content-Security-Policy`` (CSP) header. This header is
            used by browsers to allow/restrict the downloaded resource
            to itself perform new http requests. By default CSP is set
            to ``"default-src 'none'"`` which restricts all requests.
        :param send_file_kwargs: Other keyword arguments to send to
            :func:`werkzeug.utils.send_file` instead of the stream
            sensitive values. Discouraged.
        """
        from .wrappers import Response  # lazy: avoids a stream<->wrappers import edge

        if self.type not in ("url", "data", "path"):
            e = f"Invalid type: {self.type!r}, should be 'url', 'data' or 'path'."
            raise ValueError(e)
        if getattr(self, self.type) is None:
            e = f"There is nothing to stream, missing {self.type!r} attribute."
            raise ValueError(e)

        if self.type == "url":
            if self.max_age is not None:
                res = request.redirect(self.url, code=302, local=False)
                res.headers["Cache-Control"] = f"max-age={self.max_age}"
                return res
            return request.redirect(self.url, code=301, local=False)

        if as_attachment is None:
            as_attachment = self.as_attachment
        if immutable is None:
            immutable = self.immutable

        send_file_kwargs = {
            "mimetype": self.mimetype,
            "as_attachment": as_attachment,
            "download_name": self.download_name,
            "conditional": self.conditional,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "max_age": STATIC_CACHE_LONG if immutable else self.max_age,
            "environ": request.httprequest.environ,
            "response_class": Response,
            **send_file_kwargs,
        }

        if self.type == "data":
            res = _send_file(BytesIO(self.data), **send_file_kwargs)
        else:  # self.type == 'path'
            send_file_kwargs["use_x_sendfile"] = False
            x_accel_redirect: str | None = None
            if config["x_sendfile"]:
                with contextlib.suppress(ValueError):  # outside of the filestore
                    fspath = Path(self.path).relative_to(
                        Path(config["data_dir"]) / "filestore"
                    )
                    x_accel_redirect = f"/web/filestore/{fspath}"
                    send_file_kwargs["use_x_sendfile"] = True

            res = _send_file(self.path, **send_file_kwargs)
            if "X-Sendfile" in res.headers and x_accel_redirect is not None:
                res.headers["X-Accel-Redirect"] = x_accel_redirect

                # In case of X-Sendfile/X-Accel-Redirect, the body is empty,
                # yet werkzeug gives the length of the file. This makes
                # NGINX wait for content that'll never arrive.
                res.headers["Content-Length"] = "0"

        # ``res.headers`` / ``res.cache_control`` rebuild a proxy facade on every
        # access; hoist them so this tail mutates one facade, not one per write.
        headers = res.headers
        headers["X-Content-Type-Options"] = "nosniff"

        if content_security_policy:  # see also Application.set_csp()
            headers["Content-Security-Policy"] = content_security_policy

        cache_control = res.cache_control
        if self.public:
            if (cache_control.max_age or 0) > 0:
                cache_control.public = True
        else:
            cache_control.pop("public", "")
            cache_control.private = True
        if immutable:
            cache_control["immutable"] = None  # None sets the directive

        return res
