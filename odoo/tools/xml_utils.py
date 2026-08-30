import base64
import contextlib
import logging
import typing
import zipfile
from io import BytesIO
from typing import IO, Any, Literal

import requests
from lxml import etree

from odoo.exceptions import UserError
from odoo.libs.xml import (
    create_xml_node,
    create_xml_node_chain,
    dict_to_xml,
    remove_control_characters,
)
from odoo.tools.files import file_open

__all__ = [
    "cleanup_xml_node",
    "dict_to_xml",
    "find_xml_value",
    "load_xsd_files_from_url",
    "validate_xml_from_attachment",
]

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment
    from odoo.orm._typing import BaseModel

type XmlSource = etree._Element | str | bytes

_logger = logging.getLogger(__name__)


class odoo_resolver(etree.Resolver):
    def __init__(self, env: Environment, prefix: str | None) -> None:
        super().__init__()
        self.env = env
        self.prefix = prefix

    def resolve(self, url: str, id: object, context: object) -> object:
        attachment_name = f"{self.prefix}.{url}" if self.prefix else url
        attachment = self.env["ir.attachment"].search(
            [("name", "=", attachment_name)], limit=1
        )
        if attachment:
            return self.resolve_string(attachment.raw, context)
        return None


def _pick_xsd(xsd_attachments: Any, xsd_name: str | None, source: str) -> str:
    if xsd_name:
        picked = xsd_attachments.filtered(lambda a: a.name.endswith(xsd_name))
        if not picked:
            available = ", ".join(sorted(xsd_attachments.mapped("name")))
            raise FileNotFoundError(
                f"{source} provided no XSD named {xsd_name!r}; it has: {available}"
            )
        return picked[0].name
    if len(xsd_attachments) > 1:
        available = ", ".join(sorted(xsd_attachments.mapped("name")))
        raise ValueError(
            f"{source} provided {len(xsd_attachments)} schemas and none was "
            f"named: pass xsd_name= to say which one is the root. "
            f"Available: {available}"
        )
    return xsd_attachments.name


def _check_xml(
    env: Environment,
    url: str | None,
    path: str | None,
    xmls: XmlSource | list[XmlSource],
    xsd_name: str | None = None,
) -> None:
    xsd_attachment: Any = env["ir.attachment"]
    owned: Any = env["ir.attachment"]
    if path:
        with file_open(path, filter_ext=(".xsd",)) as file:
            content = file.read()
        attachment_vals = {
            "name": path.split("/")[-1],
            "datas": base64.b64encode(content.encode()),
        }
        xsd_attachment = owned = env["ir.attachment"].create(attachment_vals)
    elif url:
        xsd_attachment = load_xsd_files_from_url(env, url) or env["ir.attachment"]

    try:
        if not xsd_attachment:
            raise FileNotFoundError(
                f"No XSD could be loaded from {url or path!r}; refusing to report "
                f"the document as validated."
            )

        name = _pick_xsd(xsd_attachment, xsd_name, repr(url or path))

        if not isinstance(xmls, list):
            xmls = [xmls]

        for xml in xmls:
            validate_xml_from_attachment(env, xml, name)
    finally:
        owned.unlink()


def _check_with_xsd(
    tree_or_str: XmlSource,
    stream: str | IO[bytes],
    env: Environment | None = None,
    prefix: str | None = None,
) -> None:
    if not isinstance(tree_or_str, etree._Element):
        tree_or_str = etree.fromstring(
            tree_or_str,
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    if env:
        parser.resolvers.add(odoo_resolver(env, prefix))
        if isinstance(stream, str) and stream.endswith(".xsd"):
            attachment = env["ir.attachment"].search([("name", "=", stream)], limit=1)
            if not attachment:
                raise FileNotFoundError
            stream = BytesIO(attachment.raw)
    xsd_schema = etree.XMLSchema(etree.parse(stream, parser=parser))
    try:
        xsd_schema.assertValid(tree_or_str)
    except etree.DocumentInvalid as xml_errors:
        raise UserError("\n".join(str(e) for e in xml_errors.error_log)) from xml_errors


def cleanup_xml_node(
    xml_node_or_string: etree._Element | str | bytes,
    remove_blank_text: bool = True,
    remove_blank_nodes: bool = True,
    indent_level: int = 0,
    indent_space: str = "  ",
) -> etree._Element:
    xml_node = xml_node_or_string

    if isinstance(xml_node, str):
        xml_node = xml_node.encode()
    if isinstance(xml_node, bytes):
        parser = etree.XMLParser(recover=True, resolve_entities=False)
        xml_node = etree.fromstring(remove_control_characters(xml_node), parser=parser)

    def leaf_iter(parent_node, node, level):
        for child_node in node:
            leaf_iter(node, child_node, level if level < 0 else level + 1)

        if level >= 0:
            indent = "\n" + indent_space * level
            if not node.tail or not node.tail.strip():
                node.tail = "\n" if parent_node is None else indent
            if len(node) > 0:
                if not node.text or not node.text.strip():
                    node.text = indent + indent_space
                last_child = node[-1]
                if last_child.tail == indent + indent_space:
                    last_child.tail = indent

        if parent_node is not None and len(node) == 0:
            if remove_blank_text and node.text is not None and not node.text.strip():
                node.text = ""
            if remove_blank_nodes and not (node.text or ""):
                parent_node.remove(node)

    leaf_iter(None, xml_node, indent_level)
    return xml_node


def _upsert_xsd_attachment(env: Environment, name: str, content: bytes) -> Any:
    fetched_attachment = env["ir.attachment"].search([("name", "=", name)], limit=1)
    if fetched_attachment:
        _logger.info("Updating the content of ir.attachment with name: %s", name)
        fetched_attachment.raw = content
        return fetched_attachment

    _logger.info("Saving XSD file as ir.attachment, with name: %s", name)
    return env["ir.attachment"].create({"name": name, "raw": content, "public": True})


def _fetch_xsd_content(url: str, request_max_timeout: int) -> bytes | None:
    try:
        _logger.info("Fetching file/archive from given URL: %s", url)
        response = requests.get(url, timeout=request_max_timeout)
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        _logger.warning("Request error: %s with the given URL: %s", error, url)
        return None

    if not response.content:
        _logger.warning("The HTTP response from %s is empty (no content)", url)
        return None
    return response.content


def _load_xsd_archive(
    env: Environment,
    archive: zipfile.ZipFile,
    xsd_name_prefix: str,
    xsd_names_filter: list[str] | None,
    modify_xsd_content: Callable[[bytes], bytes] | None,
) -> BaseModel:
    saved_attachments: Any = env["ir.attachment"]
    for file_path in archive.namelist():
        if not file_path.endswith(".xsd"):
            continue

        file_name = file_path.rsplit("/", 1)[-1]
        if xsd_names_filter and file_name not in xsd_names_filter:
            _logger.info("Skipping file with name %s in ZIP archive", file_name)
            continue

        try:
            content = archive.read(file_path)
        except KeyError:
            _logger.warning(
                "Failed to retrieve XSD file with name %s from ZIP archive", file_name
            )
            continue
        if modify_xsd_content:
            content = modify_xsd_content(content)

        prefixed_xsd_name = (
            f"{xsd_name_prefix}.{file_name}" if xsd_name_prefix else file_name
        )
        saved_attachments |= _upsert_xsd_attachment(env, prefixed_xsd_name, content)

    return saved_attachments


def load_xsd_files_from_url(
    env: Environment,
    url: str,
    file_name: str | None = None,
    request_max_timeout: int = 10,
    xsd_name_prefix: str = "",
    xsd_names_filter: list[str] | None = None,
    modify_xsd_content: Callable[[bytes], bytes] | None = None,
) -> BaseModel | Literal[False]:
    content = _fetch_xsd_content(url, request_max_timeout)
    if content is None:
        return False

    archive = None
    with contextlib.suppress(zipfile.BadZipFile):
        archive = zipfile.ZipFile(BytesIO(content))

    if archive is not None:
        return _load_xsd_archive(
            env, archive, xsd_name_prefix, xsd_names_filter, modify_xsd_content
        )

    if modify_xsd_content:
        content = modify_xsd_content(content)
    if not file_name:
        file_name = f"{url.rsplit('/', maxsplit=1)[-1]}"
        _logger.info("XSD name not provided, defaulting to %s", file_name)

    prefixed_xsd_name = (
        f"{xsd_name_prefix}.{file_name}" if xsd_name_prefix else file_name
    )
    return _upsert_xsd_attachment(env, prefixed_xsd_name, content)


def validate_xml_from_attachment(
    env: Environment,
    xml_content: etree._Element | str | bytes,
    xsd_name: str,
    prefix: str | None = None,
    *,
    required: bool = True,
) -> None:
    prefixed_xsd_name = f"{prefix}.{xsd_name}" if prefix else xsd_name
    try:
        _logger.info("Validating with XSD...")
        _check_with_xsd(xml_content, prefixed_xsd_name, env, prefix)
        _logger.info("XSD validation successful!")
    except FileNotFoundError:
        if required:
            raise FileNotFoundError(
                f"XSD {prefixed_xsd_name!r} is not available, so the document "
                f"could not be validated. Load the schema, or pass "
                f"required=False to accept an unvalidated document."
            ) from None
        _logger.warning(
            "XSD %r not found; the document was NOT validated", prefixed_xsd_name
        )
    except etree.XMLSchemaParseError as e:
        if required:
            raise FileNotFoundError(
                f"XSD {prefixed_xsd_name!r} could not be parsed, so the "
                f"document was not validated: {e}"
            ) from e
        _logger.warning(
            "XSD %r is not valid; the document was NOT validated: %s",
            prefixed_xsd_name,
            e,
        )


def find_xml_value(
    xpath: str,
    xml_element: etree._Element,
    namespaces: dict | None = None,
) -> str | None:
    result = xml_element.xpath(xpath, namespaces=namespaces)
    if not result:
        return None
    first = result[0]
    return first if isinstance(first, str) else first.text
