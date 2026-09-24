from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from odoo import models
from odoo.libs.debug_log import DebugLog
from odoo.tools import groupby

_debug = DebugLog(__name__)


@dataclass(frozen=True, slots=True, eq=False)
class ActivityDocument:
    records: models.BaseModel
    changes: dict
    visited: models.BaseModel


class MixinStockActivity(models.AbstractModel):
    _name = "mixin.stock.activity"
    _description = "Chained Document Activity Logging"

    def _get_log_activity_documents(
        self,
        orig_obj_changes,
        stream_field,
        stream,
        groupby_method=False,
    ):
        if self.env.context.get("skip_activity") or not orig_obj_changes:
            return {}
        origins = self.env[next(iter(orig_obj_changes))._name].concat(
            *orig_obj_changes,
        )
        origins_by_record = defaultdict(next(iter(orig_obj_changes)).browse)
        for origin in orig_obj_changes:
            for record in origin[stream_field]:
                origins_by_record[record] |= origin
        visited_by_document = {}
        if stream == "DOWN":
            if not groupby_method:
                raise AssertionError(
                    "You have to define a groupby method and pass them as arguments.",
                )
            grouped_records = groupby(
                origins.mapped(stream_field),
                key=groupby_method,
            )
        elif stream == "UP":
            grouped_records = {}
            for record in origins.mapped(stream_field):
                for (
                    document,
                    responsible,
                    visited,
                ) in record._get_upstream_documents_and_responsibles(
                    self.env["stock.move"],
                ):
                    key = (document, responsible)
                    if key in grouped_records:
                        grouped_records[key] |= record
                        visited_by_document[key] |= visited
                    else:
                        grouped_records[key] = record
                        visited_by_document[key] = visited
            grouped_records = grouped_records.items()
        else:
            raise AssertionError("Unknown stream.")

        documents = {}
        for (parent, responsible), records in grouped_records:
            if not parent:
                continue
            records = self.env[records[0]._name].concat(*records)
            documents[parent, responsible] = ActivityDocument(
                records=records,
                changes={
                    origin: orig_obj_changes[origin]
                    for record in records
                    for origin in origins_by_record[record]
                },
                visited=visited_by_document.get(
                    (parent, responsible),
                    self.env["stock.move"],
                ),
            )
            if _debug.logic.enabled:
                _debug.logic(
                    "log_activity_documents",
                    parent=parent,
                    responsible=responsible.id,
                    origins=len(documents[parent, responsible].changes),
                    records=records,
                )
        return documents

    def _log_activity(self, render_method, documents):
        for (parent, responsible), document in documents.items():
            _debug.lifecycle(
                "log_activity_warning", parent=parent, responsible=responsible.id
            )
            note = render_method(document)
            parent.sudo().activity_schedule(
                "mail.mail_activity_data_warning",
                date.today(),
                note=note,
                user_id=responsible.id,
            )
