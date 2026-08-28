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
caller-error diagnostics runs them before dispatch and maps the `UserError` to
its own protocol's 400.

Only field *names* are checked, never value types, and only the leading segment
of a dotted path -- the rest is resolved against comodels the ORM knows how to
walk. A wrong-typed value and an unknown operator stay the ORM's to reject, so a
well-formed call is never falsely refused.

They live here rather than beside a caller because two consumers already reach
for them and a third surface has the same problem: they are written against
``call_kw`` argument positions, not against anything one protocol owns.
"""

import difflib

from odoo.exceptions import UserError
from odoo.fields import Domain

# read/search_read both take the field list as their second positional
# argument, so one extractor covers both.
_FIELD_ARG_METHODS = frozenset({"read", "search_read"})

# web_read(specification) and web_search_read(domain, specification, ...) carry
# their field list as a *dict* whose keys are field names -- core does
# `list(specification)` and hands it to `read()` (see web/models/web_read.py),
# skipping any key that is not a field. So the same stale-field-name mistake
# `check_requested_fields` catches for read/search_read also silently drops
# data here, on the methods a modern client reaches for first. Only the
# TOP-LEVEL keys are field names and get checked; the nested sub-specifications
# (a relation's `fields`, its `context`, `limit`, ...) are core's to validate,
# which is why they are deliberately not walked.
#
# The int is the positional index of the spec when it is not the `specification`
# kwarg. It is 1 for both, for two different reasons `call_kw` makes the same:
# `web_read` is a *record* method, so args[0] is the ids and its own first
# parameter (the spec) is args[1] -- the very reason read/search_read read their
# field list from args[1] too; `web_search_read` is `@api.model`, so args[0] is
# the domain and the spec is args[1].
# `web_name_search(name, specification, domain, ...)` runs `web_read(spec)` on
# the hits, so its specification is the same field-name dict; it is `@api.model`
# with the name at args[0], so the spec is args[1] like the two above.
_SPEC_ARG_METHODS = {"web_read": 1, "web_search_read": 1, "web_name_search": 1}

# Methods whose first positional argument is a search domain.
_DOMAIN_ARG_METHODS = frozenset(
    {
        "search",
        "search_read",
        "search_count",
        "read_group",
        "formatted_read_group",
        "formatted_read_grouping_sets",
        "web_search_read",
        "web_read_group",
    }
)

# The domain of a search is `args[0]` for every method above, but two carry it
# elsewhere: `name_search(name, domain, ...)` at args[1] and
# `web_name_search(name, specification, domain, ...)` at args[2] (both
# `@api.model`, so no ids prefix). They were pre-flighted only when the caller
# passed `domain` as a kwarg; positionally, a stale field in the domain still
# reached the ORM as fault 500. This maps a method to the positional index of
# its domain when that index is not 0.
_DOMAIN_ARG_INDEX = {"name_search": 1, "web_name_search": 2}

# read_group-family methods. For every one of them the field-name-bearing
# specs -- the groupby list and the aggregate list, in whichever order the
# signature puts them -- sit in args[1] and args[2] (`having`, `limit`,
# `offset` come later and are left alone), or in the kwargs named below. The
# check is position-agnostic because it only extracts leading field names, and
# both a groupby spec and an aggregate spec name a field.
_GROUPING_ARG_METHODS = frozenset(
    {
        "read_group",
        "formatted_read_group",
        "formatted_read_grouping_sets",
        "web_read_group",
    }
)
_GROUPING_KWARGS = ("fields", "groupby", "aggregates", "grouping_sets")

# Write methods carrying a values dict whose keys are field names. A stale key
# there raised a bare `KeyError: 'field'` (write) or `ValueError: Invalid field`
# (create/copy) out of the ORM -- fault 500, the write-side twin of the read
# pre-flights, and worse because the write half-happens or fails opaquely. Each
# entry is (positional index of the values, kwarg name): `create` is
# `@api.model_create_multi`, so its values are args[0] and may be a single dict
# or a list of them; `write` and `copy` are record methods, so args[0] is the
# ids and the values dict is args[1] (`copy`'s `default` is optional).
# `name_create` takes a bare name, not a dict, so it is absent. Only field
# NAMES are checked, never value types -- a wrong-typed value is core's to
# reject, the same line drawn for aggregate methods and domain operators.
_VALS_ARG_METHODS = {
    "create": (0, "vals_list"),
    "write": (1, "vals"),
    "copy": (1, "default"),
}


def call_args(params: list) -> tuple[list, dict]:
    """The (args, kwargs) an execute_kw params tuple carries."""
    args = params[5] if len(params) > 5 and isinstance(params[5], list) else []
    kwargs = params[6] if len(params) > 6 and isinstance(params[6], dict) else {}
    return args, kwargs


def _requested_fields(model_method: str, args: list, kwargs: dict) -> list | None:
    """Return the field names a read/search_read/web_read call asked for.

    For read/search_read this is the field list; for web_read/web_search_read
    it is the top-level keys of the ``specification`` dict, which core treats as
    field names. Nested sub-specifications are not descended into.

    :return: the requested names, or ``None`` when this call does not carry a
        usable field list (wrong method, or omitted -- which means "all fields"
        and must not be validated)
    :rtype: list | None
    """
    if model_method in _FIELD_ARG_METHODS:
        fields = kwargs.get("fields")
        if fields is None and len(args) > 1:
            fields = args[1]
        if not isinstance(fields, list | tuple) or not fields:
            return None
        return list(fields)

    if model_method in _SPEC_ARG_METHODS:
        spec = kwargs.get("specification")
        if spec is None:
            index = _SPEC_ARG_METHODS[model_method]
            if len(args) > index:
                spec = args[index]
        if not isinstance(spec, dict) or not spec:
            return None
        return list(spec)

    return None


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


def domain_argument(model_method: str, args, kwargs):
    """The search domain a call carries, wherever its signature puts it.

    Its own function because the position is not uniform and getting it wrong
    is silent: `search` and friends take it at args[0], but `name_search` takes
    it at args[1] and `web_name_search` at args[2], behind their `name`
    argument. A caller that assumes args[0] finds the *name* string there,
    decides it is not a domain, and checks nothing at all.

    :return: the domain, or None when this call carries none
    """
    domain = kwargs.get("domain")
    if domain is not None:
        return domain
    index = (
        0
        if model_method in _DOMAIN_ARG_METHODS
        else _DOMAIN_ARG_INDEX.get(model_method)
    )
    if index is None or len(args) <= index:
        return None
    return args[index]


def mentioned_field_names(model_method: str, args, kwargs) -> list[str]:
    """Every field name a call mentions, in whichever shape it mentions it.

    The union of what the five checks above look at -- the field list or
    specification, the domain, the order, the group specification and the
    values dict -- flattened to leading names. Separate from those checks
    because it answers a different question: they ask "does this name exist",
    this asks "which names are named", which is what a policy about *particular*
    fields needs.

    Leading names only: `partner_id` from `partner_id.name`, `create_date` from
    `create_date:month`. A path's tail resolves against a comodel with its own
    policy, and a granularity or aggregate suffix is not a field.

    Best-effort by construction: a malformed domain yields no names rather than
    raising, because a caller that cannot be parsed is one the ORM will refuse
    anyway, and a policy check is not the place to report syntax.
    """
    names: list[str] = []

    requested = _requested_fields(model_method, args, kwargs)
    if requested:
        names.extend(str(name) for name in requested)

    domain = domain_argument(model_method, args, kwargs)
    if isinstance(domain, list | tuple):
        try:
            parsed = Domain(list(domain))
        except ValueError, TypeError:
            parsed = None
        if parsed is not None:
            names.extend(
                _leading_name(str(condition.field_expr))
                for condition in parsed.iter_conditions()
            )

    order = kwargs.get("order")
    if order and isinstance(order, str):
        names.extend(
            _leading_name(term.strip().split()[0])
            for term in order.split(",")
            if term.strip()
        )

    if model_method in _GROUPING_ARG_METHODS:
        containers = [kwargs[key] for key in _GROUPING_KWARGS if key in kwargs]
        containers.extend(args[1:3])
        for container in containers:
            names.extend(
                _leading_name(spec) for spec in _iter_grouping_specs(container)
            )

    if model_method in _VALS_ARG_METHODS:
        for vals in _iter_vals_dicts(model_method, args, kwargs):
            names.extend(str(key) for key in vals)

    return [name for name in names if name]


def _leading_name(spec: str) -> str:
    """The field a spec leads with: `x` from `x.y`, `x:month`, `x desc`."""
    return spec.split(":", 1)[0].split(".", 1)[0].strip()


def check_requested_fields(env, model_name: str, model_method: str, args, kwargs):
    """Reject a read/search_read/web_read naming fields the model does not have.

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

    model_fields = env[model_name]._fields
    unknown = [f for f in requested if not isinstance(f, str) or f not in model_fields]
    if not unknown:
        return

    known = sorted(model_fields)
    raise UserError(
        env._(
            "Unknown field(s) on '%(model)s': %(fields)s. "
            "Call fields_get('%(model)s') for the fields this model actually has.",
            model=model_name,
            fields=", ".join(_describe_unknown(n, known) for n in unknown),
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
    known = sorted(model._fields)
    unknown = []
    for condition in parsed.iter_conditions():
        head = str(condition.field_expr).split(".", 1)[0].split(":", 1)[0]
        if head and head not in model._fields and head not in unknown:
            unknown.append(head)
    if unknown:
        raise UserError(
            env._(
                "Unknown field(s) in the domain for '%(model)s': %(fields)s. "
                "Call fields_get('%(model)s') for the fields this model "
                "actually has.",
                model=model_name,
                fields=", ".join(_describe_unknown(n, known) for n in unknown),
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


def check_order(env, model_name: str, kwargs: dict):
    """Reject an ``order`` naming fields the model does not have.

    The third shape of the same caller mistake, after the field list and the
    domain. ``order`` is a comma-separated "field [asc|desc]" list and a stale
    name raised ``ValueError: Invalid field 'x' on model 'y'`` straight out of
    the ORM -- fault 500, with a traceback in the log.

    :raise UserError: mapped to fault 400 by ``_classify_fault``.
    """
    order = kwargs.get("order")
    if not order or not isinstance(order, str):
        return

    model_fields = env[model_name]._fields
    unknown = []
    for term in order.split(","):
        parts = term.strip().split()
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
                    "relation, and sorting across a relation is not supported. "
                    "Sort by a field of '%(model)s' itself.",
                    model=model_name,
                    term=parts[0],
                    head=head,
                )
            )
    if not unknown:
        return

    known = sorted(model_fields)
    raise UserError(
        env._(
            "Unknown field(s) in the sort order for '%(model)s': %(fields)s. "
            "Call fields_get('%(model)s') for the fields this model actually has.",
            model=model_name,
            fields=", ".join(_describe_unknown(n, known) for n in unknown),
        )
    )


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


def check_grouping(env, model_name: str, model_method: str, args, kwargs):
    """Reject a groupby/aggregate naming a field the model does not have.

    The fourth shape of the same caller mistake, after the field list, the
    domain and the order. A stale field in a ``read_group`` groupby or
    aggregate raised ``ValueError: Invalid field 'x' on model 'y'`` (or
    ``Invalid aggregate ...``) straight out of the ORM -- fault 500, with a
    traceback the log-viewer alerts on -- while the domain on the very same
    call was already pre-flighted.

    Only the leading field name of each spec is checked -- ``create_date`` of
    ``create_date:month``, ``amount`` of ``amount:sum`` -- matching the field
    group of core's own ``regex_read_group_spec`` and mirroring what
    ``check_domain``/``check_order`` do with a path's head. Granularity and
    aggregate-method names are left to core, so a well-formed spec is never
    falsely rejected. ``__count`` and other ``__``-prefixed pseudo-fields are
    skipped.

    :raise UserError: mapped to fault 400 by ``_classify_fault``.
    """
    if model_method not in _GROUPING_ARG_METHODS:
        return

    containers = [kwargs[key] for key in _GROUPING_KWARGS if key in kwargs]
    containers.extend(args[1:3])

    model_fields = env[model_name]._fields
    unknown = []
    for container in containers:
        for spec in _iter_grouping_specs(container):
            head = spec.split(":", 1)[0].split(".", 1)[0]
            if not head or head.startswith("__"):
                continue
            if head not in model_fields and head not in unknown:
                unknown.append(head)
    if not unknown:
        return

    known = sorted(model_fields)
    raise UserError(
        env._(
            "Unknown field(s) in the group specification for '%(model)s': "
            "%(fields)s. Call fields_get('%(model)s') for the fields this model "
            "actually has.",
            model=model_name,
            fields=", ".join(_describe_unknown(n, known) for n in unknown),
        )
    )


def _iter_vals_dicts(model_method: str, args, kwargs):
    """Yield the values dict(s) a create/write/copy call carries.

    ``create`` may pass a single dict or a list of them; ``write``/``copy`` pass
    one. The values sit at the positional index recorded for the method, or in
    its kwarg. A non-dict (a bare ``copy`` with no override, a malformed call)
    yields nothing rather than raising.
    """
    index, kw = _VALS_ARG_METHODS[model_method]
    vals = kwargs.get(kw)
    if vals is None and len(args) > index:
        vals = args[index]
    if isinstance(vals, dict):
        yield vals
    elif isinstance(vals, list | tuple):
        for item in vals:
            if isinstance(item, dict):
                yield item


def check_write_values(env, model_name: str, model_method: str, args, kwargs):
    """Reject a create/write/copy vals dict naming a field the model lacks.

    The write-side twin of ``check_requested_fields``. A stale key raised a
    bare ``KeyError: 'field'`` (write) or ``ValueError: Invalid field`` (create,
    copy) from the ORM -- fault 500 with a traceback, and on the write path a
    half-applied or opaquely-failed change rather than merely absent data. The
    keys of a vals dict are always field names (Command tuples sit in the
    *values*), so checking them is exact, not a guess. Value *types* are left to
    core, the same boundary drawn for aggregate methods and domain operators.

    :raise UserError: mapped to fault 400 by ``_classify_fault``.
    """
    if model_method not in _VALS_ARG_METHODS:
        return

    model_fields = env[model_name]._fields
    unknown = []
    for vals in _iter_vals_dicts(model_method, args, kwargs):
        for key in vals:
            if isinstance(key, str) and key not in model_fields and key not in unknown:
                unknown.append(key)
    if not unknown:
        return

    known = sorted(model_fields)
    raise UserError(
        env._(
            "Unknown field(s) on '%(model)s': %(fields)s. "
            "Call fields_get('%(model)s') for the fields this model actually has.",
            model=model_name,
            fields=", ".join(_describe_unknown(n, known) for n in unknown),
        )
    )
