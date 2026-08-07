"""The empty value of a groupby/aggregate spec — the read_group leaf.

Split out of :mod:`~odoo.orm.models.mixins.read_group.mixin` to break a cycle,
not for file-size hygiene. ``_read_group_empty_value`` is a small pure helper
that ``fill`` and ``format`` both need, and while it lived on ``ReadGroupMixin``
it was the *only* thing either of them called upwards:

    mixin  -> format : _read_group_format_result, _read_group_postprocess_*
    format -> mixin  : _read_group_empty_value          <- sole back-edge
    mixin  -> fill   : _read_group_fill_results, _read_group_fill_temporal
    fill   -> mixin  : _read_group_empty_value          <- sole back-edge

so one method held the whole ``mixin``/``format``/``fill`` package in a 3-cycle
(really two 2-cycles sharing ``mixin`` as hub). Hosting it on a leaf that both
inherit turns the sub-package into a DAG. The cycle was invisible until
``tooling/architecture/mixin_coupling_check.py`` began measuring the mixins'
``self``-call graph, which no import-based checker can see.

Keep this module a leaf: it may read the recordset surface declared by
``_ModelStubs``, but it must not call back into ``mixin``, ``format`` or
``fill``, or the cycle returns.
"""

from .... import decorators as api
from ....parsing import parse_read_group_spec
from .._model_stubs import _ModelStubs


class _ReadGroupEmptyMixin(_ModelStubs):
    """Empty-value resolution for groupby and aggregate specs."""

    __slots__ = ()

    @api.model
    def _read_group_empty_value(self, spec):
        """Return the empty value corresponding to the given groupby spec or aggregate spec."""
        if spec == "__count":
            return 0
        fname, chain_fnames, func = parse_read_group_spec(spec)
        if func in ("count", "count_distinct"):
            return 0
        if func in ("array_agg", "array_agg_distinct"):
            return []
        field = self._fields[fname]
        if (not func or func == "recordset") and (field.relational or fname == "id"):
            if chain_fnames and field.type == "many2one":
                groupby_seq = f"{chain_fnames}:{func}" if func else chain_fnames
                model = self.env[field.comodel_name]
                return model._read_group_empty_value(groupby_seq)
            return (
                self.env[field.comodel_name]
                if field.relational
                else self.env[self._name]
            )
        return False
