import ast
import collections.abc
import itertools
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Self

from lxml import etree

from odoo import api, fields
from odoo.fields import Command
from odoo.models import BaseModel
from odoo.tools.safe_eval import safe_eval

if TYPE_CHECKING:
    import types
    from collections.abc import Callable, Generator, Iterator

_logger = logging.getLogger(__name__)

MODIFIER_ALIASES = {"1": "True", "0": "False"}


def _combine_bool_exprs(op: str, expr1: Any, expr2: Any) -> str:
    expr1, expr2 = str(expr1), str(expr2)
    absorbing, neutral = ("True", "False") if op == "or" else ("False", "True")
    if absorbing in (expr1, expr2):
        return absorbing
    if expr1 == neutral:
        return expr2
    if expr2 == neutral:
        return expr1
    return f"({expr1}) {op} ({expr2})"


class Form:
    def __init__(
        self, record: BaseModel, view: int | str | BaseModel | None = None
    ) -> None:
        assert isinstance(record, BaseModel)
        assert len(record) <= 1

        self._record = record
        self._env = record.env

        if isinstance(view, BaseModel):
            assert view._name == "ir.ui.view", (
                "the view parameter must be a view id, xid or record, got %s" % view
            )
            view_id = view.id
        elif isinstance(view, str):
            view_id = record.env.ref(view).id
        else:
            view_id = view or False

        views = record.get_views([(view_id, "form")])
        self._models_info = views["models"]
        tree = etree.fromstring(views["views"]["form"]["arch"])
        view = self._process_view(tree, record)
        self._view = view

        self._values = UpdateDict()
        if record:
            self._init_from_record()
        else:
            self._init_from_defaults()

    @classmethod
    def from_action(cls, env: api.Environment, action: dict) -> Form:
        assert action["type"] == "ir.actions.act_window", (
            f"only window actions are valid, got {action['type']}"
        )
        if views := action.get("views"):
            assert views[0][1] == "form", (
                f"the actions dict should have a form as first view, got {views[0][1]}"
            )
            view_id = views[0][0]
        else:
            view_mode = action.get("view_mode", "")
            if not view_mode.startswith("form"):
                raise ValueError(
                    f"The actions dict should have a form first view mode, got {view_mode}"
                )
            view_id = action.get("view_id")
            if view_id and "," in view_mode:
                raise ValueError(
                    f"A `view_id` is only valid if the action has a single `view_mode`, got {view_mode}"
                )
        context = action.get("context", {})
        if isinstance(context, str):
            context = ast.literal_eval(context)
        record = (
            env[action["res_model"]].with_context(context).browse(action.get("res_id"))
        )

        return cls(record, view_id)

    def _process_view(self, tree: Any, model: BaseModel, level: int = 2) -> dict:
        fields = {"id": {"type": "id"}}
        fields_spec = {}
        modifiers = {"id": {"required": "False", "readonly": "True"}}
        contexts = {}
        flevel = tree.xpath("count(ancestor::field)")
        daterange_field_names = {}
        field_infos = self._models_info.get(model._name, {}).get("fields", {})

        for node in tree.xpath(f".//field[count(ancestor::field) = {flevel}]"):
            field_name = node.get("name")

            field_info = dict(field_infos.get(field_name) or {"type": None})
            fields[field_name] = field_info
            fields_spec[field_name] = field_spec = {}

            field_modifiers = {}
            for attr in (
                "required",
                "readonly",
                "invisible",
                "column_invisible",
            ):
                default = attr in ("required", "readonly") and field_info.get(
                    attr, False
                )
                expr = node.get(attr) or str(default)
                field_modifiers[attr] = MODIFIER_ALIASES.get(expr, expr)

            for ancestor in node.xpath(
                f"ancestor::*[@invisible][count(ancestor::field) = {flevel}]"
            ):
                field_modifiers["invisible"] = _combine_bool_exprs(
                    "or", ancestor.get("invisible"), field_modifiers["invisible"]
                )

            if field_name in modifiers:
                for modifier, expr in modifiers[field_name].items():
                    field_modifiers[modifier] = _combine_bool_exprs(
                        "and", expr, field_modifiers[modifier]
                    )

            modifiers[field_name] = field_modifiers

            ctx = node.get("context")
            if ctx:
                contexts[field_name] = ctx
                field_spec["context"] = get_static_context(ctx)

            if node.get("widget") == "many2many":
                field_info["type"] = node.get("widget")
            elif node.get("widget") == "daterange":
                options = ast.literal_eval(node.get("options", "{}"))
                related_field = options.get("start_date_field") or options.get(
                    "end_date_field"
                )
                if related_field:
                    daterange_field_names[related_field] = field_name
                else:
                    _logger.warning(
                        "daterange widget on field %r has neither"
                        " start_date_field nor end_date_field option",
                        field_name,
                    )

            if field_info["type"] == "one2many":
                if level:
                    field_info["invisible"] = field_modifiers.get("invisible")
                    edition_view = self._get_one2many_edition_view(
                        field_info, node, level
                    )
                    field_info["edition_view"] = edition_view
                    field_spec["fields"] = edition_view["fields_spec"]
                else:
                    field_info["type"] = "many2many"

        for related_field, start_field in daterange_field_names.items():
            if related_field not in modifiers:
                field_info = dict(field_infos.get(related_field) or {"type": None})
                fields[related_field] = field_info
                fields_spec[related_field] = {}
                modifiers[related_field] = {
                    "required": field_info.get("required", False),
                    "readonly": field_info.get("readonly", False),
                }
            modifiers[related_field]["invisible"] = modifiers[start_field].get(
                "invisible", False
            )

        return {
            "tree": tree,
            "fields": fields,
            "fields_spec": fields_spec,
            "modifiers": modifiers,
            "contexts": contexts,
            "onchange": model._onchange_spec({"arch": etree.tostring(tree)}),
        }

    def _get_one2many_edition_view(
        self, field_info: dict, node: Any, level: int
    ) -> dict:
        submodel = self._env[field_info["relation"]]

        views = {view.tag: view for view in node.xpath("./*[descendant::field]")}
        for view_type in ["list", "form"]:
            if view_type in views:
                continue
            if field_info["invisible"] == "True":
                views[view_type] = etree.Element(view_type)
                continue
            refs = self._env["ir.ui.view"]._get_view_refs(node)
            subviews = submodel.with_context(**refs).get_views([(None, view_type)])
            subnode = etree.fromstring(subviews["views"][view_type]["arch"])
            views[view_type] = subnode
            node.append(subnode)
            for model_name, value in subviews["models"].items():
                model_info = self._models_info.setdefault(model_name, {})
                if "fields" not in model_info:
                    model_info["fields"] = {}
                model_info["fields"].update(value["fields"])

        view_type = next(
            (vtype for vtype in node.get("mode", "list").split(",") if vtype != "form"),
            "form",
        )
        if not (view_type == "list" and views["list"].get("editable")):
            view_type = "form"

        return self._process_view(views[view_type], submodel, level=level - 1)

    def __str__(self) -> str:
        return f"<{type(self).__name__} {self._record}>"

    def _init_from_record(self) -> None:
        assert self._record.id, "editing unstored records is not supported"
        self._values.clear()

        [record_values] = self._record.web_read(self._view["fields_spec"])
        self._env.flush_all()
        self._env.clear()

        values = convert_read_to_form(record_values, self._view["fields"])
        self._values.update(values)

    def _init_from_defaults(self) -> None:
        vals = self._values
        vals["id"] = False

        self._perform_onchange()
        self._values._changed.update(self._view["fields"])

    def __getattr__(self, field_name: str) -> Any:
        if field_name.startswith("_"):
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {field_name!r}"
            )
        return self[field_name]

    def __getitem__(self, field_name: str) -> Any:
        field_info = self._view["fields"].get(field_name)
        assert field_info is not None, f"{field_name!r} was not found in the view"

        value = self._values[field_name]
        if field_info["type"] == "many2one":
            Model = self._env[field_info["relation"]]
            return Model.browse(value)
        elif field_info["type"] == "one2many":
            return O2MProxy(self, field_name)
        elif field_info["type"] == "many2many":
            return M2MProxy(self, field_name)
        return value

    def __setattr__(self, field_name: str, value: Any) -> None:
        # Mirrors __getattr__: private names are real attributes, public ones
        # are view fields. Without this, every internal assignment in Form and
        # O2MForm had to spell object.__setattr__.
        if field_name.startswith("_"):
            object.__setattr__(self, field_name, value)
        else:
            self[field_name] = value

    def __setitem__(self, field_name: str, value: Any) -> None:
        field_info = self._view["fields"].get(field_name)
        assert field_info is not None, f"{field_name!r} was not found in the view"
        assert field_info["type"] != "one2many", (
            "Can't set an one2many field directly, use its proxy instead"
        )
        assert not self._get_modifier(field_name, "readonly"), (
            f"can't write on readonly field {field_name!r}"
        )
        assert not self._get_modifier(field_name, "invisible"), (
            f"can't write on invisible field {field_name!r}"
        )

        if field_info["type"] == "many2many":
            return M2MProxy(self, field_name).set(value)

        if field_info["type"] == "many2one":
            assert (
                isinstance(value, BaseModel) and value._name == field_info["relation"]
            )
            value = value.id

        self._values[field_name] = value
        self._perform_onchange(field_name)
        return None

    def _get_modifier(
        self,
        field_name: str,
        modifier: str,
        *,
        view: dict | None = None,
        vals: dict | None = None,
    ) -> bool:
        if view is None:
            view = self._view

        expr = view["modifiers"][field_name].get(modifier, False)
        if isinstance(expr, bool):
            return expr
        if expr in ("True", "False"):
            return expr == "True"

        if vals is None:
            vals = self._values

        eval_context = self._get_eval_context(vals)

        return bool(safe_eval(expr, eval_context))

    def _get_context(self, field_name: str) -> dict:
        context_str = self._view["contexts"].get(field_name)
        if not context_str:
            return {}
        eval_context = self._get_eval_context()
        return safe_eval(context_str, eval_context)

    def _get_eval_context(self, values: dict | None = None) -> dict:
        context = {
            "id": self._record.id,
            "active_id": self._record.id,
            "active_ids": self._record.ids,
            "active_model": self._record._name,
            "current_date": date.today().strftime("%Y-%m-%d"),
            **self._env.context,
        }
        if values is None:
            values = self._get_all_values()
        return {
            **context,
            "context": context,
            **values,
        }

    def _get_all_values(self) -> dict:
        return self._get_values("all")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        if not exc_type:
            self.save()

    def save(self) -> BaseModel:
        values = self._get_save_values()
        if not self._record or values:
            [record_values] = self._record.web_save(values, self._view["fields_spec"])
            self._env.flush_all()
            self._env.clear()

            if not self._record:
                record = self._record.browse(record_values["id"])
                self._record = record

            values = convert_read_to_form(record_values, self._view["fields"])
            self._values.clear()
            self._values.update(values)

        return self._record

    @property
    def record(self) -> BaseModel:
        assert not self._values._changed
        return self._record

    def _get_save_values(self) -> dict:
        return self._get_values("save")

    def _get_values(
        self,
        mode: str,
        values: UpdateDict | None = None,
        view: dict | None = None,
        modifiers_values: dict | None = None,
        parent_link: str | None = None,
    ) -> dict:
        assert mode in ("save", "onchange", "all")

        if values is None:
            values = self._values
        if view is None:
            view = self._view
        assert isinstance(values, UpdateDict)

        modifiers_values = modifiers_values or values

        result = {}
        for field_name, field_info in view["fields"].items():
            if field_name == "id" or field_name not in values:
                continue

            value = values[field_name]

            if (
                mode == "save"
                and value is False
                and field_name != parent_link
                and field_info["type"] != "boolean"
                and not self._get_modifier(
                    field_name, "invisible", view=view, vals=modifiers_values
                )
                and not self._get_modifier(
                    field_name,
                    "column_invisible",
                    view=view,
                    vals=modifiers_values,
                )
                and self._get_modifier(
                    field_name, "required", view=view, vals=modifiers_values
                )
            ):
                raise AssertionError(
                    f"{field_name} is a required field ({view['modifiers'][field_name]})"
                )

            if mode in ("save", "onchange") and field_name not in values._changed:
                continue

            if mode == "save" and self._get_modifier(
                field_name, "readonly", view=view, vals=modifiers_values
            ):
                field_node = next(
                    node
                    for node in view["tree"].iter("field")
                    if node.get("name") == field_name
                )
                if not field_node.get("force_save"):
                    continue

            if field_info["type"] == "one2many":
                if mode == "all":
                    value = list(value)
                else:
                    subview = field_info["edition_view"]
                    value = value.to_commands(
                        lambda vals, subview=subview, field_info=field_info: (
                            self._get_values(
                                mode,
                                vals,
                                subview,
                                modifiers_values={
                                    "id": False,
                                    **vals,
                                    "parent": Dotter(values),
                                },
                                parent_link=field_info.get("relation_field"),
                            )
                        )
                    )

            elif field_info["type"] == "many2many":
                if mode == "all":
                    value = list(value)
                else:
                    value = value.to_commands()

            result[field_name] = value

        return result

    def _perform_onchange(self, field_name: str | None = None) -> dict | None:
        assert field_name is None or isinstance(field_name, str)

        if field_name:
            field_names = [field_name]
            self._values._changed.add(field_name)
        else:
            field_names = []

        # .get: a field can be in self._view["fields"] without being in
        # ["onchange"], which is built once from the view tree. The daterange
        # fix-up registers the related start/end field in fields, fields_spec
        # and modifiers, but _onchange_spec only walks <field> nodes and that
        # partner field has none -- so assigning it raised KeyError here instead
        # of simply having no onchange to run, which is what a falsy spec means.
        if field_name and not self._view["onchange"].get(field_name):
            return None

        record = self._record

        if field_name:
            context = self._get_context(field_name)
            if context:
                record = record.with_context(**context)

        values = self._get_onchange_values()
        result = record.onchange(values, field_names, self._view["fields_spec"])
        self._env.flush_all()
        self._env.clear()

        if w := result.get("warning"):
            if isinstance(w, collections.abc.Mapping) and w.keys() >= {
                "title",
                "message",
            }:
                _logger.getChild("onchange").warning("%(title)s %(message)s", w)
            else:
                _logger.getChild("onchange").error(
                    "received invalid warning %r from onchange on %r (should be a dict with keys `title` and `message`)",
                    w,
                    field_names,
                )

        if not field_name:
            self._values.update(
                {
                    field_name: _cleanup_from_default(field_info["type"], False)
                    for field_name, field_info in self._view["fields"].items()
                    if field_name not in self._values
                }
            )

        if result.get("value"):
            self._apply_onchange(result["value"])

        return result

    def _get_onchange_values(self) -> dict:
        return self._get_values("onchange")

    def _apply_onchange(self, values: dict) -> None:
        self._apply_onchange_values(self._values, self._view["fields"], values)

    def _apply_onchange_values(
        self, values: UpdateDict, fields: dict, onchange_values: dict
    ) -> None:
        assert isinstance(values, UpdateDict)
        for fname, value in onchange_values.items():
            field_info = fields[fname]
            if field_info["type"] in ("one2many", "many2many"):
                subfields = {}
                if field_info["type"] == "one2many":
                    subfields = field_info["edition_view"]["fields"]
                field_value = values[fname]
                for cmd in value:
                    match cmd[0]:
                        case Command.CREATE:
                            vals = UpdateDict(
                                convert_read_to_form(
                                    dict.fromkeys(subfields, False), subfields
                                )
                            )
                            self._apply_onchange_values(vals, subfields, cmd[2])
                            field_value.create(vals)
                        case Command.UPDATE:
                            vals = field_value.get_vals(cmd[1])
                            self._apply_onchange_values(vals, subfields, cmd[2])
                        case Command.DELETE | Command.UNLINK:
                            field_value.remove(cmd[1])
                        case Command.LINK:
                            field_value.add(
                                cmd[1], convert_read_to_form(cmd[2], subfields)
                            )
                        case c:
                            raise ValueError(f"Unexpected onchange() o2m command {c!r}")
            else:
                values[fname] = value
            values._changed.add(fname)


class O2MForm(Form):
    def __init__(self, proxy: O2MProxy, index: int | None = None) -> None:
        model = proxy._model
        self._proxy = proxy
        self._index = index

        self._record = model
        self._env = model.env

        self._models_info = proxy._form._models_info
        self._view = proxy._field_info["edition_view"]

        self._values = UpdateDict()
        if index is None:
            self._init_from_defaults()
        else:
            vals = proxy._records[index]
            self._values.update(vals)
            if vals.get("id"):
                self._record = model.browse(vals["id"])

    def _get_modifier(
        self,
        field_name: str,
        modifier: str,
        *,
        view: dict | None = None,
        vals: dict | None = None,
    ) -> bool:
        if modifier != "required" and self._proxy._form._get_modifier(
            self._proxy._field, modifier
        ):
            return True
        return super()._get_modifier(field_name, modifier, view=view, vals=vals)

    def _get_eval_context(self, values: dict | None = None) -> dict:
        eval_context = super()._get_eval_context(values)
        eval_context["parent"] = Dotter(self._proxy._form._values)
        return eval_context

    def _get_onchange_values(self) -> dict:
        values = super()._get_onchange_values()
        field_info = self._proxy._field_info
        if "relation_field" in field_info:
            parent_form = self._proxy._form
            parent_values = parent_form._get_onchange_values()
            if parent_form._record.id:
                parent_values["id"] = parent_form._record.id
            values[field_info["relation_field"]] = parent_values
        return values

    def save(self) -> None:
        proxy = self._proxy
        field_value = proxy._form._values[proxy._field]
        values = self._get_save_values()
        if self._index is None:
            field_value.create(values)
        else:
            id_ = field_value[self._index]
            field_value.update(id_, values)

        proxy._form._perform_onchange(proxy._field)

    def _get_save_values(self) -> UpdateDict:
        values = UpdateDict(self._values)

        for field_name in self._view["fields"]:
            if self._get_modifier(field_name, "required") and not (
                self._get_modifier(field_name, "column_invisible")
                or self._get_modifier(field_name, "invisible")
            ):
                assert values[field_name] is not False, (
                    f"{field_name!r} is a required field"
                )

        return values


class UpdateDict(dict):
    _changed: set

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._changed = set()
        if args and isinstance(args[0], UpdateDict):
            self._changed.update(args[0]._changed)

    def __repr__(self) -> str:
        items = [
            f"{key!r}{'*' if key in self._changed else ''}: {val!r}"
            for key, val in self.items()
        ]
        return f"{{{', '.join(items)}}}"

    def changed_items(self) -> Generator[tuple]:
        return ((k, v) for k, v in self.items() if k in self._changed)

    def update(self, *args: Any, **kw: Any) -> None:
        super().update(*args, **kw)
        if args and isinstance(args[0], UpdateDict):
            self._changed.update(args[0]._changed)

    def clear(self) -> None:
        super().clear()
        self._changed.clear()


class X2MValue(collections.abc.Sequence):
    _virtual_seq = itertools.count()

    __hash__ = None

    def __init__(self, iterable_of_vals: Any = ()) -> None:
        self._data: dict[Any, UpdateDict] = {
            vals["id"]: UpdateDict(vals) for vals in iterable_of_vals
        }
        self._given: list = list(self._data)
        self._keys: list | None = None

    def __repr__(self) -> str:
        return repr(self._data)

    def __contains__(self, id_: Any) -> bool:
        return id_ in self._data

    def __getitem__(self, index: Any) -> Any:
        # A dict view is not indexable, so an index needs a list -- but
        # rebuilding it per access made indexed iteration quadratic (measured
        # n*4 -> time*154). Cached, and dropped by every mutator below.
        if self._keys is None:
            self._keys = list(self._data)
        return self._keys[index]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        return list(self) == other

    def get_vals(self, id_: Any) -> UpdateDict:
        return self._data[id_]

    def add(self, id_: Any, vals: dict) -> None:
        if id_ in self._data:
            self._data[id_].update(vals)
            return
        self._data[id_] = UpdateDict(vals)
        self._keys = None

    def remove(self, id_: Any) -> None:
        self._data.pop(id_, None)
        self._keys = None

    def clear(self) -> None:
        self._data.clear()
        self._keys = None

    def create(self, vals: dict) -> None:
        id_ = f"virtual_{next(self._virtual_seq)}"
        create_vals = UpdateDict(vals)
        create_vals._changed.update(vals)
        self._data[id_] = create_vals
        self._keys = None

    def update(self, id_: Any, changes: dict, changed: Any = ()) -> None:
        vals = self._data[id_]
        vals.update(changes)
        vals._changed.update(changed)

    def to_list_of_vals(self) -> list[UpdateDict]:
        return list(self._data.values())

    def _to_commands(
        self,
        convert_values: Callable[[UpdateDict], Any],
        removal_command: Callable[[Any], Any],
    ) -> list:
        given = set(self._given)
        result = []
        for id_, vals in self._data.items():
            if isinstance(id_, str) and id_.startswith("virtual_"):
                result.append((Command.CREATE, id_, convert_values(vals)))
                continue
            if id_ not in given:
                result.append(Command.link(id_))
            if vals._changed:
                result.append(Command.update(id_, convert_values(vals)))
        result.extend(
            removal_command(id_) for id_ in self._given if id_ not in self._data
        )
        return result


class O2MValue(X2MValue):
    def to_commands(
        self, convert_values: Callable[[UpdateDict], Any] = lambda vals: vals
    ) -> list:
        return self._to_commands(convert_values, Command.delete)


class M2MValue(X2MValue):
    @staticmethod
    def _convert_changed(vals: UpdateDict) -> dict:
        return {
            key: val.to_commands() if isinstance(val, X2MValue) else val
            for key, val in vals.changed_items()
        }

    def to_commands(self) -> list:
        return self._to_commands(self._convert_changed, Command.unlink)


class X2MProxy:
    _form: Form | None = None
    _field: str | None = None
    _field_info: dict | None = None

    def __init__(self, form: Form, field_name: str) -> None:
        self._form = form
        self._field = field_name
        self._field_info = form._view["fields"][field_name]
        self._field_value: X2MValue = form._values[field_name]

    @property
    def ids(self) -> list:
        return list(self._field_value)

    def _assert_editable(self) -> None:
        assert not self._form._get_modifier(self._field, "readonly"), (
            f"field {self._field!r} is not editable"
        )
        assert not self._form._get_modifier(self._field, "invisible"), (
            f"field {self._field!r} is not visible"
        )


class O2MProxy(X2MProxy):
    def __len__(self) -> int:
        return len(self._field_value)

    @property
    def _model(self) -> BaseModel:
        model = self._form._env[self._field_info["relation"]]
        context = self._form._get_context(self._field)
        if context:
            model = model.with_context(**context)
        return model

    @property
    def _records(self) -> list[UpdateDict]:
        return self._field_value.to_list_of_vals()

    def new(self) -> O2MForm:
        self._assert_editable()
        return O2MForm(self)

    def edit(self, index: int) -> O2MForm:
        self._assert_editable()
        return O2MForm(self, index)

    def remove(self, index: int) -> None:
        self._assert_editable()
        self._field_value.remove(self._field_value[index])
        self._form._perform_onchange(self._field)


class M2MProxy(X2MProxy, collections.abc.Sequence):
    def __getitem__(self, index: Any) -> BaseModel:
        comodel_name = self._field_info["relation"]
        return self._form._env[comodel_name].browse(self._field_value[index])

    def __len__(self) -> int:
        return len(self._field_value)

    def __iter__(self) -> Iterator[BaseModel]:
        comodel_name = self._field_info["relation"]
        records = self._form._env[comodel_name].browse(self._field_value)
        return iter(records)

    def __contains__(self, record: Any) -> bool:
        comodel_name = self._field_info["relation"]
        assert isinstance(record, BaseModel) and record._name == comodel_name
        return record.id in self._field_value

    def add(self, record: BaseModel) -> None:
        self._assert_editable()
        parent = self._form
        comodel_name = self._field_info["relation"]
        assert isinstance(record, BaseModel) and record._name == comodel_name, (
            f"trying to assign a {record._name!r} object to a {comodel_name!r} field"
        )

        if record.id not in self._field_value:
            self._field_value.add(record.id, {"id": record.id})
            parent._perform_onchange(self._field)

    def remove(self, id: Any = None, index: int | None = None) -> None:
        self._assert_editable()
        assert (id is None) ^ (index is None), "can remove by either id or index"
        if id is None:
            id = self._field_value[index]
        self._field_value.remove(id)
        self._form._perform_onchange(self._field)

    def set(self, records: BaseModel) -> None:
        self._assert_editable()
        comodel_name = self._field_info["relation"]
        assert isinstance(records, BaseModel) and records._name == comodel_name, (
            f"trying to assign a {records._name!r} object to a {comodel_name!r} field"
        )

        if set(records.ids) != set(self._field_value):
            self._field_value.clear()
            for id_ in records.ids:
                self._field_value.add(id_, {"id": id_})
            self._form._perform_onchange(self._field)

    def clear(self) -> None:
        self._assert_editable()
        self._field_value.clear()
        self._form._perform_onchange(self._field)


def convert_read_to_form(values: dict, model_fields: dict) -> dict:
    result = {}
    for fname, value in values.items():
        field_info = {"type": "id"} if fname == "id" else model_fields[fname]
        if field_info["type"] == "one2many":
            if "edition_view" in field_info:
                subfields = field_info["edition_view"]["fields"]
                value = O2MValue(
                    convert_read_to_form(vals, subfields) for vals in (value or ())
                )
            else:
                value = O2MValue({"id": id_} for id_ in (value or ()))
        elif field_info["type"] == "many2many":
            value = M2MValue({"id": id_} for id_ in (value or ()))
        elif field_info["type"] == "datetime" and isinstance(value, datetime):
            value = fields.Datetime.to_string(value)
        elif field_info["type"] == "date" and isinstance(value, date):
            value = fields.Date.to_string(value)
        result[fname] = value
    return result


def _cleanup_from_default(type_: str, value: Any) -> Any:
    if not value:
        if type_ == "one2many":
            return O2MValue()
        elif type_ == "many2many":
            return M2MValue()
        elif type_ in ("integer", "float"):
            return 0
        return value

    if type_ == "one2many":
        raise NotImplementedError
    if type_ == "datetime" and isinstance(value, datetime):
        return fields.Datetime.to_string(value)
    elif type_ == "date" and isinstance(value, date):
        return fields.Date.to_string(value)
    return value


def get_static_context(context_str: str) -> dict:
    context_ast = ast.parse(context_str.strip(), mode="eval").body
    assert isinstance(context_ast, ast.Dict)
    result = {}
    for key_ast, val_ast in zip(context_ast.keys, context_ast.values, strict=False):
        try:
            key = ast.literal_eval(key_ast)
            val = ast.literal_eval(val_ast)
            result[key] = val
        except ValueError:
            pass
    return result


class Dotter:
    __slots__ = ["__values"]

    def __init__(self, values: dict) -> None:
        self.__values = values

    def __getattr__(self, key: str) -> Any:
        val = self.__values[key]
        return Dotter(val) if isinstance(val, dict) else val
