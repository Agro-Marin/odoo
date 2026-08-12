from datetime import date

from odoo import models
from odoo.tools import groupby


class StockActivityMixin(models.AbstractModel):
    """Schedule warning activities on the documents a chain of moves reaches.

    Both methods are model-agnostic: the caller supplies the changed records, the
    relation to follow, and how to render the note. They lived on `stock.picking`
    only because the delivery flow needed them first, which is why
    `sale_stock`, `purchase_stock`, `mrp` and `industry_fsm_stock` all call
    `env["stock.picking"]._log_activity_get_documents(...)` with sale lines,
    purchase lines and manufacturing raw moves -- using a picking as a namespace.
    Inherit this instead.
    """

    _name = "stock.activity.mixin"
    _description = "Chained Document Activity Logging"

    def _log_activity_get_documents(
        self,
        orig_obj_changes,
        stream_field,
        stream,
        groupby_method=False,
    ):
        """Find the (document, responsible) pairs to notify for the given changes, following
        either the upstream ("UP") or downstream ("DOWN") documents, and build a rendering
        context per document containing only the changes relevant to it (e.g. a picking is
        only notified about the moves it actually contains).

        :param dict orig_obj_changes: record -> change on that record, e.g. {move: (new_qty, old_qty)}
        :param str stream_field: field on the `orig_obj_changes` records to follow, e.g. 'move_dest_ids'
        :param str stream: ``'UP'`` (log on the topmost ongoing document) or ``'DOWN'`` (log on
            the following documents)
        :param groupby_method: required when `stream` is 'DOWN'; groups objects by
            (document to log on, responsible for that document)
        """
        if self.env.context.get("skip_activity") or not orig_obj_changes:
            # No changes means no documents to notify. Without the guard the model
            # name below is taken from `next(iter(...))`, which raises StopIteration
            # -- a bad failure for a method five modules call with a dict they built.
            return {}
        move_to_orig_object_rel = {
            co: ooc for ooc in orig_obj_changes for co in ooc[stream_field]
        }
        origin_objects = self.env[next(iter(orig_obj_changes))._name].concat(
            *orig_obj_changes,
        )
        # Group each destination object by (document to log, responsible), regardless of
        # stream direction. E.g.:
        # {(delivery_picking_1, admin): stock.move(1, 2),
        #  (delivery_picking_2, admin): stock.move(3)}
        visited_documents = {}
        if stream == "DOWN":
            if groupby_method:
                grouped_moves = groupby(
                    origin_objects.mapped(stream_field),
                    key=groupby_method,
                )
            else:
                raise AssertionError(
                    "You have to define a groupby method and pass them as arguments.",
                )
        elif stream == "UP":
            # Ascending requires `_get_upstream_documents_and_responsibles` to be
            # defined on the destination objects.
            grouped_moves = {}
            for visited_move in origin_objects.mapped(stream_field):
                for (
                    document,
                    responsible,
                    visited,
                ) in visited_move._get_upstream_documents_and_responsibles(
                    self.env[visited_move._name],
                ):
                    if grouped_moves.get((document, responsible)):
                        grouped_moves[document, responsible] |= visited_move
                        visited_documents[document, responsible] |= visited
                    else:
                        grouped_moves[document, responsible] = visited_move
                        visited_documents[document, responsible] = visited
            grouped_moves = grouped_moves.items()
        else:
            raise AssertionError("Unknown stream.")

        documents = {}
        for (parent, responsible), moves in grouped_moves:
            if not parent:
                continue
            moves = self.env[moves[0]._name].concat(*moves)
            rendering_context = {
                move: (orig_object, orig_obj_changes[orig_object])
                for move in moves
                for orig_object in move_to_orig_object_rel[move]
            }
            if visited_documents:
                documents[parent, responsible] = (
                    rendering_context,
                    visited_documents.values(),
                )
            else:
                documents[parent, responsible] = rendering_context
        return documents

    def _log_activity(self, render_method, documents):
        """Schedule a warning activity on each (document, responsible) pair in `documents`,
        with the note rendered by `render_method(rendering_context)`.

        :param dict documents: (document, responsible) -> rendering_context, as returned by
            `_log_activity_get_documents`
        :param callable render_method: rendering_context -> html note string
        """
        for (parent, responsible), rendering_context in documents.items():
            note = render_method(rendering_context)
            parent.sudo().activity_schedule(
                "mail.mail_activity_data_warning",
                date.today(),
                note=note,
                user_id=responsible.id,
            )
