import difflib
import io
import itertools
import logging
from contextlib import contextmanager
from copy import deepcopy
from struct import error as StructError

from lxml import etree
from markupsafe import Markup

from odoo import api, models, modules, tools
from odoo.exceptions import RedirectWarning
from odoo.libs.filesystem import guess_mimetype
from odoo.tools import groupby
from odoo.tools.pdf import OdooPdfFileReader, PdfReadError

_logger = logging.getLogger(__name__)


def _can_commit():
    return not (tools.config["test_enable"] or modules.module.current_test)


@contextmanager
def rollbackable_transaction(cr):
    if not _can_commit():
        yield
        return

    cr.commit()
    try:
        yield

        cr.commit()
    except Exception:
        cr.rollback()
        raise


def split_etree_on_tag(tree, tag):
    tree = deepcopy(tree)
    nodes_to_split = tree.findall(f".//{tag}")

    parent_node = nodes_to_split[0].getparent()
    for node in nodes_to_split:
        parent_node.remove(node)

    trees = []
    for node in nodes_to_split:
        parent_node.append(node)
        trees.append(deepcopy(tree))
        parent_node.remove(node)
    return trees


def extract_pdf_embedded_files(filename, content):
    with io.BytesIO(content) as buffer:
        try:
            pdf_reader = OdooPdfFileReader(buffer, strict=False)
        except Exception as e:
            _logger.info('Error when reading the pdf file "%s": %s', filename, e)
            return []

        try:
            return list(pdf_reader.get_attachments())
        except (NotImplementedError, StructError, PdfReadError) as e:
            _logger.warning(
                "Unable to access the attachments of %s. Tried to decrypt it, but %s.",
                filename,
                e,
            )
            return []


class MixinAccountDocumentImport(models.AbstractModel):
    _name = "mixin.account.document.import"
    _description = "Business document import mixin"

    @api.model
    def _create_records_from_attachments(self, attachments, grouping_method=None):
        if grouping_method is None:
            grouping_method = self._group_files_data_by_origin_attachment

        files_data = self._to_files_data(attachments)

        files_data.extend(self._unwrap_attachments(files_data))

        file_data_groups = grouping_method(files_data)

        records = self.create([{}] * len(file_data_groups))
        for record, file_data_group in zip(records, file_data_groups, strict=False):
            attachment_records = self._from_files_data(file_data_group)
            attachment_records.write(
                {
                    "res_model": record._name,
                    "res_id": record.id,
                }
            )
            record.message_post(
                body=self.env._(
                    "This document was created from the following attachment(s)."
                ),
                attachment_ids=attachment_records.ids,
            )

        for record, file_data_group in zip(records, file_data_groups, strict=False):
            record_extended = record._extend_with_attachments(file_data_group, new=True)
            if not record_extended:
                record.message_post(
                    body=self.env._(
                        "There was an error while importing the bill, you can find attached the incoming XML"
                    ),
                )

        return records

    def _group_files_data_by_origin_attachment(self, files_data):
        return [
            file_data_group
            for origin_attachment, file_data_group in groupby(
                files_data, lambda file_data: file_data["origin_attachment"]
            )
        ]

    def _group_files_data_into_groups_of_mixed_types(self, files_data):
        files_data_with_origin_attachment = []
        files_data_without_origin_attachment = []
        for file_data in files_data:
            if "decoder_info" not in file_data:
                file_data["decoder_info"] = self._get_edi_decoder(file_data, new=True)

            if file_data["origin_attachment"] == file_data["attachment"]:
                files_data_without_origin_attachment.append(file_data)
            else:
                files_data_with_origin_attachment.append(file_data)

        groups = []
        sorted_files_data = sorted(
            files_data_without_origin_attachment,
            key=lambda file_data: (file_data["decoder_info"] or {}).get("priority", 0),
            reverse=True,
        )
        for file_data in sorted_files_data:
            self._assign_attachment_to_group_of_different_type(file_data, groups)

        for file_data in files_data_with_origin_attachment:
            self._assign_attachment_to_group_with_same_origin_attachment(
                file_data, groups
            )

        return groups

    def _assign_attachment_to_group_of_different_type(
        self, incoming_file_data, groups=None
    ):
        if groups is None:
            groups = []
        incoming_type = incoming_file_data["import_file_type"]

        if groups_with_different_type := [
            group
            for group in groups
            if not incoming_type
            or incoming_type
            not in (file_data["import_file_type"] for file_data in group)
        ]:
            sorted_by_similarity = sorted(
                groups_with_different_type,
                key=lambda group: max(
                    self._get_similarity_score(
                        incoming_file_data["name"], file_data["name"]
                    )
                    for file_data in group
                ),
                reverse=True,
            )
            sorted_by_similarity[0].append(incoming_file_data)
            return

        groups.append([incoming_file_data])

    def _assign_attachment_to_group_with_same_origin_attachment(
        self, incoming_file_data, groups=None
    ):
        if groups is None:
            groups = []
        for group in groups:
            if any(
                incoming_file_data["origin_attachment"]
                == file_data["origin_attachment"]
                for file_data in group
            ):
                group.append(incoming_file_data)
                return
        groups.append([incoming_file_data])

    def _get_similarity_score(self, filename1, filename2):
        matcher = difflib.SequenceMatcher(a=filename1, b=filename2, autojunk=False)
        return matcher.find_longest_match().size

    def _extend_with_attachments(self, files_data, new=False):
        def _get_attachment_name(file_data):
            params = {
                "filename": file_data["name"],
                "root_filename": file_data["origin_attachment"].name,
                "type": file_data["import_file_type"],
            }
            if not file_data["attachment"]:
                return self.env._(
                    "'%(filename)s' (extracted from '%(root_filename)s', type=%(type)s)",
                    **params,
                )
            else:
                return self.env._("'%(filename)s' (type=%(type)s)", **params)

        self.ensure_one()

        for file_data in files_data:
            if "decoder_info" not in file_data:
                file_data["decoder_info"] = self._get_edi_decoder(file_data, new=new)

        sorted_files_data = sorted(
            files_data,
            key=lambda file_data: (
                file_data["decoder_info"] is not None,
                (file_data["decoder_info"] or {}).get("priority", 0),
            ),
            reverse=True,
        )

        file_data = sorted_files_data[0]

        if (
            file_data["decoder_info"] is None
            or file_data["decoder_info"].get("priority", 0) == 0
        ):
            _logger.info(
                "Attachment(s) %s not imported: no suitable decoder found.",
                [file_data["name"] for file_data in files_data],
            )
            return None

        try:
            with rollbackable_transaction(self.env.cr):
                reason_cannot_decode = file_data["decoder_info"]["decoder"](
                    self, file_data, new
                )
                if reason_cannot_decode:
                    self.message_post(
                        body=self.env._(
                            "Attachment %(filename)s not imported: %(reason)s",
                            filename=file_data["name"],
                            reason=reason_cannot_decode,
                        )
                    )
                    return None
        except RedirectWarning:
            raise
        except Exception as e:
            _logger.exception(
                "Error importing attachment %s on record %s", file_data["name"], self
            )

            self.sudo().message_post(
                body=Markup("%s<br/><br/>%s<br/>%s")
                % (
                    self.env._(
                        "Error importing attachment %(filename)s:",
                        filename=_get_attachment_name(file_data),
                    ),
                    self.env._("This specific error occurred during the import:"),
                    str(e),
                )
            )
            return None
        return True

    def _get_edi_decoder(self, file_data, new=False):
        pass

    def _attachment_fields_to_clear(self):
        return []

    def _fix_attachments_on_record(self, attachments):
        self.ensure_one()
        attachments_to_attach = attachments.filtered(self._should_attach_to_record)
        if attachments_to_attach:
            attachments_to_write = attachments_to_attach.filtered(
                lambda a: a.res_model != self._name or a.res_id != self.id
            )
            attachments_to_write.write(
                {
                    "res_model": self._name,
                    "res_id": self.id,
                }
            )
        attachments_to_unattach = (attachments - attachments_to_attach).filtered(
            lambda a: a.res_model == self._name and not a.res_field
        )
        if attachments_to_unattach:
            for fname in self._attachment_fields_to_clear():
                self[fname] -= attachments_to_unattach
            attachments_to_unattach.write(
                {
                    "res_model": False,
                    "res_id": 0,
                }
            )

    def _fix_attachments_on_record_from_files_data(
        self, valid_files_data, extra_files_data
    ):
        self.ensure_one()
        valid_attachments = self._from_files_data(valid_files_data).filtered(
            lambda a: a.res_model != self._name or a.res_id != self.id
        )
        extra_attachments = self._from_files_data(extra_files_data).filtered(
            lambda a: a.res_model == self._name and not a.res_field
        )
        valid_attachments.write({"res_model": self._name, "res_id": self.id})
        extra_attachments.write({"res_model": False, "res_id": 0})

    def _should_attach_to_record(self, attachment):
        return (
            attachment
            and not attachment.res_field
            and attachment.mimetype
            in {
                "text/csv",
                "application/pdf",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.oasis.opendocument.spreadsheet",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.oasis.opendocument.presentation",
            }
        )

    @api.model
    def _to_files_data(self, attachments):
        files_data = []
        for attachment in attachments:
            file_data = {
                "name": attachment.name,
                "raw": attachment.raw or b"",
                "mimetype": attachment.mimetype,
                "origin_attachment": attachment,
                "attachment": attachment,
            }
            file_data["xml_tree"] = self._get_xml_tree(file_data)
            file_data["import_file_type"] = self._get_import_file_type(file_data)
            file_data["origin_import_file_type"] = file_data["import_file_type"]
            files_data.append(file_data)
        return files_data

    @api.model
    def _from_files_data(self, files_data):
        return self.env["ir.attachment"].union(
            *(
                file_data["attachment"]
                for file_data in files_data
                if file_data.get("attachment")
            )
        )

    @api.model
    def _get_import_file_type(self, file_data):
        if "pdf" in file_data["mimetype"] or file_data["name"].endswith(".pdf"):
            return "pdf"
        return None

    @api.model
    def _get_xml_tree(self, file_data):
        if (
            "text/plain" in file_data["mimetype"]
            and (
                guess_mimetype(file_data["raw"] or b"").endswith("/xml")
                or file_data["name"].endswith(".xml")
            )
        ) or file_data["mimetype"].endswith("/xml"):
            try:
                return etree.fromstring(
                    file_data["raw"],
                    parser=etree.XMLParser(
                        remove_comments=True, resolve_entities=False
                    ),
                )
            except etree.ParseError as e:
                _logger.info(
                    'Error when reading the xml file "%s": %s', file_data["name"], e
                )
        return None

    @api.model
    def _unwrap_attachments(self, files_data, recurse=True):
        return list(
            itertools.chain(
                *(
                    self._unwrap_attachment(file_data, recurse=recurse)
                    for file_data in files_data
                )
            )
        )

    @api.model
    def _unwrap_attachment(self, file_data, recurse=True):
        embedded = []
        if file_data["import_file_type"] == "pdf" and file_data["raw"]:
            for filename, content in extract_pdf_embedded_files(
                file_data["name"], file_data["raw"]
            ):
                embedded_file_data = {
                    "name": filename,
                    "raw": content,
                    "mimetype": guess_mimetype(content),
                    "attachment": None,
                    "origin_attachment": file_data["origin_attachment"],
                    "origin_import_file_type": file_data["origin_import_file_type"],
                }
                embedded_file_data["xml_tree"] = self._get_xml_tree(embedded_file_data)
                embedded_file_data["import_file_type"] = self._get_import_file_type(
                    embedded_file_data
                )
                embedded.append(embedded_file_data)

        if embedded and recurse:
            embedded.extend(self._unwrap_attachments(embedded))

        return embedded

    @api.model
    def _split_xml_into_new_attachments(self, file_data, tag):
        new_files_data = []
        if len(file_data["xml_tree"].findall(f".//{tag}")) > 1:
            trees = split_etree_on_tag(file_data["xml_tree"], tag)
            filename_without_extension, _dummy, extension = file_data[
                "name"
            ].rpartition(".")
            attachment_vals = [
                {
                    "name": f"{filename_without_extension}_{filename_index}.{extension}",
                    "raw": etree.tostring(tree),
                }
                for filename_index, tree in enumerate(trees[1:], start=2)
            ]
            created_attachments = self.env["ir.attachment"].create(attachment_vals)

            new_files_data.extend(self._to_files_data(created_attachments))
        return new_files_data
