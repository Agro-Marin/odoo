import base64
import contextlib
import mimetypes
from datetime import datetime
from io import BytesIO
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Any
from zlib import adler32

from werkzeug.utils import send_file as _send_file

from odoo.tools import config, file_path

from .constants import STATIC_CACHE_LONG
from .core import request
from .wrappers import Response, _Response


class Stream:
    type: str = ""
    data: bytes | None = None
    path: str | None = None
    url: str | None = None

    mimetype: str | None = None
    as_attachment: bool = False
    download_name: str | None = None
    conditional: bool = True
    etag: bool | str = True
    last_modified: float | datetime | None = None
    max_age: int | None = None
    immutable: bool = False
    size: int | None = None
    public: bool = False

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
        path = file_path(path, filter_ext)
        return cls._from_trusted_path(path, public=public)

    @classmethod
    def _from_trusted_path(cls, path: str, public: bool = False) -> Stream:
        p = Path(path)
        st = p.stat()
        if not S_ISREG(st.st_mode):
            msg = f"Path {path!r} is not a regular file"
            if S_ISDIR(st.st_mode):
                raise IsADirectoryError(msg)
            raise OSError(msg)
        check = adler32(path.encode())
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
        data = record[field_name] or b""
        if isinstance(data, str):
            data = data.encode()

        with contextlib.suppress(ValueError):
            data = base64.b64decode(
                data.replace(b"\r", b"").replace(b"\n", b""),
                validate=True,
            )
        return cls(
            type="data",
            data=data,
            etag=record.env["ir.attachment"]._get_content_checksum(data),
            last_modified=record.write_date if record._log_access else None,
            size=len(data),
            public=record.env.user._is_public(),
        )

    def _payload(self, attr: str) -> Any:
        value = getattr(self, attr)
        if value is None:
            e = f"There is nothing to stream, missing {attr!r} attribute."
            raise ValueError(e)
        return value

    def _check_type(self) -> None:
        if self.type not in ("url", "data", "path"):
            e = f"Invalid type: {self.type!r}, should be 'url', 'data' or 'path'."
            raise ValueError(e)

    def read(self) -> bytes:
        if self.type == "url":
            msg = "Cannot read an URL"
            raise ValueError(msg)

        self._check_type()

        if self.type == "data":
            return self._payload("data")

        return Path(self._payload("path")).read_bytes()

    def _get_url_redirect(self) -> Any:
        url = self._payload("url")
        if self.max_age is not None:
            res = request.redirect(url, code=302, local=False)
            res.headers["Cache-Control"] = f"max-age={self.max_age}"
            return res
        return request.redirect(url, code=301, local=False)

    def _send_path(self, send_file_kwargs: dict[str, Any]) -> Any:
        path = self._payload("path")
        send_file_kwargs["use_x_sendfile"] = False
        x_accel_redirect: str | None = None
        if config["x_sendfile"]:
            with contextlib.suppress(ValueError):
                fspath = Path(path).relative_to(Path(config["data_dir"]) / "filestore")
                x_accel_redirect = f"/web/filestore/{fspath}"
                send_file_kwargs["use_x_sendfile"] = True

        res = _send_file(path, **send_file_kwargs)
        if "X-Sendfile" in res.headers and x_accel_redirect is not None:
            res.headers["X-Accel-Redirect"] = x_accel_redirect
            res.headers.pop("X-Sendfile", None)
            res.headers["Content-Length"] = "0"
        return res

    def get_response(
        self,
        as_attachment: bool | None = None,
        immutable: bool | None = None,
        content_security_policy: str | None = "default-src 'none'",
        environ: dict[str, Any] | None = None,
        **send_file_kwargs: Any,
    ) -> Any:
        self._check_type()

        if self.type == "url":
            return self._get_url_redirect()

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
            "environ": request.httprequest.environ if environ is None else environ,
            "response_class": _Response,
            **send_file_kwargs,
        }

        if self.type == "data":
            res = _send_file(BytesIO(self._payload("data")), **send_file_kwargs)
        else:
            res = self._send_path(send_file_kwargs)

        headers = res.headers
        headers["X-Content-Type-Options"] = "nosniff"

        if content_security_policy:
            headers["Content-Security-Policy"] = content_security_policy

        cache_control = res.cache_control
        if self.public:
            if (cache_control.max_age or 0) > 0:
                cache_control.public = True
        else:
            cache_control.pop("public", "")
            cache_control.private = True
        if immutable:
            cache_control["immutable"] = None

        return Response(res)
