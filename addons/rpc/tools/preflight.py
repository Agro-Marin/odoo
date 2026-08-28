"""Reject a caller's mistake as a caller's mistake, before the ORM sees it.

An RPC caller names fields, domains, sort orders, group specifications and
values by string. The ORM's answers to a stale name are inconsistent and none of
them are useful to the caller who made the mistake: ``read`` logs
``Invalid field(s) [...] skipping`` and returns the record *without* those keys
(``odoo/orm/models/mixins/read.py``), ``web_read`` silently drops any
``specification`` key that is not a field, a domain raises a bare ``ValueError``,
an ``order`` raises another, and ``write`` raises ``KeyError: 'field'``. Over
XML-RPC the raising ones become fault 500 "Internal Server Error" with a
traceback in the server log, so a client's typo is indistinguishable -- on the
wire and in the log -- from the server breaking, and it wakes whatever alerts on
tracebacks. The silent ones are worse: HTTP 200 and quietly incomplete data,
with no signal for the caller to correct itself.

Leniency is right for the web client, which only ever sends field names it read
from the same server. It is wrong for an external agent asking with field
knowledge from stock Odoo, from an older version, or from a fork that renamed
something -- ``free_qty`` where this one has ``qty_free``.

These are **opt-in**. Nothing in `rpc`'s own endpoints calls them, because
turning a currently-lenient `read` into a 400 would change behaviour for every
existing caller of `/json/2` and `/xmlrpc/2/*`. A surface that wants
caller-error diagnostics runs `check_call` before dispatch and maps the
`UserError` to its own protocol's 400.

Only field *names* are checked, never value types, and only the leading segment
of a dotted path -- the rest is resolved against comodels the ORM knows how to
walk. A wrong-typed value and an unknown operator stay the ORM's to reject, so a
well-formed call is never falsely refused.

They live here rather than beside a caller because two consumers already reach
for them and a third surface has the same problem: they are written against
``call_kw`` argument positions, not against anything one protocol owns.

`CALL_SHAPES` is the single table those positions live in. It replaced six
overlapping ones (a set per check, plus two exception maps for the arguments
that do not sit at index 0), which is how three whole classes of argument came
to be checked by nothing: every *positional* `order`, `formatted_read_group`'s
`having`, and `web_save`/`web_save_multi`/`onchange`/`default_get`/`load`
entirely. `test_preflight` asserts the table against the live registry, so the
next public method to grow a field-name argument fails a test instead of
silently joining them.
"""

import difflib
from typing import Any, NamedTuple

from odoo.exceptions import UserError
from odoo.fields import Domain

#: A sequence of bare field names.
FIELDS = "fields"
#: One bare field name, not a sequence of them.
FIELD = "field"
#: A sequence of export-style field paths (``partner_id/name``), whose leading
#: segment is a field of this model and whose tail resolves against a comodel.
PATHS = "paths"
#: A dict whose TOP-LEVEL keys are field names. Nested sub-specifications
#: resolve against a comodel and are core's to validate, so they are not walked.
SPEC = "spec"
#: A search domain.
DOMAIN = "domain"
#: A comma-separated ``"field [asc|desc]"`` string.
ORDER = "order"
#: One or more groupby / aggregate specs (``create_date:month``, ``amount:sum``),
#: possibly nested one level for ``grouping_sets``.
GROUP = "group"
#: A domain whose left-hand sides are aggregate specs rather than plain fields.
HAVING = "having"
#: A values dict keyed by field name, or a sequence of them.
VALS = "vals"


class Argument(NamedTuple):
    """One field-name-bearing argument of one model method.

    :param kind: what the value is, one of the constants above
    :param index: its position in ``call_kw``'s ``args``, or ``None`` when the
        parameter is keyword-only and therefore has no position at all
    :param name: its parameter name, which is also its key in ``kwargs``
    :param key: set when the field name is not the argument but sits *inside*
        it, under this key of a dict of options -- ``read_progress_bar``'s
        ``progress_bar={"field": ..., "colors": ...}`` is the one such shape
    """

    kind: str
    index: int | None
    name: str
    key: str | None = None


# `call_kw` flattens a call to (args, kwargs). A *record* method's args[0] is
# the ids, so its own first parameter is args[1]; an `@api.model` method's
# args[0] is its own first parameter. Every index below is therefore what a
# caller actually puts on the wire, read off the ORM signature quoted with it.
# Getting one wrong is silent in both directions -- too low and a check reads
# the wrong argument, too high and it reads nothing -- which is why the
# signature is quoted and why `test_preflight` re-derives every index from
# `inspect.signature` rather than trusting this table.
CALL_SHAPES: dict[str, tuple[Argument, ...]] = {
    # read(fields, load)
    "read": (Argument(FIELDS, 1, "fields"),),
    # search(domain, offset, limit, order)
    "search": (Argument(DOMAIN, 0, "domain"), Argument(ORDER, 3, "order")),
    # search_count(domain, limit)
    "search_count": (Argument(DOMAIN, 0, "domain"),),
    # search_read(domain, fields, offset, limit, order)
    "search_read": (
        Argument(DOMAIN, 0, "domain"),
        Argument(FIELDS, 1, "fields"),
        Argument(ORDER, 4, "order"),
    ),
    # name_search(name, domain, operator, limit) -- the domain hides behind
    # `name`, so a reader assuming args[0] finds a search string there and
    # checks nothing.
    "name_search": (Argument(DOMAIN, 1, "domain"),),
    # default_get(fields)
    "default_get": (Argument(FIELDS, 0, "fields"),),
    # load(fields, data) -- export-style paths (`partner_id/name`), the one
    # field list that is not a list of bare names.
    "load": (Argument(PATHS, 0, "fields"),),
    # export_data(fields_to_export) -- the read half of the import/export pair,
    # and the one method here that returns raw values under a key of its own
    # (`{"datas": [[...]]}`) rather than keyed by field name. A policy that
    # filters a result by its keys therefore cannot see into it, which makes
    # naming the fields the only place to refuse.
    "export_data": (Argument(PATHS, 1, "fields_to_export"),),
    # get_field_translations(field_name, langs) -- reads the field's value in
    # every installed language, and indexes `self._fields[field_name]`
    # directly, so a stale name is a bare KeyError.
    "get_field_translations": (Argument(FIELD, 1, "field_name"),),
    # update_field_translations(field_name, translations, source_lang) -- the
    # write half of the same pair.
    "update_field_translations": (Argument(FIELD, 1, "field_name"),),
    # search_panel_select_range(field_name, kwargs) -- returns the distinct
    # values of one field, so the field name IS the read.
    "search_panel_select_range": (Argument(FIELD, 0, "field_name"),),
    "search_panel_select_multi_range": (Argument(FIELD, 0, "field_name"),),
    # web_resequence(specification, field_name, offset) -- a read spec and the
    # ordering field it writes.
    "web_resequence": (
        Argument(SPEC, 1, "specification"),
        Argument(FIELD, 2, "field_name"),
    ),
    # create(vals_list) -- @api.model_create_multi, so one dict or a list
    "create": (Argument(VALS, 0, "vals_list"),),
    # write(vals)
    "write": (Argument(VALS, 1, "vals"),),
    # copy(default) / copy_data(default) -- optional, so often absent
    "copy": (Argument(VALS, 1, "default"),),
    "copy_data": (Argument(VALS, 1, "default"),),
    # onchange(values, field_names, fields_spec)
    "onchange": (
        Argument(VALS, 1, "values"),
        Argument(FIELDS, 2, "field_names"),
        Argument(SPEC, 3, "fields_spec"),
    ),
    # read_group(domain, fields, groupby, offset, limit, orderby, lazy) -- the
    # sort parameter is `orderby` here and `order` everywhere else, so a check
    # keyed on the name alone misses this one even in its keyword form.
    "read_group": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "fields"),
        Argument(GROUP, 2, "groupby"),
        Argument(ORDER, 5, "orderby"),
    ),
    # formatted_read_group(domain, groupby, aggregates, having, offset, limit, order)
    "formatted_read_group": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "groupby"),
        Argument(GROUP, 2, "aggregates"),
        Argument(HAVING, 3, "having"),
        Argument(ORDER, 6, "order"),
    ),
    # formatted_read_grouping_sets(domain, grouping_sets, aggregates, *, order)
    "formatted_read_grouping_sets": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "grouping_sets"),
        Argument(GROUP, 2, "aggregates"),
        Argument(ORDER, None, "order"),
    ),
    # read_progress_bar(domain, group_by, progress_bar) -- three field names
    # in three shapes, the third of them inside a dict of options.
    "read_progress_bar": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "group_by"),
        Argument(FIELD, 2, "progress_bar", "field"),
    ),
    # web_read(specification)
    "web_read": (Argument(SPEC, 1, "specification"),),
    # web_search_read(domain, specification, offset, limit, order, count_limit)
    "web_search_read": (
        Argument(DOMAIN, 0, "domain"),
        Argument(SPEC, 1, "specification"),
        Argument(ORDER, 4, "order"),
    ),
    # web_name_search(name, specification, domain, operator, limit) -- runs
    # web_read(spec) on its hits, so the spec's keys are field names too.
    "web_name_search": (
        Argument(SPEC, 1, "specification"),
        Argument(DOMAIN, 2, "domain"),
    ),
    # web_read_group(domain, groupby, aggregates, limit, offset, order, *,
    #                auto_unfold, opening_info, unfold_read_specification,
    #                unfold_read_default_limit, groupby_read_specification)
    "web_read_group": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "groupby"),
        Argument(GROUP, 2, "aggregates"),
        Argument(ORDER, 5, "order"),
        Argument(SPEC, None, "unfold_read_specification"),
        Argument(SPEC, None, "groupby_read_specification"),
    ),
    # web_save(vals, specification, next_id, last_write_date, known_values) --
    # a write and a read back in one call, and the method a modern client
    # reaches for first. Both halves name fields.
    "web_save": (
        Argument(VALS, 1, "vals"),
        Argument(SPEC, 2, "specification"),
    ),
    # web_save_multi(vals_list, specification, known_values)
    "web_save_multi": (
        Argument(VALS, 1, "vals_list"),
        Argument(SPEC, 2, "specification"),
    ),
}


def call_args(params: list) -> tuple[list, dict]:
    """The (args, kwargs) an execute_kw params tuple carries."""
    args = params[5] if len(params) > 5 and isinstance(params[5], list) else []
    kwargs = params[6] if len(params) > 6 and isinstance(params[6], dict) else {}
    return args, kwargs


def arguments(model_method: str, kind: str, args, kwargs) -> list:
    """Every argument of `kind` that a call to `model_method` carries.

    Keyword first, then the recorded position -- the order `call_kw` itself
    resolves them in. An argument the caller omitted yields nothing rather than
    a ``None`` for each check to re-filter.
    """
    found = []
    for argument in CALL_SHAPES.get(model_method, ()):
        if argument.kind != kind:
            continue
        value = kwargs.get(argument.name)
        if value is None and argument.index is not None and len(args) > argument.index:
            value = args[argument.index]
        if argument.key is not None:
            value = value.get(argument.key) if isinstance(value, dict) else None
        if value is not None:
            found.append(value)
    return found


def _first(model_method: str, kind: str, args, kwargs):
    values = arguments(model_method, kind, args, kwargs)
    return values[0] if values else None


def _leading_name(spec: Any) -> str:
    """The field a spec leads with: `x` from `x.y`, `x:month`, `x/y`, `x desc`.

    A path's tail resolves against a comodel with its own fields, and a
    granularity or aggregate suffix is not a field, so neither is ours to check.
    """
    if not isinstance(spec, str):
        return ""
    head = spec
    for separator in (":", ".", "/"):
        head = head.split(separator, 1)[0]
    return head.strip()


def _iter_field_names(kind: str, container) -> list[str]:
    """The field names one argument carries, normalised for its kind.

    A ``SPEC`` is a dict keyed by field name and a ``FIELDS`` argument a
    sequence of them; neither is descended into, and both are exact names.
    ``PATHS`` are export-style (``partner_id/name``) and ``FIELD`` is one bare
    name rather than a container, so those two are reduced to their leading
    segment. Anything else -- a caller who sent a bare string where a list
    belongs, say -- carries no usable list and yields nothing, because "no
    fields named" and "every field" must not be told apart here.
    """
    if kind is FIELD:
        return [_leading_name(container)] if isinstance(container, str) else []
    if not isinstance(container, dict | list | tuple):
        return []
    names = list(container)
    if kind is PATHS:
        return [_leading_name(name) for name in names]
    return names


def _iter_grouping_specs(container):
    """Yield the string specs inside a groupby/aggregate argument.

    ``formatted_read_grouping_sets`` nests one level deeper (a list of groupby
    tuples), so this recurses; a non-string, non-sequence element yields
    nothing rather than raising.
    """
    if isinstance(container, str):
        yield container
    elif isinstance(container, list | tuple):
        for item in container:
            yield from _iter_grouping_specs(item)


def _iter_vals_dicts(model_method: str, args, kwargs):
    """Yield the values dict(s) a create/write/copy/web_save call carries.

    ``create`` may pass a single dict or a list of them; the others pass one.
    A non-dict (a bare ``copy`` with no override, a malformed call) yields
    nothing rather than raising.
    """
    for vals in arguments(model_method, VALS, args, kwargs):
        if isinstance(vals, dict):
            yield vals
        elif isinstance(vals, list | tuple):
            for item in vals:
                if isinstance(item, dict):
                    yield item


def _parse_domain(domain):
    """The parsed domain, or None when it is not one this can read.

    Best-effort by construction: a caller whose domain cannot be parsed is one
    the ORM will refuse anyway, and name extraction is not the place to report
    syntax. ``check_domain`` reports it; this does not.
    """
    if isinstance(domain, Domain):
        return domain
    if not isinstance(domain, list | tuple):
        return None
    try:
        return Domain(list(domain))
    except ValueError, TypeError:
        return None


def _domain_names(domain) -> list[str]:
    parsed = _parse_domain(domain)
    if parsed is None:
        return []
    return [_leading_name(str(c.field_expr)) for c in parsed.iter_conditions()]


def _order_names(order) -> list[str]:
    """The field each term of an `order` string sorts by."""
    if not order or not isinstance(order, str):
        return []
    return [_leading_name(term.split()[0]) for term in order.split(",") if term.strip()]


def _requested_fields(model_method: str, args: list, kwargs: dict) -> list | None:
    """Return the field names a call's field list or specification asks for.

    :return: the requested names, or ``None`` when this call carries no usable
        field list -- wrong method, or omitted, which means "all fields" and
        must not be validated as if it named none.
    """
    names = []
    for kind in (FIELDS, PATHS, FIELD, SPEC):
        for container in arguments(model_method, kind, args, kwargs):
            names.extend(_iter_field_names(kind, container))
    return names or None


def domain_argument(model_method: str, args, kwargs):
    """The search domain a call carries, wherever its signature puts it.

    Its own function because the position is not uniform and getting it wrong
    is silent: `search` and friends take it at args[0], but `name_search` takes
    it at args[1] and `web_name_search` at args[2], behind their `name`
    argument. A caller that assumes args[0] finds the *name* string there,
    decides it is not a domain, and checks nothing at all.

    :return: the domain, or None when this call carries none
    """
    return _first(model_method, DOMAIN, args, kwargs)


def mentioned_field_names(model_method: str, args, kwargs) -> list[str]:
    """Every field name a call mentions, in whichever shape it mentions it.

    The union of everything `CALL_SHAPES` records for the method -- field list,
    specification, domain, order, group specification, ``having`` and values
    dict -- flattened to leading names. Separate from the checks below because
    it answers a different question: they ask "does this name exist", this asks
    "which names are named", which is what a policy about *particular* fields
    needs. `agromarin/mcp_server`'s field denial is that policy, and a name this
    misses is a field its denial does not cover.

    ``__count`` and other ``__``-prefixed pseudo-fields are dropped, matching
    what `check_grouping` skips: neither is a field, and a caller cannot deny
    one.
    """
    names: list[str] = []
    for kind in (FIELDS, PATHS, FIELD, SPEC):
        for container in arguments(model_method, kind, args, kwargs):
            names.extend(_leading_name(n) for n in _iter_field_names(kind, container))
    for domain in arguments(model_method, DOMAIN, args, kwargs):
        names.extend(_domain_names(domain))
    for having in arguments(model_method, HAVING, args, kwargs):
        names.extend(_domain_names(having))
    for order in arguments(model_method, ORDER, args, kwargs):
        names.extend(_order_names(order))
    for container in arguments(model_method, GROUP, args, kwargs):
        names.extend(_leading_name(spec) for spec in _iter_grouping_specs(container))
    for vals in _iter_vals_dicts(model_method, args, kwargs):
        names.extend(_leading_name(key) for key in vals)
    return [name for name in names if name and not name.startswith("__")]


def _close_field_names(name: str, known: list) -> list:
    tokens = frozenset(name.split("_"))
    reordered = [k for k in known if frozenset(k.split("_")) == tokens and k != name]
    if reordered:
        return reordered[:2]
    return difflib.get_close_matches(name, known, n=2, cutoff=0.5)


def _describe_unknown(name, known: list) -> str:
    if not isinstance(name, str):
        return f"{name!r} (not a string)"
    close = _close_field_names(name, known)
    if close:
        return f"{name!r} (did you mean {' or '.join(repr(c) for c in close)}?)"
    return repr(name)


def _unknown_field_names(env, model_name: str, names) -> str:
    """The unknown names among `names`, rendered with suggestions.

    Empty when every name is a field, which is the caller's "nothing to
    report". Each check keeps its own literal message -- a message assembled
    from fragments is a message no translator can reach -- and shares only the
    scan and the rendering, which is where the five of them were identical.
    """
    model_fields = env[model_name]._fields
    unknown = []
    for name in names:
        # An empty name is a spec whose leading segment is not a field of this
        # model at all: `export_data`/`load` accept `.id` and `id/.id`, whose
        # head is the empty string. Reporting "" as an unknown field rejects a
        # perfectly ordinary export. `__count` and friends are pseudo-fields,
        # skipped for the same reason -- neither is ours to refuse.
        if isinstance(name, str) and (not name or name.startswith("__")):
            continue
        if (isinstance(name, str) and name in model_fields) or name in unknown:
            continue
        unknown.append(name)
    if not unknown:
        return ""
    known = sorted(model_fields)
    return ", ".join(_describe_unknown(name, known) for name in unknown)


def check_requested_fields(env, model_name: str, model_method: str, args, kwargs):
    """Reject a call naming fields the model does not have in its field list.

    ``read`` is deliberately lenient in the ORM: it logs
    ``Invalid field(s) [...] skipping`` and returns the record *without* those
    keys (see ``odoo/orm/models/mixins/read.py``); ``web_read`` does the same,
    skipping any ``specification`` key that is not a field. For the web client
    that is the right call, but MCP's callers are external agents that ask with
    field knowledge from stock Odoo or an older version -- ``free_qty`` instead
    of this fork's ``qty_free``. They got HTTP 200 and silently incomplete data,
    with no signal to correct themselves.

    :raise UserError: naming the unknown fields, with close matches when there
        are any. ``_classify_fault`` maps that to fault 400, so the caller can
        tell its own mistake from a server failure.
    """
    requested = _requested_fields(model_method, args, kwargs)
    if requested is None:
        return
    if unknown := _unknown_field_names(env, model_name, requested):
        raise UserError(
            env._(
                "Unknown field(s) on '%(model)s': %(fields)s. "
                "Call fields_get('%(model)s') for the fields this model "
                "actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_domain(env, model_name: str, model_method: str, args, kwargs):
    """Reject a search domain the model cannot answer, as a caller error.

    Same reasoning as ``check_requested_fields``, for the other half of a
    search. A stale field name in a *domain* raised a bare ``ValueError`` out
    of the ORM, which fell through to fault 500 "Internal Server Error" plus an
    ERROR-with-traceback in the server log -- so a client's own typo was
    indistinguishable, on the wire and in the log, from the server breaking,
    and it woke the log-viewer's alerting. These are the most common caller
    mistakes MCP actually sees in production: invalid field in condition,
    malformed domain, invalid operator.

    :raise UserError: mapped to fault 400 by ``_classify_fault``.
    """
    domain = domain_argument(model_method, args, kwargs)
    if domain is None or isinstance(domain, Domain):
        return
    if not isinstance(domain, list | tuple):
        raise UserError(
            env._(
                "The domain for '%(model)s' must be a list, got %(kind)s.",
                model=model_name,
                kind=type(domain).__name__,
            )
        )

    model = env[model_name]
    try:
        parsed = Domain(list(domain))
    except (ValueError, TypeError) as e:
        raise UserError(
            env._(
                "Malformed domain for '%(model)s': %(error)s",
                model=model_name,
                error=e,
            )
        ) from e

    # Report unknown field names ourselves so the caller gets a suggestion;
    # only the leading segment of a path is checked, because the rest is
    # resolved against comodels that validate() knows how to walk.
    if unknown := _unknown_field_names(env, model_name, _domain_names(parsed)):
        raise UserError(
            env._(
                "Unknown field(s) in the domain for '%(model)s': %(fields)s. "
                "Call fields_get('%(model)s') for the fields this model "
                "actually has.",
                model=model_name,
                fields=unknown,
            )
        )

    try:
        parsed.validate(model)
    except (ValueError, TypeError) as e:
        raise UserError(
            env._(
                "Invalid domain for '%(model)s': %(error)s",
                model=model_name,
                error=e,
            )
        ) from e


def check_order(env, model_name: str, model_method: str, args, kwargs):
    """Reject an ``order`` naming fields the model does not have.

    The third shape of the same caller mistake, after the field list and the
    domain. ``order`` is a comma-separated "field [asc|desc]" list and a stale
    name raises ``ValueError: Invalid field 'x' on model 'y'`` straight out of
    the ORM -- fault 500, with a traceback in the log.

    Takes the method like its siblings, because the sort argument is *not*
    uniformly a keyword called ``order``: `search` puts it at args[3],
    `search_read` and `web_search_read` at args[4], `web_read_group` at args[5],
    `formatted_read_group` at args[6], and `read_group` calls it ``orderby``.
    Reading only ``kwargs['order']`` -- which this did until `CALL_SHAPES`
    existed -- let every positional sort through unchecked, and `read_group`'s
    through in both forms.

    :raise UserError: mapped to fault 400 by ``_classify_fault``.
    """
    model_fields = env[model_name]._fields
    unknown = []
    for order in arguments(model_method, ORDER, args, kwargs):
        if not order or not isinstance(order, str):
            continue
        for term in order.split(","):
            parts = term.split()
            if not parts:
                continue
            head, _, rest = parts[0].partition(".")
            head = head.split(":", 1)[0]
            if not head:
                continue
            field = model_fields.get(head)
            if field is None:
                if head not in unknown:
                    unknown.append(head)
                continue
            # A dotted term is only meaningful for a properties field; the ORM
            # cannot sort across a relation and answers `Invalid field property
            # '<rest>' on <model>.<head>` -- 17 such rows in production, all
            # reported as fault 500 because nothing checked the order.
            if rest and not getattr(field, "is_properties", False):
                raise UserError(
                    env._(
                        "Cannot sort '%(model)s' by '%(term)s': '%(head)s' is a "
                        "relation, and sorting across a relation is not "
                        "supported. Sort by a field of '%(model)s' itself.",
                        model=model_name,
                        term=parts[0],
                        head=head,
                    )
                )
    if unknown := _unknown_field_names(env, model_name, unknown):
        raise UserError(
            env._(
                "Unknown field(s) in the sort order for '%(model)s': "
                "%(fields)s. Call fields_get('%(model)s') for the fields this "
                "model actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_grouping(env, model_name: str, model_method: str, args, kwargs):
    """Reject a groupby/aggregate/having naming a field the model lacks.

    The fourth shape of the same caller mistake, after the field list, the
    domain and the order. A stale field in a ``read_group`` groupby or
    aggregate raised ``ValueError: Invalid field 'x' on model 'y'`` (or
    ``Invalid aggregate ...``) straight out of the ORM -- fault 500, with a
    traceback the log-viewer alerts on -- while the domain on the very same
    call was already pre-flighted.

    ``having`` is checked here rather than by ``check_domain`` because its
    left-hand sides are *aggregate specs* (``amount:sum``), which
    ``Domain.validate`` rejects as field names; only the leading name is ours.

    Only the leading field name of each spec is checked -- ``create_date`` of
    ``create_date:month``, ``amount`` of ``amount:sum`` -- matching the field
    group of core's own ``regex_read_group_spec`` and mirroring what
    ``check_domain``/``check_order`` do with a path's head. Granularity and
    aggregate-method names are left to core, so a well-formed spec is never
    falsely rejected. ``__count`` and other ``__``-prefixed pseudo-fields are
    skipped.

    :raise UserError: mapped to fault 400 by ``_classify_fault``.
    """
    names = []
    for container in arguments(model_method, GROUP, args, kwargs):
        names.extend(_leading_name(spec) for spec in _iter_grouping_specs(container))
    for having in arguments(model_method, HAVING, args, kwargs):
        names.extend(_domain_names(having))
    if unknown := _unknown_field_names(env, model_name, [n for n in names if n]):
        raise UserError(
            env._(
                "Unknown field(s) in the group specification for '%(model)s': "
                "%(fields)s. Call fields_get('%(model)s') for the fields this "
                "model actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_write_values(env, model_name: str, model_method: str, args, kwargs):
    """Reject a create/write/copy/web_save vals dict naming a missing field.

    The write-side twin of ``check_requested_fields``. A stale key raised a
    bare ``KeyError: 'field'`` (write) or ``ValueError: Invalid field`` (create,
    copy) from the ORM -- fault 500 with a traceback, and on the write path a
    half-applied or opaquely-failed change rather than merely absent data. The
    keys of a vals dict are always field names (Command tuples sit in the
    *values*), so checking them is exact, not a guess. Value *types* are left to
    core, the same boundary drawn for aggregate methods and domain operators.

    :raise UserError: mapped to fault 400 by ``_classify_fault``.
    """
    keys = [
        key for vals in _iter_vals_dicts(model_method, args, kwargs) for key in vals
    ]
    if unknown := _unknown_field_names(env, model_name, keys):
        raise UserError(
            env._(
                "Unknown field(s) on '%(model)s': %(fields)s. "
                "Call fields_get('%(model)s') for the fields this model "
                "actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_call(env, model_name: str, model_method: str, args, kwargs):
    """Run every pre-flight against one call.

    Both consumers ran the five in the same order with the same five arguments,
    which is the shape of one function rather than a convention each caller has
    to keep.

    The order is the one those call sites already used, deliberately, and not a
    tidier one: a call wrong in two ways reports whichever check runs first, so
    reordering changes the message a caller (and whatever greps its logs) has
    been getting. Measured: with the domain moved last, `search_read` carrying
    both a stale `order` and a stale domain field reports the order where it
    used to report the domain. Nothing is gained by that, so nothing is
    changed.

    :raise UserError: from whichever check refuses first.
    """
    check_requested_fields(env, model_name, model_method, args, kwargs)
    check_domain(env, model_name, model_method, args, kwargs)
    check_order(env, model_name, model_method, args, kwargs)
    check_grouping(env, model_name, model_method, args, kwargs)
    check_write_values(env, model_name, model_method, args, kwargs)
