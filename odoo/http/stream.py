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

    def read(self) -> bytes:
        if self.type == "url":
            msg = "Cannot read an URL"
            raise ValueError(msg)

        if self.type == "data":
            if self.data is None:
                msg = "There is nothing to stream, missing 'data' attribute."
                raise ValueError(msg)
            return self.data

        if self.type == "path":
            if self.path is None:
                msg = "There is nothing to stream, missing 'path' attribute."
                raise ValueError(msg)
            return Path(self.path).read_bytes()

        msg = f"Invalid type: {self.type!r}, should be 'url', 'data' or 'path'."
        raise ValueError(msg)

    def get_response(
        self,
        as_attachment: bool | None = None,
        immutable: bool | None = None,
        content_security_policy: str | None = "default-src 'none'",
        **send_file_kwargs: Any,
    ) -> Any:
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
            "response_class": _Response,
            **send_file_kwargs,
        }

        if self.type == "data":
            res = _send_file(BytesIO(self.data), **send_file_kwargs)
        else:
            send_file_kwargs["use_x_sendfile"] = False
            x_accel_redirect: str | None = None
            if config["x_sendfile"]:
                with contextlib.suppress(ValueError):
                    fspath = Path(self.path).relative_to(
                        Path(config["data_dir"]) / "filestore"
                    )
                    x_accel_redirect = f"/web/filestore/{fspath}"
                    send_file_kwargs["use_x_sendfile"] = True

            res = _send_file(self.path, **send_file_kwargs)
            if "X-Sendfile" in res.headers and x_accel_redirect is not None:
                res.headers["X-Accel-Redirect"] = x_accel_redirect
                res.headers.pop("X-Sendfile", None)

                res.headers["Content-Length"] = "0"

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
