"""Stored access rows read their reach through the models' anchors.

A module's own rows are rewritten when its data loads; this converts the rows
data does not reach: noupdate rows and the database's own. Each is read by the
same recognizer the source rewrite used and changed only when the rows it
proposes are proven equal to its domain and every anchor they read is one the
model declares. A split permission keeps its id for the first row and names
the others `<xmlid>_2`..., as the modules' files do. Losing this step is
harmless, which is why it runs last: an unconverted row keeps a correct domain.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.models import Anchor

from odoo.addons.base.models.ir_access import REACH_ANCHOR
from odoo.addons.base.models.ir_access_reach import Part, propose, proves

_logger = logging.getLogger(__name__)

KIND_OF_RUNG = {
    ("own", "owner"): "owner",
    ("own", "creator"): "creator",
    ("own", "employee"): "employee",
    ("own", "partner"): "partner",
    ("partner", "partner"): "partner",
    ("team", "team"): "team",
    ("company", "company"): "company",
}


def _key(anchors: dict[str, Anchor], part: Part) -> str | None:
    if part.reach in ("all", "none"):
        return ""
    kind = KIND_OF_RUNG[(part.reach, part.kind)]
    wanted = (part.path, kind, part.unset, part.hierarchy or "", part.usage or None)
    keys = [
        key
        for key, anchor in anchors.items()
        if (
            anchor.path,
            anchor.kind,
            bool(anchor.shared),
            anchor.hierarchy or "",
            anchor.usage or None,
        )
        == wanted
    ]
    if not keys:
        return None
    default = REACH_ANCHOR.get(part.reach)
    key = default if default in keys else min(keys)
    return "" if key == default else key


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Access = env["ir.access"].with_context(active_test=False)
    registry = env.registry
    counts = {"converted": 0, "split": 0, "unanchored": 0, "unproven": 0}
    for access in Access.search([("reach", "=", False), ("domain", "!=", False)]):
        model = access.model_id.model
        if model not in registry:
            continue
        proposal = propose(access.domain, access.kind)
        if proposal is None:
            continue
        if not proves(access.domain, proposal):
            counts["unproven"] += 1
            continue
        anchors = registry.model_anchors.get(model, {})
        keys = [_key(anchors, part) for part in proposal.parts]
        if any(key is None for key in keys):
            counts["unanchored"] += 1
            continue
        xmlid = access.get_external_id().get(access.id)
        noupdate = False
        if xmlid:
            module, name = xmlid.split(".", 1)
            noupdate = bool(
                env["ir.model.data"]
                .search([("module", "=", module), ("name", "=", name)], limit=1)
                .noupdate
            )
        for index, (part, key) in enumerate(
            zip(proposal.parts, keys, strict=True), start=1
        ):
            values = {
                "reach": part.reach,
                "anchor": key or False,
                "domain": part.static or False,
            }
            if index == 1:
                access.write(values)
                continue
            sibling = (
                env.ref(f"{module}.{name}_{index}", raise_if_not_found=False)
                if xmlid
                else None
            )
            if sibling is not None and sibling._name == "ir.access":
                # the module's file split the row too, and loaded its parts
                sibling.write(values)
                continue
            extra = access.copy({"name": f"{access.name} ({index})", **values})
            if xmlid:
                env["ir.model.data"].create(
                    {
                        "module": module,
                        "name": f"{name}_{index}",
                        "model": "ir.access",
                        "res_id": extra.id,
                        "noupdate": noupdate,
                    }
                )
        counts["converted"] += 1
        counts["split"] += len(proposal.parts) > 1
    _logger.info(
        "base 1.117: %(converted)s access rows read their reach through anchors "
        "(%(split)s split); %(unanchored)s kept their domain for want of a declared "
        "anchor, %(unproven)s because the reach proposed was not proven equal",
        counts,
    )
