import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _name_variants(env, requirement):
    variants = set()
    for code, _label in env["res.lang"].get_installed():
        value = requirement.with_context(lang=code).name
        if value:
            variants.add(value.strip().lower())
    return variants


def _assign(requirement_index, names, attachment_names, taken, visited):
    for index, attachment_name in enumerate(attachment_names):
        if index in visited or not any(n in attachment_name for n in names):
            continue
        visited.add(index)
        holder = taken.get(index)
        if holder is None or _assign(
            holder[0], holder[1], attachment_names, taken, visited
        ):
            taken[index] = (requirement_index, names)
            return True
    return False


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    requests = env["approval.request"].search(
        [("category_id.document_requirement_ids", "!=", False)],
        order="state, id",
    )
    linked = 0
    unmatched = 0
    for request in requests:
        requirements = request.category_id.document_requirement_ids
        attachments = env["ir.attachment"].search(
            [
                ("res_model", "=", "approval.request"),
                ("res_id", "=", request.id),
                ("approval_requirement_id", "=", False),
            ],
            order="id",
        )
        if not requirements or not attachments:
            continue
        attachment_names = [(a.name or "").lower() for a in attachments]
        taken = {}
        for requirement_index, requirement in enumerate(requirements):
            _assign(
                requirement_index,
                frozenset(_name_variants(env, requirement)),
                attachment_names,
                taken,
                set(),
            )
        for attachment_index, (requirement_index, _names) in taken.items():
            attachments[attachment_index].approval_requirement_id = requirements[
                requirement_index
            ].id
            linked += 1
        unmatched += len(attachments) - len(taken)

    _logger.info(
        "approval: linked %d attachment(s) to a document requirement by the "
        "retired filename match; %d attachment(s) matched nothing and keep a "
        "NULL link.",
        linked,
        unmatched,
    )
