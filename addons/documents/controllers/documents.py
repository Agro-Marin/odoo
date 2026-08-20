import base64
import io
import json
import logging
import pathlib
import zipfile
from collections import defaultdict
from contextlib import ExitStack
from http import HTTPStatus
from typing import Any, NamedTuple
from urllib.parse import quote, urlparse

from werkzeug.exceptions import BadRequest, Forbidden, RequestEntityTooLarge

from odoo import SUPERUSER_ID, Command, _, fields, http
from odoo.exceptions import MissingError
from odoo.fields import Domain
from odoo.http import content_disposition, request
from odoo.tools import SQL, consteq, replace_exceptions, str2bool
from odoo.tools.image import base64_to_image
from odoo.tools.urls import keep_query

from odoo.addons.documents.tools import (
    UserFolder,
    is_mimetype_textual,
)
from odoo.addons.mail.controllers.attachment import AttachmentController

logger = logging.getLogger(__name__)

# Schemes a URL document may redirect to. Author-controlled URLs are served to
# anyone holding a share link, so dangerous schemes (javascript:, data:,
# vbscript:) must never be emitted as a redirect target.
_SAFE_REDIRECT_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "mailto"})


def _is_safe_redirect_url(url: str) -> bool:
    """Return whether ``url`` is safe to use as a redirect target.

    A schemeless URL (``example.com/x`` or protocol-relative ``//host``) is
    resolved by the browser against the current origin and is fine; only an
    explicit dangerous scheme is rejected.
    """
    if not url:
        return False
    scheme = urlparse(url).scheme.lower()
    return not scheme or scheme in _SAFE_REDIRECT_SCHEMES


#: How much of a file is held in memory at once while streaming it into a zip.
_ZIP_READ_BLOCK = 256 * 1024


class ZipEntry(NamedTuple):
    """One planned archive entry: where it goes, and what to put there.

    ``document`` is the record the entry was resolved from -- the shortcut, not
    its target, since the audit answers "what did this user take away", and the
    shortcut is what they reached. It is what lets :meth:`ShareRoute._make_zip`
    record the whole archive, descendants included, without walking twice.
    """

    path: str
    stream: Any | None  # None marks a directory entry
    document: Any = None
    # Set for content Odoo can read but does not serve itself: a remote keyed
    # store hands back a redirect, so the bytes have to be fetched rather than
    # streamed from a path. The callable is resolved during the plan pass and
    # must not touch the ORM -- see :meth:`_stream_zip`.
    reader: Any = None


class _ZipSink:
    """Write-only sink handing whatever ``zipfile`` produces to the generator.

    Deliberately without ``seek``/``tell``: that is how ``zipfile`` is told the
    output is not seekable, so it emits data descriptors instead of rewinding to
    patch local headers, and the archive can be produced strictly forwards.
    """

    __slots__ = ("_chunks",)

    def __init__(self) -> None:
        self._chunks = []

    def write(self, data: bytes) -> int:
        self._chunks.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        """No-op: the generator drains this sink between writes."""

    def take(self) -> bytes:
        """Return everything written since the last call, and forget it."""
        chunks, self._chunks = self._chunks, []
        return b"".join(chunks)


def _read_stream_blocks(stream: Any, reader: Any = None) -> Any:
    """Yield an ``odoo.http.Stream``'s content in bounded blocks.

    Filestore-backed content is read from disk a block at a time; content held
    in the database is already in memory and is handed over as-is. A *reader*
    supersedes the stream: remotely-keyed content has no local path and its
    stream is a redirect, so the bytes come from the detached fetcher the plan
    pass resolved.
    """
    if reader is not None:
        yield from reader(_ZIP_READ_BLOCK)
        return
    if stream.type == "path":
        with open(stream.path, "rb") as source:  # noqa: PTH123 — plain fs path
            while block := source.read(_ZIP_READ_BLOCK):
                yield block
    else:
        content = stream.read()
        for offset in range(0, len(content), _ZIP_READ_BLOCK):
            yield content[offset : offset + _ZIP_READ_BLOCK]


def _sanitize_zip_name(name: str) -> str:
    """Return a single, safe zip entry component out of a document/file name.

    Only ``/`` was previously stripped, so ``..`` components and Windows ``\\``
    separators survived into archive entry names. Python's own ``extractall``
    drops ``..``, but many extractors (``unzip``, GUI tools, naive code) follow
    the relative path and traverse out of the target directory (zip-slip). Here
    both separators are neutralized and a bare ``.``/``..`` component is replaced.
    """
    name = (name or "").replace("/", "_").replace("\\", "_")
    if name in (".", ".."):
        name = "_" * len(name)
    return name


class ShareRoute(http.Controller):
    """Handle public and portal sharing, download and upload of documents."""

    TEXTUAL_THUMBNAIL_SIZE = 4096
    # Guardrails for the in-memory zip builder (``_make_zip``). Both are
    # overridable through ``ir.config_parameter`` so an administrator can raise
    # them for legitimately large folder shares. They bound the RAM a single
    # request (including an *unauthenticated* public folder-share link) can make
    # the worker allocate.
    ZIP_MAX_FILE_COUNT = 10000
    ZIP_MAX_TOTAL_SIZE = 1024 * 1024 * 1024  # 1 GiB of uncompressed content

    # util methods #################################################################################
    def _max_content_length(self) -> int:
        return request.env["documents.document"].get_document_max_upload_limit()

    @classmethod
    def _is_shortcut_target_reachable(cls, document_sudo: Any) -> bool:
        """Return whether the shortcut target of ``document_sudo`` may be served.

        Mirrors the shortcut check of :meth:`_from_access_token` for recordsets
        that were obtained in ``sudo`` (where dereferencing
        ``shortcut_document_id`` performs no access check at all). A document
        that is not a shortcut is always reachable -- it was selected by a
        domain that already accounts for its own permissions.
        """
        target_sudo = document_sudo.shortcut_document_id
        if not target_sudo:
            return True
        if request.env.user._is_public():
            return (
                target_sudo.access_via_link in ("view", "edit")
                and not target_sudo.is_access_via_link_hidden
            )
        return target_sudo.user_permission != "none"

    @classmethod
    def _folder_children_domain(cls) -> Any:
        """Visibility domain for the *children* of a shared folder.

        Folder-independent (it only constrains the child records), so it can be
        reused to fetch the children of many folders in a single search.
        """
        # A shortcut must never widen access: the search is done in sudo, so
        # the permission clauses below only constrain the *shortcut* record.
        # Without this, a shortcut placed in a shared folder exposes its
        # (otherwise inaccessible) target -- notably through ``_make_zip``.
        # Every caller reaches `folder_sudo` through `_from_access_token`, i.e.
        # through its share link, so link-granted visibility always applies here.
        # Keying these filters on `_is_public()` alone meant a *logged-in*
        # visitor following the very same link was judged only by their own
        # permissions -- typically none, for an external collaborator -- so the
        # shared folder came back empty for them while anonymous visitors got
        # the right contents.
        link_target_domain = Domain("access_via_link", "in", ("view", "edit")) & Domain(
            "is_access_via_link_hidden", "=", False
        )
        if not request.env.user._is_public():
            link_target_domain |= Domain("user_permission", "!=", "none")
        reachable_target_domain = Domain(
            "shortcut_document_id", "any", link_target_domain
        )
        shortcut_domain = Domain("shortcut_document_id", "=", False) | (
            reachable_target_domain
        )

        # What the share link itself grants: the same set an anonymous visitor
        # following this link would see.
        permission_domain = Domain.AND(
            [
                [("is_access_via_link_hidden", "=", False)],
                [("access_via_link", "in", ("edit", "view"))],
                # a link alone cannot open an unfulfilled request, unless
                # access_via_link='edit'
                Domain.OR(
                    [
                        [("access_via_link", "=", "edit")],
                        [("type", "!=", "binary")],
                        Domain.OR(
                            [
                                [("attachment_id", "!=", False)],
                                [
                                    (
                                        "shortcut_document_id.attachment_id",
                                        "!=",
                                        False,
                                    )
                                ],
                            ]
                        ),
                    ]
                ),
            ]
        )
        if not request.env.user._is_public():
            # An identified visitor sees at least what the link grants, plus
            # whatever their own permissions add.
            permission_domain |= Domain(
                "user_permission", "!=", "none"
            )  # needed for search in sudo

        return permission_domain & shortcut_domain

    @classmethod
    def _get_folder_children(cls, folder_sudo: Any) -> Any:
        return (
            request.env["documents.document"]
            .sudo()
            .search(
                Domain("folder_id", "=", folder_sudo.id)
                & cls._folder_children_domain(),
                order="name",
            )
        )

    @classmethod
    def _get_folders_children(cls, folders_sudo: Any) -> dict:
        """Children of several folders in one search, grouped by folder id.

        The public folder view renders one subfolder-listing per subfolder; done
        one ``_get_folder_children`` at a time that is ``1 + S`` searches (each
        with the non-trivial permission domain) on an anonymous route. Fetch them
        all at once and group in Python instead.
        """
        empty = request.env["documents.document"].sudo()
        result = dict.fromkeys(folders_sudo.ids, empty)
        if not folders_sudo:
            return result
        children = empty.search(
            Domain("folder_id", "in", folders_sudo.ids) & cls._folder_children_domain(),
            order="name",
        )
        for folder, folder_children in children.grouped(
            lambda child: child.folder_id.id
        ).items():
            result[folder] = folder_children
        return result

    @staticmethod
    def _split_access_token(access_token: str) -> tuple[str, int]:
        """Split an ``access_token`` into its secret and the document id.

        The token is ``<document_token>o<id in hex>``. Splitting on the LAST
        ``o`` is what makes that unambiguous: the id is hexadecimal, so it never
        contains an ``o``, while the base64url secret may.

        :return: ``(document_token, document_id)``, or ``("", 0)`` when the
            token is malformed -- which every caller must treat as "no such
            document" rather than as a bad request, since the value is a public,
            attacker-controlled path segment.
        """
        try:
            document_token, __, encoded_id = (access_token or "").rpartition("o")
            document_id = int(encoded_id, 16)
        except ValueError:
            return "", 0
        if not document_token or document_id < 1:
            return "", 0
        return document_token, document_id

    @classmethod
    def _from_access_token(
        cls, access_token: str, *, skip_log: bool = False, follow_shortcut: bool = True
    ) -> Any:
        """Get existing document with matching ``access_token``.

        It returns an empty recordset when either:
        * the document is not found ;
        * the user cannot already access the document and the link
          doesn't grant access ;
        * the matching document is a shortcut but it is not allowed to
          follow the shortcut.
        Otherwise it returns the matching document in sudo.

        A ``documents.access`` record is created/updated with the
        current date unless the ``skip_log`` flag is set.

        :param str access_token: the access token to the document record
        :param bool skip_log: flag to prevent updating the record last
            access date of internal users, useful to prevent silly
            serialization errors, best used with read-only controllers.
        :param bool follow_shortcut: flag to prevent returning the target
            from a shortcut and instead return the shortcut itself.
        """
        Doc = request.env["documents.document"]

        # Document record
        document_token, document_id = cls._split_access_token(access_token)
        if not document_id:
            return Doc
        document_sudo = Doc.browse(document_id).sudo()
        try:
            if not document_sudo.document_token:  # like exists() but prefetch
                return Doc
        except MissingError:
            return Doc

        # Permissions
        if not (
            # `consteq` is `hmac.compare_digest`, which raises TypeError on a
            # `str` holding non-ASCII. `document_token` is the raw, public,
            # attacker-controlled path segment, so without this guard any
            # non-ASCII token turned every public documents route into an
            # unauthenticated HTTP 500 (a free traceback-log flooder). A real
            # token is base64url, so non-ASCII simply never matches.
            document_token.isascii()
            and consteq(document_token, document_sudo.document_token)
            and (
                document_sudo.user_permission != "none"
                or document_sudo.access_via_link != "none"
            )
        ):
            return Doc
        if not request.env.user._is_internal() and not document_sudo.active:
            return Doc

        # Document access
        skip_log = skip_log or request.env.user._is_public()
        if not skip_log:
            for doc_sudo in filter(
                bool, (document_sudo, document_sudo.shortcut_document_id)
            ):
                new_access = cls._upsert_last_access_date(request.env, doc_sudo)
                if new_access and doc_sudo._get_permission_without_token() == "none":
                    # Used to trigger webclient reload
                    document_sudo = document_sudo.with_context(
                        document_newly_accessible=True
                    )

        # Shortcut
        if follow_shortcut:
            if target_sudo := document_sudo.shortcut_document_id:
                if target_sudo.user_permission != "none" or (
                    target_sudo.access_via_link != "none"
                    and not target_sudo.is_access_via_link_hidden
                ):
                    document_sudo = target_sudo
                else:
                    document_sudo = Doc

        # Extra validation step, to run with the target
        if (
            request.env.user._is_public()
            and document_sudo.type == "binary"
            and not document_sudo.attachment_id
            and document_sudo.access_via_link != "edit"
        ):
            # public cannot access a document request, unless access_via_link='edit'
            return Doc

        return document_sudo

    @classmethod
    def _upsert_last_access_date(cls, env: Any, document: Any) -> bool:
        """Set or update last_access_date to now() for env user, WITHOUT ACCESS RIGHT CHECK.

        :return: True if a new documents.access record was created
        """
        # Atomic upsert. A search-then-create was racy: two concurrent first
        # accesses by the same user on the same document both saw no row and both
        # inserted, and the second hit the `unique(document_id, partner_id)`
        # constraint -- not a serialization error, so no ORM retry, just a
        # poisoned 500 on a hot path (documents_touch / documents_home). Let
        # Postgres arbitrate instead. `xmax = 0` is true only for the freshly
        # inserted row, so it tells us whether this call created the access.
        env.cr.execute(
            SQL(
                """
                INSERT INTO documents_access (document_id, partner_id, last_access_date)
                     VALUES (%(document_id)s, %(partner_id)s, %(now)s)
                ON CONFLICT (document_id, partner_id)
                  DO UPDATE SET last_access_date = EXCLUDED.last_access_date
                  RETURNING (xmax = 0) AS inserted
                """,
                document_id=document.id,
                partner_id=env.user.partner_id.id,
                now=fields.Datetime.now(),
            )
        )
        created = env.cr.fetchone()[0]
        # The raw write bypassed the ORM cache; drop the stale access relations.
        env["documents.access"].invalidate_model(["last_access_date"])
        document.invalidate_recordset(["access_ids"])
        # `last_access_date` above is overwritten by the next visit; the log
        # keeps the history it discards.
        env["documents.access.log"]._log(document, env.user.partner_id, "view")
        return created

    def _make_zip(self, name: str, documents: Any) -> Any:
        """Stream a zip of ``documents``, recursing into folders.

        Built in two passes. The first walks the tree and resolves every entry
        to its archive path and content stream; the second turns that plan into
        zip bytes as the client reads them.

        The split is not cosmetic:

        * **Nothing is buffered.** The whole archive used to be assembled in a
          ``BytesIO`` and handed over in one piece, so an unauthenticated public
          folder share sized the worker's memory. Peak memory is now one
          compression buffer, whatever the archive weighs.
        * **The caps can still answer 413.** Once the first byte is on the wire
          the status is settled, so a limit discovered mid-archive could only
          truncate the download. The plan pass knows every entry's size before
          anything is sent -- ``Stream.size`` is set for filestore- and
          database-backed content alike -- so the refusal stays a clean 413.
        * **The generator never touches the ORM.** It runs after the controller
          returns, when the cursor is gone; all record access belongs to the
          plan pass, which hands it plain paths and bytes.

        :param str name: the name to give to the zip file
        :param odoo.models.Model documents: documents to load in the ZIP
        :return: a http response streaming the zip file
        """
        entries = self._plan_zip_entries(name, documents)
        # Every route that builds an archive records it, and it records what the
        # archive actually holds -- the files discovered by the walk, not just
        # the roots the caller named. `/documents/zip` (what the web client uses
        # for any multi-document download) recorded nothing at all, so the access
        # log answered "who took this file" for single downloads and stayed
        # silent for every bulk one.
        self._log_download(
            request.env["documents.document"]
            .sudo()
            .browse({entry.document.id for entry in entries if entry.document})
        )
        headers = [
            ("Content-Type", "application/zip"),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Disposition", content_disposition(name)),
        ]
        return request.make_response(self._stream_zip(name, entries), headers)

    def _plan_zip_entries(self, name: str, documents: Any) -> list:
        """Resolve ``documents`` to the archive's entries, enforcing the caps.

        :return: list of ``ZipEntry``; ``stream`` is None for a directory entry.
        """
        seen_folders = set()  # because of shortcuts, we can have loops
        # many documents can have the same name
        seen_names = defaultdict(int)

        get_param = request.env["ir.config_parameter"].sudo().get_param
        max_files = int(
            get_param("documents.zip_max_file_count", self.ZIP_MAX_FILE_COUNT)
        )
        max_total = int(
            get_param("documents.zip_max_total_size", self.ZIP_MAX_TOTAL_SIZE)
        )
        counters = {"files": 0, "total": 0}

        def account(size: int) -> None:
            # Enforced against the RUNNING totals, while planning -- before the
            # response has begun and while a 413 is still expressible. They no
            # longer bound memory (the archive is streamed); they bound how much
            # work one request, including an unauthenticated public folder
            # share, can ask of a worker.
            counters["files"] += 1
            counters["total"] += size
            if counters["files"] > max_files or counters["total"] > max_total:
                logger.warning(
                    "Refusing to build an oversized zip (%s files, %s bytes) for %r",
                    counters["files"],
                    counters["total"],
                    name,
                )
                raise RequestEntityTooLarge

        def unique(pathname: str) -> str:
            # files inside a zip can not have the same name
            # (files in the documents application can)
            seen_names[pathname] += 1
            if seen_names[pathname] <= 1:
                return pathname

            ext = "".join(pathlib.Path(pathname).suffixes)
            return f"{pathname.removesuffix(ext)}-{seen_names[pathname]}{ext}"

        def make_zip_item(document: Any, folder: Any) -> Any:
            if document.type == "url":
                raise ValueError("cannot create a zip item out of an url")
            # ``documents`` is a sudo recordset, so following
            # ``shortcut_document_id`` below would bypass every access check.
            # ``_get_folder_children`` already filters these out; this is the
            # last line of defence for any other entry point.
            if not self._is_shortcut_target_reachable(document):
                return None  # skip
            # Every entry, at every depth, passes through here -- so this is
            # where "viewers may not download this" is applied. Filtering at the
            # call sites instead would have covered the documents handed in and
            # missed everything the walk below discovers.
            if not document._is_download_allowed():
                return None  # skip
            if document.type == "folder":
                document_name = _sanitize_zip_name(document.name)
                # it is the ending slash that makes it appears as a
                # folder inside the zip file.
                return ZipEntry(
                    unique(f"{folder.path}{document_name}") + "/", None, document
                )
            try:
                stream = self._documents_content_stream(
                    document.shortcut_document_id or document
                )
                download_name = _sanitize_zip_name(stream.download_name)
            except ValueError, MissingError:
                return None  # skip
            if stream.type == "url":
                # A url stream covers two different things. Content Odoo merely
                # points at (a `cloud_storage` row, any binary attachment
                # carrying a url) has no bytes to archive and `Stream.read`
                # refuses it -- skipping is the only option, and this pass is the
                # last point where it is expressible, since the streaming pass
                # runs after the 200 is on the wire. Content held in a remote
                # KEYED store is different: Odoo can read it, it just does not
                # serve it, so it belongs in the archive and is fetched through
                # the detached reader below.
                source = (document.shortcut_document_id or document).attachment_id
                reader = source.sudo()._zip_detached_reader()
                if reader is None:
                    return None  # skip
                account(source.file_size or 0)
                return ZipEntry(
                    unique(f"{folder.path}{download_name}"), stream, document, reader
                )
            # The declared size, never the content: this pass must not read a
            # single file, both to keep the plan cheap and because reading is
            # what the streaming pass is for.
            account(stream.size or 0)
            return ZipEntry(unique(f"{folder.path}{download_name}"), stream, document)

        def generate_zip_items(documents_sudo: Any, folder: Any) -> Any:
            documents_sudo = documents_sudo.sorted(lambda d: d.id)

            yield from (
                item
                for doc in documents_sudo
                if doc.type == "binary"
                and (doc.shortcut_document_id or doc).attachment_id
                if (item := make_zip_item(doc, folder)) is not None
            )
            for folder_sudo in documents_sudo:
                if folder_sudo.type != "folder":
                    continue
                # Children hang off the TARGET, never off the shortcut, so
                # recursing on the shortcut found nothing and the archive
                # carried the folder as an empty directory -- silently, with
                # HTTP 200. A shortcut to a *file* has always been resolved
                # (`make_zip_item` below streams the target); this is the same
                # promise for folders. `_get_folder_children` re-applies the
                # visibility domain to whatever it lists, so resolving here
                # cannot widen what the link grants.
                source_sudo = folder_sudo.shortcut_document_id or folder_sudo

                if (sub_folder := make_zip_item(folder_sudo, folder)) is None:
                    continue  # unreachable shortcut target
                yield sub_folder
                # The guard skips the WALK, never the entry above: several
                # shortcuts to one folder each deserve their own directory in
                # the archive, and only the first carries the contents. Keyed on
                # the resolved folder, because a cycle closed through a shortcut
                # (A holds a shortcut to B, B one back to A) is only visible once
                # both sides resolve to the same record. Global rather than
                # per-branch so the walk stays bounded by the number of folders.
                if source_sudo in seen_folders:
                    continue
                seen_folders.add(source_sudo)
                # One recursion for the whole level, not one per child: a
                # single-record call made `sorted()` and the files-then-folders
                # split above vacuous, and issued one `_get_folder_children`
                # search per child.
                yield from generate_zip_items(
                    self._get_folder_children(source_sudo), sub_folder
                )

        return list(generate_zip_items(documents, ZipEntry("", None)))

    def _stream_zip(self, name: str, entries: list) -> Any:
        """Yield the archive for ``entries`` as it is produced.

        Runs after the controller has returned, so it must stay clear of the
        ORM: every entry already carries the resolved path or bytes it needs.
        """
        sink = _ZipSink()
        try:
            # No `tell` on the sink, so zipfile writes data descriptors instead
            # of seeking back to patch local headers -- which is what makes a
            # zip streamable at all.
            with zipfile.ZipFile(
                sink, "w", compression=zipfile.ZIP_DEFLATED
            ) as doc_zip:
                for entry in entries:
                    if entry.stream is None:  # a directory entry
                        doc_zip.writestr(entry.path, b"")
                        if chunk := sink.take():
                            yield chunk
                        continue
                    with doc_zip.open(entry.path, "w") as destination:
                        for block in _read_stream_blocks(entry.stream, entry.reader):
                            destination.write(block)
                            # Hand each compressed block out as it appears
                            # rather than accumulating the archive.
                            if chunk := sink.take():
                                yield chunk
                    if chunk := sink.take():
                        yield chunk
        except zipfile.BadZipfile:
            # The response has already started, so this cannot become an error
            # status; log it loudly and let the truncated body fail the client's
            # unzip rather than pass for a complete archive.
            logger.exception("BadZipfile exception while building %r", name)
            raise
        if chunk := sink.take():  # central directory
            yield chunk

    @staticmethod
    def _parse_pdf_split_new_files(new_files: Any) -> list:
        """Validate the client's ``new_files`` structure, once, at the boundary.

        The route used to traverse this untrusted payload inline in three
        separate loops, indexing keys straight out of it. Anything that parsed
        as JSON but did not have the exact expected shape -- a missing
        ``new_pages``, a page without ``old_file_type``, a non-numeric index --
        surfaced as a ``KeyError``/``TypeError`` and an HTTP 500. Normalizing
        here means every downstream consumer works on a known shape, and the
        caller maps the ``ValueError`` raised below to a clean 400.

        :return: ``new_files`` with page indices coerced to ``int``.
        """
        if not isinstance(new_files, list):
            e = "new_files must be a list"
            raise ValueError(e)
        for new_file in new_files:
            if not isinstance(new_file, dict):
                e = "each new file must be an object"
                raise ValueError(e)
            if not isinstance(new_file.get("name"), str):
                e = "each new file needs a name"
                raise ValueError(e)
            pages = new_file.get("new_pages")
            if not isinstance(pages, list):
                e = "new_pages must be a list"
                raise ValueError(e)
            for page in pages:
                if not isinstance(page, dict):
                    e = "each page must be an object"
                    raise ValueError(e)
                if page.get("old_file_type") not in ("document", "file"):
                    e = "old_file_type must be 'document' or 'file'"
                    raise ValueError(e)
                # `int(...)` raises ValueError on anything non-numeric and
                # TypeError on a missing key (``None``); the caller maps both to
                # a 400. Bounds are checked later, against the resolved files.
                page["old_file_index"] = int(page.get("old_file_index"))
                page["old_page_number"] = int(page.get("old_page_number"))
        return new_files

    # Download & upload routes #####################################################################
    @http.route("/documents/pdf_split", type="http", methods=["POST"], auth="user")
    def pdf_split(
        self,
        new_files: str | None = None,
        ufile: Any = None,
        archive: Any = False,
        vals: str | None = None,
    ) -> Any:
        """Split and/or merge pdf documents.

        The data can come from different sources: multiple existing documents
        (at least one must be provided) and any number of extra uploaded files.

        :param new_files: the array that represents the new pdf structure:
            [{
                'name': 'New File Name',
                'new_pages': [{
                    'old_file_type': 'document' or 'file',
                    'old_file_index': document_id or index in ufile,
                    'old_page_number': 5,
                }],
            }]
        :param ufile: extra uploaded files that are not existing documents
        :param archive: whether to archive the original documents
        :param vals: values for the create of the new documents.
        """
        # Client-supplied payloads: malformed JSON (or a missing param) must be a
        # 400, not an uncaught 500 like every other JSON site in this file.
        with replace_exceptions(ValueError, TypeError, by=BadRequest):
            vals = json.loads(vals or "{}")
            new_files = json.loads(new_files or "[]")
            new_files = self._parse_pdf_split_new_files(new_files)
            if not isinstance(vals, dict):
                e = "vals must be an object"
                raise ValueError(e)
        # find original documents
        document_ids = {
            page["old_file_index"]
            for new_file in new_files
            for page in new_file["new_pages"]
            if page["old_file_type"] == "document"
        }
        documents = request.env["documents.document"].browse(document_ids)
        documents.check_access("read")
        # `_get_pdf_raw` is the base primitive for "this row's bytes, if it holds
        # a PDF": it neutralizes `bin_size` and answers None for anything else.
        # The ids are client-supplied like the rest of the payload, and both
        # refusals used to reach PyPDF instead of being answered here -- a
        # document carrying no content (a pending request, a shortcut) as a
        # TypeError, one holding something other than a PDF as a PdfStreamError,
        # which is not a ValueError and so escaped the mapping below as an HTTP
        # 500. It also replaces the `datas` round-trip, which base64-encoded the
        # whole payload out of the filestore only to decode it back here.
        # sudo: read access to a document carries access to its content, the
        # same elevation `datas` grants through `related_sudo`.
        pdf_raws = [
            document.attachment_id.sudo()._get_pdf_raw()
            if document.attachment_id
            else None
            for document in documents
        ]
        if any(pdf_raw is None for pdf_raw in pdf_raws):
            raise BadRequest("cannot split a document that does not hold a PDF")

        with ExitStack() as stack:
            files = request.httprequest.files.getlist("ufile")
            open_files = [
                stack.enter_context(io.BytesIO(file.read())) for file in files
            ]

            # merge together data from existing documents and from extra uploads
            document_id_index_map = {}
            current_index = len(open_files)
            for document, pdf_raw in zip(documents, pdf_raws, strict=True):
                open_files.append(stack.enter_context(io.BytesIO(pdf_raw)))
                document_id_index_map[document.id] = current_index
                current_index += 1

            # update new_files structure with the new indices from documents
            for new_file in new_files:
                for page in new_file["new_pages"]:
                    if page.pop("old_file_type") == "document":
                        page["old_file_index"] = document_id_index_map[
                            page["old_file_index"]
                        ]

            # apply the split/merge (out-of-range client indices -> 400)
            with replace_exceptions(ValueError, by=BadRequest):
                new_documents = documents._pdf_split(
                    new_files=new_files, open_files=open_files, vals=vals
                )

        # archive original documents if needed
        if str2bool(archive, default=False):
            documents.write({"active": False})

        return request.make_response(
            json.dumps(new_documents.ids), [("Content-Type", "application/json")]
        )

    @http.route("/documents/<access_token>", type="http", auth="public")
    def documents_home(
        self,
        access_token: str,
        member_id: str = "",
        member_signup_token: str = "",
    ) -> Any:
        """Serve the shared document home page for the current user type.

        ``member_id``/``member_signup_token`` are the member-invitation pair
        carried by the signup link. They are declared here, rather than read out
        of ``request.params`` in the body: the dispatcher filters a request's
        args down to what the endpoint accepts, so an undeclared parameter is
        dropped with a "called ignoring args" warning on every invitation
        follow-up -- and would be genuinely lost the day the body stopped
        reaching around the signature.
        """
        document_sudo = self._from_access_token(access_token)

        with replace_exceptions(ValueError, by=BadRequest):
            member_id = int(member_id or "0")

        if not document_sudo:
            Redirect = request.env["documents.redirect"].sudo()
            if document_sudo := Redirect._get_redirection(access_token):
                return request.redirect(
                    f"/documents/{quote(document_sudo.access_token, safe='')}?{keep_query('*')}",
                    HTTPStatus.MOVED_PERMANENTLY,
                )

        if request.env.user._is_public():
            if not document_sudo:
                redirect_url = (
                    f"/documents/{quote(access_token, safe='')}?{keep_query('*')}"
                )
                if signup_url := request.env["documents.access"]._get_signup_url(
                    member_id, member_signup_token, access_token, redirect_url
                ):
                    # Document requires a member to access (not "access_via_link")
                    # and we have a signup token -> redirect user to signup
                    return request.redirect(signup_url)
            return self._documents_render_public_view(document_sudo)
        elif request.env.user._is_portal():
            return self._documents_render_portal_view(document_sudo)
        else:  # assume internal user
            # Internal users use the /odoo/documents/<access_token> route
            return request.redirect(
                f"/odoo/documents/{quote(access_token, safe='')}?{keep_query('*')}",
                HTTPStatus.TEMPORARY_REDIRECT,
            )

    def _documents_render_public_view(self, document_sudo: Any) -> Any:
        target_sudo = document_sudo.shortcut_document_id
        if (
            target_sudo
            and target_sudo.access_via_link != "none"
            and not target_sudo.is_access_via_link_hidden
        ):
            return request.redirect(
                f"/odoo/documents/{quote(target_sudo.access_token, safe='')}?{keep_query('*')}"
            )
        if target_sudo or not document_sudo:
            return request.render(
                "documents.not_available", {"document": document_sudo}, status=404
            )
        if document_sudo.type == "url":
            if not _is_safe_redirect_url(document_sudo.url):
                return request.render(
                    "documents.not_available", {"document": document_sudo}, status=404
                )
            return request.redirect(
                document_sudo.url, code=HTTPStatus.TEMPORARY_REDIRECT, local=False
            )
        if document_sudo.type == "binary" and document_sudo.attachment_id:
            return request.render(
                "documents.share_file",
                {"document": document_sudo, "quote": lambda v: quote(v, safe="")},
            )
        if document_sudo.type == "binary":
            return request.render(
                "documents.document_request_page",
                {"document": document_sudo, "quote": lambda v: quote(v, safe="")},
            )
        if document_sudo.type == "folder":
            sub_documents_sudo = ShareRoute._get_folder_children(document_sudo)
            return request.render(
                "documents.public_folder_page",
                {
                    "folder": document_sudo,
                    "documents": sub_documents_sudo,
                    "subfolders": ShareRoute._get_folders_children(
                        sub_documents_sudo.filtered(lambda d: d.type == "folder")
                    ),
                    "quote": lambda v: quote(v, safe=""),
                },
            )
        else:
            e = f"unknown document type {document_sudo.type}"
            raise NotImplementedError(e)

    def _documents_render_portal_view(self, document: Any) -> Any:
        # Render the portal version (stripped version of the backend Documents app).
        # We build the session information necessary for the web client to load
        session_info = request.env["ir.http"].session_info()

        session_info.update(
            user_companies={
                "current_company": request.env.company.id,
                "allowed_companies": {
                    request.env.company.id: {
                        "id": request.env.company.id,
                        "name": request.env.company.name,
                    },
                },
            },
            documents_init=self._documents_get_init_data(document, request.env.user),
        )

        return request.render(
            "documents.document_portal_view",
            {"session_info": session_info},
        )

    @classmethod
    def _documents_get_init_data(cls, document: Any, user: Any) -> dict:
        # Get initialization data to restore the interface on the selected document.
        if not document or not user:
            return {}

        document.ensure_one()
        documents_init = {
            "user_folder_id": document.user_folder_id,
            "document_id": document.id,
        }
        # An archived document keeps the default `documents_init` (it cannot be
        # browsed as a folder). Shortcuts to archived folders behave like binary
        # documents for the same reason.
        if (
            document.active
            and document.type == "folder"
            and (
                not document.shortcut_document_id
                or document.shortcut_document_id.active
            )
        ):
            documents_init = {"user_folder_id": str(document.id)}
        elif document.active:
            target = document.shortcut_document_id or document
            if document.type == "binary" and target.attachment_id:
                documents_init["open_preview"] = True
        return documents_init

    @http.route(
        "/documents/avatar/<access_token>", type="http", auth="public", readonly=True
    )
    def documents_avatar(self, access_token: str) -> Any:
        """Show the avatar of the document's owner, or the avatar placeholder.

        :param access_token: the access token to the document record
        """
        partner_sudo = self._from_access_token(
            access_token, skip_log=True
        ).owner_id.partner_id
        return (
            request.env["ir.binary"]
            ._get_image_stream_from(
                partner_sudo,
                "avatar_128",
                placeholder=partner_sudo._avatar_get_placeholder_path(),
            )
            .get_response(as_attachment=False)
        )

    def _documents_content_readonly(self, rule: Any, args: dict) -> bool:
        """Whether this hit can be served from a read-only cursor.

        Serving an actual download records an audit entry, which is a write; an
        inline preview (``download=false``, what the viewer and the share page
        use) writes nothing and stays read-only.

        Decided here rather than by letting the write happen and relying on the
        dispatcher's read-only retry: that retry re-runs the whole handler, and
        this one serves file content.

        A **folder** token ignores ``download`` entirely -- :meth:`documents_content`
        always builds the zip and always records the download -- so answering
        from the query string alone declared exactly the case that cannot be
        served read-only. On a deployment with a replica that is the retry this
        docstring says was avoided: a `ReadOnlySqlTransaction`, a warning, and the
        whole handler run twice. The type is resolved in sudo off the id embedded
        in the token; failing to resolve it means a read/write cursor, which is
        always safe.
        """
        if str2bool(request.httprequest.args.get("download", "1"), default=True):
            return False
        try:
            __, document_id = self._split_access_token(args.get("access_token") or "")
            if not document_id:
                return True  # no such document: the handler will 404, writing nothing
            document_sudo = (
                request.env["documents.document"]
                .with_user(SUPERUSER_ID)
                .sudo()
                .browse(document_id)
                .exists()
            )
            target_sudo = document_sudo.shortcut_document_id or document_sudo
            return target_sudo.type != "folder"
        except Exception:
            logger.warning(
                "Could not classify %r for read-only serving; using a read/write "
                "cursor",
                args.get("access_token"),
                exc_info=True,
            )
            return False

    @http.route(
        "/documents/content/<access_token>",
        type="http",
        auth="public",
        readonly=_documents_content_readonly,
    )
    def documents_content(self, access_token: str, download: Any = True) -> Any:
        """Serve the file of the document.

        :param access_token: the access token to the document record
        :param download: whether to download the document on the user's
            file system or to preview the document within the browser
        """
        document_sudo = self._from_access_token(access_token, skip_log=True)
        if not document_sudo:
            Redirect = request.env["documents.redirect"].sudo()
            if document_sudo := Redirect._get_redirection(access_token):
                return request.redirect(
                    f"/odoo/documents/{quote(document_sudo.access_token, safe='')}",
                    HTTPStatus.MOVED_PERMANENTLY,
                )
            raise request.not_found()
        if document_sudo.type == "url":
            if not _is_safe_redirect_url(document_sudo.url):
                raise request.not_found()
            return request.redirect(
                document_sudo.url, code=HTTPStatus.TEMPORARY_REDIRECT, local=False
            )
        if document_sudo.type == "folder":
            if not document_sudo._is_download_allowed():
                raise Forbidden("downloading this folder is not allowed")
            self._log_download(document_sudo)
            return self._make_zip(
                f"{document_sudo.name}.zip",
                self._get_folder_children(document_sudo),
            )
        if document_sudo.type == "binary":
            if not document_sudo.attachment_id:
                raise request.not_found()
            with replace_exceptions(ValueError, by=BadRequest):
                download = str2bool(download)
            if download:
                if not document_sudo._is_download_allowed():
                    raise Forbidden("downloading this document is not allowed")
                self._log_download(document_sudo)
            with replace_exceptions(ValueError, MissingError, by=request.not_found()):
                stream = self._documents_content_stream(document_sudo)
            return stream.get_response(as_attachment=download)
        e = f"unknown document type {document_sudo.type!r}"
        raise NotImplementedError(e)

    def _documents_content_stream(self, document_sudo: Any) -> Any:
        return request.env["ir.binary"]._get_stream_from(document_sudo)

    def _log_download(self, document_sudo: Any) -> None:
        """Record that this file left the system, and who took it.

        The only trace a download used to leave was
        ``documents.access.last_access_date``, overwritten by the next visit --
        and not even that here, since this route reads the token with
        ``skip_log=True``. Public visitors are logged too, under the public
        partner: "someone holding the link took this, at this time" is exactly
        what an audit is asking.
        """
        request.env["documents.access.log"].sudo()._log(
            document_sudo, request.env.user.partner_id, "download"
        )

    @http.route(
        "/documents/redirect/<access_token>", type="http", auth="public", readonly=True
    )
    def documents_redirect(self, access_token: str) -> Any:
        """Redirect to the internal Documents web client route."""
        return request.redirect(
            f"/odoo/documents/{quote(access_token, safe='')}",
            HTTPStatus.MOVED_PERMANENTLY,
        )

    @http.route("/documents/touch/<access_token>", type="jsonrpc", auth="user")
    def documents_touch(self, access_token: str) -> dict:
        """Signal a webclient reload when a document becomes newly accessible."""
        doc = self._from_access_token(access_token)
        if doc.env.context.get("document_newly_accessible"):
            return {"reload": True}
        return {}

    @http.route(
        [
            "/documents/thumbnail/<access_token>",
            "/documents/thumbnail/<access_token>/<int:width>x<int:height>",
        ],
        type="http",
        auth="public",
        readonly=True,
    )
    def documents_thumbnail(
        self, access_token: str, width: str = "0", height: str = "0", unique: str = ""
    ) -> Any:
        """Show the thumbnail of the document, or a placeholder.

        :param access_token: the access token to the document record
        :param width: resize the thumbnail to this maximum width
        :param height: resize the thumbnail to this maximum height
        :param unique: force storing the file in the browser cache, best
            used with the checksum of the attachment
        """
        # Client-supplied geometry reaching an image pipeline: validate it at the
        # boundary. Only the *parsing* used to be guarded, so a negative value
        # (reachable through the query string, which the `<int:>` path converter
        # does not constrain) travelled all the way into `image_process`, which
        # rejects it with a bare ValueError -- an unauthenticated HTTP 500, and a
        # free traceback-log flooder on a public route. Oversized values need no
        # cap: resizing never upscales.
        with replace_exceptions(ValueError, by=BadRequest):
            width = int(width)
            height = int(height)
            if width < 0 or height < 0:
                e = "width and height must be positive"
                raise ValueError(e)
        send_file_kwargs = {}
        if unique:
            send_file_kwargs["immutable"] = True
            send_file_kwargs["max_age"] = http.STATIC_CACHE_LONG
        document_sudo = self._from_access_token(access_token, skip_log=True)
        return (
            request.env["ir.binary"]
            ._get_image_stream_from(
                document_sudo, "thumbnail", width=width, height=height
            )
            .get_response(as_attachment=False, **send_file_kwargs)
        )

    @http.route(
        ["/documents/thumbnail_textual/<access_token>"],
        type="http",
        auth="public",
        readonly=True,
    )
    def documents_thumbnail_textual(self, access_token: str) -> Any:
        """Show the thumbnail (first 4kiB) of text-like documents.

        Textual documents are those whose mimetype starts with text/
        or are a recognized application (json, xml, ...)
        .html and external attachment url are served by Stream (same
        as `/documents/content`).

        :param access_token: the access token to the document record
        """
        document_sudo = self._from_access_token(access_token, skip_log=True)
        if not document_sudo:
            raise request.not_found()
        if document_sudo.type != "binary":
            e = f"bad document type: expected a file (binary) document, found a {document_sudo.type} document"
            raise BadRequest(e)
        attachment_sudo = document_sudo.attachment_id.sudo()
        if not attachment_sudo:
            raise request.not_found()
        if not is_mimetype_textual(document_sudo.mimetype):
            e = f"bad document mimetype: expect text/* or a recognized application/, got {document_sudo.mimetype}"
            raise BadRequest(e)
        # Two things end up served whole rather than as a snippet, for two
        # unrelated reasons, and reading them off one falsy `head` made the
        # route look like it might ship a large file by accident:
        #
        # * HTML is never truncated -- half a document does not render. It goes
        #   out through `Stream`, which sets `default-src 'none'` and `nosniff`,
        #   so it cannot pull anything in or run inline script.
        # * content the client fetches from a remote store (a url-backed
        #   attachment) has no local bytes to take a prefix of, so
        #   `_read_prefix` answers empty and `Stream` performs the redirect.
        #
        # Anything else with an empty prefix is simply an empty file, and
        # streaming it is the same empty response either way.
        if document_sudo.mimetype == "text/html" or not (
            head := attachment_sudo._read_prefix(self.TEXTUAL_THUMBNAIL_SIZE)
        ):
            with replace_exceptions(ValueError, MissingError, by=request.not_found()):
                stream = self._documents_content_stream(document_sudo)
            return stream.get_response(as_attachment=False)
        return request.render(
            "documents.thumbnails_textual",
            {
                "content": head.decode("utf-8", errors="replace"),
            },
        )

    @http.route(
        ["/documents/document/<int:document_id>/update_thumbnail"],
        type="jsonrpc",
        auth="user",
    )
    def documents_update_thumbnail(self, document_id: int, thumbnail: Any) -> None:
        """Update the thumbnail of the document (after it has been generated by the browser).

        We update the thumbnail in SUDO, after checking the read access, so it will work
        if the user that generates the thumbnail is not the user who uploaded the document.
        """
        document = request.env["documents.document"].browse(document_id)
        document.check_access("read")
        if document.thumbnail_status != "client_generated":
            return
        # The thumbnail is served inline to every viewer of the document, and it
        # is written in sudo on top of a mere `read` check (any viewer can
        # generate it client-side). Re-encode the client-supplied bytes through
        # image_process so only a valid, size-bounded raster image can be
        # stored -- never arbitrary/oversized/script-bearing content.
        validated = False
        if thumbnail:
            with replace_exceptions(Exception, by=BadRequest("invalid thumbnail")):
                # base64_to_image raises unless PIL can actually identify the
                # payload as an image (rejects SVG/script/arbitrary bytes); we
                # then bound the dimensions and re-encode to a clean PNG so no
                # non-pixel data survives into what every viewer is served.
                image = base64_to_image(thumbnail)
                image.thumbnail((200, 140))
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, format="PNG")
                validated = base64.b64encode(buffer.getvalue())
        document.sudo().write(
            {
                "thumbnail": validated,
                "thumbnail_status": "present" if validated else "error",
            }
        )

    @http.route(["/documents/zip"], type="http", auth="user")
    def documents_zip(self, file_ids: str, zip_name: str, **kw: Any) -> Any:
        """Select many files / folders in the interface and click on download.

        :param file_ids: if of the files to zip.
        :param zip_name: name of the zip file.
        """
        with replace_exceptions(ValueError, by=BadRequest):
            ids_list = [int(x) for x in file_ids.split(",")]
        documents = request.env["documents.document"].browse(ids_list)
        documents.check_access("read")
        return self._make_zip(zip_name, documents)

    @http.route(
        [
            "/document/download/all/<int:share_id>/<access_token>",
            "/document/download/all/<access_token>",
        ],
        type="http",
        auth="public",
    )
    def documents_download_all_legacy(
        self, access_token: str | None = None, share_id: int | None = None
    ) -> Any:
        """Redirect the deprecated download-all route to the content route."""
        logger.warning(
            "Deprecated since Odoo 18. Please access /documents/content/<access_token> instead."
        )
        return request.redirect(
            f"/documents/content/{quote(access_token or '', safe='')}",
            HTTPStatus.MOVED_PERMANENTLY,
        )

    @http.route(
        ["/document/share/<int:share_id>/<token>", "/document/share/<token>"],
        type="http",
        auth="public",
    )
    def share_portal(
        self, share_id: int | None = None, token: str | None = None
    ) -> Any:
        """Redirect the deprecated share route to the Documents web client."""
        logger.warning(
            "Deprecated since Odoo 18. Please access /odoo/documents/<access_token> instead."
        )
        return request.redirect(
            f"/odoo/documents/{quote(token or '', safe='')}",
            code=HTTPStatus.MOVED_PERMANENTLY,
        )

    @http.route(
        ["/documents/upload/", "/documents/upload/<access_token>"],
        type="http",
        auth="public",
        methods=["POST"],
        max_content_length=_max_content_length,
    )
    def documents_upload(
        self,
        ufile: Any,
        access_token: str = "",
        user_folder_id: str = "",
        owner_id: str = "",
        partner_id: str = "",
        res_id: str = "",
        res_model: Any = False,
        allowed_company_ids: str = "",
    ) -> Any:
        """Replace an existing document or create new ones.

        :param ufile: a list of multipart/form-data files.
        :param access_token: the access token to a folder in which to
            create new documents, or the access token to an existing
            document where to upload/replace its attachment.
            A falsy value means no folder_id and is allowed to
            enable authorized users to upload at the root of
            user_folder_id (My Drive for internal users, Company for
            documents managers)
        :param owner_id, partner_id, res_id, res_model: field values
            when creating new documents, for internal users only
        """
        if allowed_company_ids:
            with replace_exceptions(ValueError, by=BadRequest):
                request.update_context(
                    allowed_company_ids=json.loads(allowed_company_ids)
                )
        # Without a token the upload targets a drive root, and only the two
        # roots documents can actually be filed in are acceptable -- "Shared
        # with me" and "Recent" are views over documents filed elsewhere, and
        # "Trash" is a state.
        with replace_exceptions(ValueError, by=BadRequest):
            upload_root = UserFolder.parse(user_folder_id)
        if (access_token and upload_root) or (
            not access_token
            and (upload_root is None or not upload_root.is_writable_root)
        ):
            raise BadRequest("Incorrect token/user_folder_id values")
        is_internal_user = request.env.user._is_internal()
        if is_internal_user and not access_token:
            document_sudo = request.env["documents.document"].sudo()
        else:
            document_sudo = self._from_access_token(access_token)
            if (
                not document_sudo
                or (
                    document_sudo.user_permission != "edit"
                    and document_sudo.access_via_link != "edit"
                )
                or document_sudo.type not in ("binary", "folder")
            ):
                raise request.not_found()

        files = request.httprequest.files.getlist("ufile")
        if not files:
            raise BadRequest("missing files")
        if len(files) > 1 and document_sudo.type not in (False, "folder"):
            raise BadRequest("cannot save multiple files inside a single document")

        if is_internal_user:
            with replace_exceptions(ValueError, by=BadRequest):
                owner_id = (
                    int(owner_id)
                    if owner_id
                    else request.env.user.id
                    if not user_folder_id
                    else None
                )
                partner_id = int(partner_id) if partner_id else None
                res_id = int(res_id) if res_id else False
            # New documents are created through `document_sudo`, so the ORM
            # performs no access check on these client-supplied values; they have
            # to be validated here, against the *real* user.
            #
            # Only the *create* branch of `_documents_upload` consumes them, and
            # that branch runs for a folder token AND for the token-less upload
            # into a drive root -- where `document_sudo` is the empty recordset,
            # so its `type` is `False`, not `"folder"`. Testing for `"folder"`
            # alone therefore disabled both guards below on exactly the path that
            # uses the values: any internal user (no Documents group required,
            # `_is_internal()` is the only gate on this route) could POST
            # `user_folder_id=MY&res_model=<any>&res_id=<any>` and have the sudo
            # create plant their file on the chatter of a record they cannot
            # write. The route already spells this union out for `len(files) > 1`
            # above; the two must agree.
            values_are_used = document_sudo.type in (False, "folder")
            if (
                values_are_used
                and owner_id
                and owner_id != request.env.user.id
                and not request.env.user.has_group("documents.group_documents_manager")
            ):
                # Otherwise any internal user holding an edit share link could
                # attribute an upload to someone else -- filing a document into
                # that user's drive under their name (audit-trail forgery, and a
                # ready-made social-engineering vector, since the victim sees a
                # file they appear to have created).
                raise Forbidden("cannot upload on behalf of another user")
            if values_are_used and res_model and res_id:
                # Linking an attachment to a record requires write access on that
                # record (core `ir.attachment._check_access` maps create to
                # write). `documents.document._inverse_res_record` enforces this,
                # but only outside superuser mode -- and the create below is
                # sudo, so without this the route stays a way to plant a file on
                # the chatter of any record of any model.
                if res_model not in request.env:
                    raise BadRequest("unknown res_model")
                request.env[res_model].browse(res_id).check_access("write")
        elif owner_id or partner_id or res_id or res_model:
            raise Forbidden("only internal users can provide field values")
        else:
            # `_is_public()`, not the `is_public` field. The latter is related to
            # `partner_id.is_public`, which means "this partner has a public
            # user", not "the caller is the public user" -- they only diverge if
            # a partner is shared with the public user, so this is a consistency
            # fix rather than a live bug. Every other public/portal branch in
            # this module calls `_is_public()`.
            owner_id = (
                document_sudo.owner_id.id
                if request.env.user._is_public()
                else request.env.user.id
            )
            partner_id = None
            res_model = False
            res_id = False

        previous_attachment_id = document_sudo.attachment_id
        document_ids = self._documents_upload(
            document_sudo,
            files,
            owner_id,
            user_folder_id,
            partner_id,
            res_id,
            res_model,
        )
        if document_sudo.type != "folder" and len(document_ids) == 1:
            document_sudo = document_sudo.browse(document_ids)

        if request.env.user._is_public():
            if document_sudo.type == "folder" or previous_attachment_id:
                return request.redirect(document_sudo.access_url)
            return request.redirect("/documents/upload/success")
        else:
            return request.make_json_response(document_ids)

    def _documents_upload(
        self,
        document_sudo: Any,
        files: Any,
        owner_id: Any,
        user_folder_id: str,
        partner_id: Any,
        res_id: Any,
        res_model: Any,
    ) -> list:
        # Replace an existing document or upload a new one.
        is_internal_user = request.env.user._is_internal()

        # Accumulate a recordset rather than rebinding `document_sudo` per file:
        # the post-loop drive-root grant below applies to *every* uploaded
        # document, not just whichever one the loop happened to leave behind.
        created_sudo = request.env["documents.document"].sudo()
        AttachmentSudo = (
            request.env["ir.attachment"]
            .sudo(not is_internal_user)
            .with_context(image_no_postprocess=True)
        )

        if document_sudo.type == "binary":
            attachment_sudo = AttachmentSudo._from_request_file(
                files[0], mimetype="TRUST" if is_internal_user else "GUESS"
            )
            # One write, and `no_document`: this is Documents binding its own
            # attachment to the document it is about to fill in two lines, the
            # same internal move `documents.document._inverse_res_record` makes.
            # Left to the bridge, the two single-field writes re-enter
            # `_create_document`, which either self-binds the request document
            # early -- so the `is a request` test below sees an attachment and
            # skips the edit-link downgrade -- or, for a document linked to a
            # `mixin.documents` record, creates a SECOND document for it.
            attachment_sudo.with_context(no_document=True).write(
                {
                    "res_model": document_sudo.res_model or "documents.document",
                    "res_id": document_sudo.res_id
                    if document_sudo.res_model
                    else document_sudo.id,
                }
            )
            values = {"attachment_id": attachment_sudo.id}
            if not document_sudo.attachment_id:  # is a request
                if document_sudo.access_via_link == "edit":
                    values["access_via_link"] = "view"
            self._documents_upload_create_write(document_sudo, values)
            created_sudo = document_sudo
        else:
            folder_sudo = document_sudo
            location = (
                {"user_folder_id": user_folder_id}
                if user_folder_id
                else {"folder_id": folder_sudo.id}
            )
            # A document created at the *Company* drive root has neither an
            # owner nor a parent folder, so nothing grants its uploader more
            # than the `access_internal` the create defaults to ("view"): a
            # plain documents user could not rename, move or delete the file
            # they had just uploaded.
            #
            # This is granted as part of the create, not repaired afterwards.
            # The previous post-hoc `action_update_access_rights` never fired at
            # all (it tested `owner_id == base.user_root`, which a Company-root
            # document -- created with `owner_id` *unset* -- never matches, and
            # it ran on the loop variable, so it could only ever have covered
            # the last file). Reinstating it as a second pass would also queue an
            # access-tracking entry and file a "gained access" chatter message on
            # a document the user had just created themselves.
            uploader_access = (
                [
                    Command.create(
                        {
                            "partner_id": request.env.user.partner_id.id,
                            "role": "edit",
                        }
                    )
                ]
                if UserFolder.parse(user_folder_id) == UserFolder(UserFolder.COMPANY)
                else []
            )
            for file in files:
                created_sudo |= self._documents_upload_create_write(
                    folder_sudo,
                    {
                        "attachment_id": AttachmentSudo._from_request_file(
                            file, mimetype="TRUST" if is_internal_user else "GUESS"
                        ).id,
                        "type": "binary",
                        "access_via_link": "none"
                        if folder_sudo.access_via_link in (False, "none")
                        else "view",
                        **location,
                        "owner_id": owner_id,
                        "res_model": res_model or False,
                        "res_id": res_id,
                    }
                    | ({"partner_id": partner_id} if partner_id is not None else {})
                    | ({"access_ids": uploader_access} if uploader_access else {}),
                )

        return created_sudo.ids

    def _documents_upload_create_write(self, document_sudo: Any, vals: dict) -> Any:
        """Write *vals* on a binary document, or create one inside a folder.

        The per-file extension point of the upload route: overrides may veto or
        redirect a single file, which is why the loop in :meth:`_documents_upload`
        cannot be batched.

        An override MUST return a ``documents.document`` recordset -- the
        document it handled, or an empty recordset to mean "nothing was
        created". Returning ``None`` breaks both consumers: the caller unions the
        result (``created_sudo |= None`` is a ``TypeError``) and
        ``documents_spreadsheet``'s override reads ``.name`` off it. Neither
        failure is recoverable mid-upload, so they surface as an HTTP 500.

        :return: the document written or created
        :rtype: recordset of documents.document
        """
        # Either write vals on a binary document or create a new document
        # with vals inside a folder document.
        if document_sudo.type == "binary":
            document_sudo.write(vals)
        else:
            vals.setdefault("folder_id", document_sudo.id)
            document_sudo = document_sudo.create(vals)
        if any(field_name in vals for field_name in ["raw", "datas", "attachment_id"]):
            document_sudo.message_post(
                body=_("Document uploaded by %(user)s", user=request.env.user.name)
            )

        return document_sudo

    @http.route("/documents/upload/success", type="http", auth="public")
    def documents_upload_success(self) -> Any:
        """Render the page shown after a successful document request upload."""
        return request.render("documents.document_request_done_page")

    @http.route(
        "/documents/upload_traceback",
        type="http",
        methods=["POST"],
        auth="user",
        # The dispatcher only reads ``routing["max_content_length"]``; as a
        # function default the 1 MiB cap was never enforced (and was bindable
        # from the request body).
        max_content_length=1 << 20,
    )
    def documents_upload_traceback(self, ufile: Any) -> Any:
        """Upload a traceback file into the dedicated traceback folder."""
        if not request.env.user._is_internal():
            raise Forbidden

        folder_sudo = request.env["documents.document"]._get_traceback_folder_sudo()

        files = request.httprequest.files.getlist("ufile")
        if not files:
            raise BadRequest("missing files")
        if len(files) > 1:
            raise BadRequest("This route only accepts one file at a time.")

        traceback_sudo = self._documents_upload_create_write(
            folder_sudo,
            {
                "attachment_id": request.env["ir.attachment"]
                ._from_request_file(files[0], mimetype="text/plain")
                .id,
                "type": "binary",
                "access_internal": "none",
                "access_via_link": "view",
                "folder_id": folder_sudo.id,
                "owner_id": False,
            },
        )

        return request.make_json_response([traceback_sudo.access_url])


class DocumentsAttachmentController(AttachmentController):
    """Extend the mail attachment controller with document-aware behaviour."""

    @http.route()
    def mail_attachment_upload(self, *args: Any, **kw: Any) -> Any:
        """Prevent creating a document when uploading an attachment from a linked activity."""
        if kw.get("activity_id"):
            with replace_exceptions(ValueError, by=BadRequest):
                activity_id = int(kw["activity_id"])
            document = request.env["documents.document"].search(
                [("request_activity_id", "=", activity_id)], limit=1
            )
            if document:
                request.update_context(no_document=True)
        return super().mail_attachment_upload(*args, **kw)

    @http.route(
        "/documents/content/pdf_first_page/<access_token>",
        methods=["GET"],
        type="http",
        auth="public",
        readonly=True,
    )
    def document_attachment_pdf_first_page(
        self, access_token: str | None = None
    ) -> Any:
        """Return the first page of a pdf."""
        document_sudo = ShareRoute._from_access_token(access_token, skip_log=True)
        if not document_sudo.attachment_id:
            raise request.not_found()
        if (document_sudo.mimetype or "") != "application/pdf":
            # Any binary reachable by the token would otherwise be fed to the
            # PDF parser and crash with a 500 instead of a clean response.
            raise BadRequest("document is not a PDF")
        return self._get_pdf_first_page_response(document_sudo.attachment_id)
