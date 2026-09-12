import ast
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

PCT_REF_RE = re.compile(r"%%|%\((.*?)\)[ds]")

EXPRESSION_ATTRIBUTES = frozenset(
    {
        "domain",
        "filter_domain",
        "context",
        "options",
        "invisible",
        "column_invisible",
        "readonly",
        "required",
    }
)

REMOVED_ATTRIBUTES = frozenset({"attrs", "states"})

OPTIONAL_VALUES = frozenset({"show", "hide", "conditional"})

KANBAN_ENTRY_TEMPLATES = frozenset({"card", "menu"})

_BARE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_HASCLASS_RE = re.compile(r"\bhasclass\(")

_COMMAND_CODES = frozenset(range(7))


@dataclass(frozen=True, slots=True)
class DataFile:
    path: str
    module: str
    root: etree._Element
    listed: bool
    loaded_from_python: bool

    def elements(self) -> Iterator[etree._Element]:
        for element in self.root.iter():
            if not callable(element.tag):
                yield element

    def records(self, model: str | None = None) -> Iterator[etree._Element]:
        for record in self.root.iter("record"):
            if model is None or record.get("model") == model:
                yield record

    def model_view_archs(self) -> Iterator[tuple[etree._Element, etree._Element]]:
        for record in self.records("ir.ui.view"):
            model = record.find("field[@name='model']")
            if model is None or not (model.text or "").strip():
                continue
            arch = record.find("field[@name='arch']")
            if arch is not None:
                yield record, arch


@dataclass(frozen=True, slots=True)
class Context:
    declared_models: frozenset[str]
    known_modules: frozenset[str]


type Check = Callable[[DataFile, Context], Iterable[tuple[int, str]]]


@dataclass(frozen=True, slots=True)
class XmlRule:
    name: str
    advice: str
    check: Check

    @property
    def gate(self) -> str:
        return "lint_xml_" + self.name.replace("-", "_")


def _field_text(record: etree._Element, name: str) -> str:
    field = record.find(f"field[@name='{name}']")
    return (field.text or "").strip() if field is not None else ""


def _neutralise_refs(expression: str) -> str:
    return PCT_REF_RE.sub(lambda m: "%" if m.group(0) == "%%" else "0", expression)


def _parses(expression: str) -> str | None:
    try:
        ast.parse(_neutralise_refs(expression).strip(), mode="eval")
    except SyntaxError as exc:
        return exc.msg
    return None


def _is_groupby_filter(element: etree._Element) -> bool:
    return element.tag == "filter" and "group_by" in (element.get("context") or "")


def attributes_spec_child(file: DataFile, ctx: Context):
    for xpath in file.root.iter("xpath"):
        if xpath.get("position") != "attributes":
            continue
        for child in xpath:
            if not callable(child.tag) and child.tag != "attribute":
                yield child.sourceline, f'<{child.tag}> under position="attributes"'


def duplicate_field(file: DataFile, ctx: Context):
    for record in file.records():
        names = [
            child.get("name")
            for child in record
            if not callable(child.tag) and child.tag == "field"
        ]
        for name, count in Counter(names).items():
            if count > 1:
                yield record.sourceline, f"{record.get('id')}: {name} x{count}"


def expression_syntax(file: DataFile, ctx: Context):
    for _record, arch in file.model_view_archs():
        for element in arch.iter():
            if callable(element.tag):
                continue
            if element.tag == "attribute":
                name = element.get("name")
                if (
                    name in EXPRESSION_ATTRIBUTES
                    and not element.get("add")
                    and not element.get("remove")
                    and (text := (element.text or "").strip())
                    and (why := _parses(text))
                ):
                    yield element.sourceline, f"<attribute name={name!r}>: {why}"
                continue
            for name in EXPRESSION_ATTRIBUTES.intersection(element.attrib):
                if name == "domain" and _is_groupby_filter(element):
                    continue
                value = element.get(name)
                if not value.strip():
                    yield element.sourceline, f'{name}="" on <{element.tag}>'
                elif why := _parses(value):
                    yield element.sourceline, f"{name}= on <{element.tag}>: {why}"


def eval_syntax(file: DataFile, ctx: Context):
    for element in file.elements():
        value = element.get("eval")
        if value is None:
            continue
        if not value.strip():
            yield element.sourceline, f'eval="" on <{element.tag}>'
        elif why := _parses(value):
            yield element.sourceline, f"eval= on <{element.tag}>: {why}"


def xpath_syntax(file: DataFile, ctx: Context):
    for xpath in file.root.iter("xpath"):
        expr = xpath.get("expr")
        if not expr:
            yield xpath.sourceline, "<xpath> without expr"
            continue
        shimmed = _HASCLASS_RE.sub("contains(@class,", _neutralise_refs(expr))
        try:
            etree.XPath(shimmed)
        except etree.XPathSyntaxError as exc:
            yield xpath.sourceline, f"{expr!r}: {exc}"


def tree_view(file: DataFile, ctx: Context):
    for element in file.root.iter("tree"):
        yield element.sourceline, "<tree>"
    for record in file.records():
        if record.get("model") not in (
            "ir.actions.act_window",
            "ir.actions.act_window.view",
        ):
            continue
        mode = record.find("field[@name='view_mode']")
        if mode is not None and "tree" in (mode.text or "").split(","):
            yield mode.sourceline, f"{record.get('id')}: view_mode {mode.text}"


def removed_attribute(file: DataFile, ctx: Context):
    for _record, arch in file.model_view_archs():
        for element in arch.iter():
            if callable(element.tag):
                continue
            for name in REMOVED_ATTRIBUTES.intersection(element.attrib):
                yield element.sourceline, f"{name}= on <{element.tag}>"


def kanban_box(file: DataFile, ctx: Context):
    for element in file.root.iter("t"):
        if element.get("t-name") == "kanban-box":
            yield element.sourceline, 't-name="kanban-box"'


def search_item_name(file: DataFile, ctx: Context):
    for element in file.root.iter("filter"):
        if not element.get("name"):
            yield element.sourceline, f"<filter string={element.get('string')!r}>"
    for element in file.root.iter("group"):
        parent = element.getparent()
        in_search = (parent is not None and parent.tag == "search") or any(
            not callable(child.tag) and child.tag == "filter" for child in element
        )
        if not in_search:
            continue
        for name in ("string", "expand"):
            if element.get(name) is not None:
                yield element.sourceline, f"<group {name}={element.get(name)!r}>"


def deprecated_output_directive(file: DataFile, ctx: Context):
    for element in file.elements():
        for name in ("t-esc", "t-raw"):
            if element.get(name) is not None:
                yield element.sourceline, f"{name}= on <{element.tag}>"


def _is_command_tuple(node: ast.AST) -> bool:
    if not isinstance(node, ast.Tuple) or len(node.elts) not in (2, 3):
        return False
    code, second, *_rest = node.elts
    if not (isinstance(code, ast.Constant) and code.value in _COMMAND_CODES):
        return False
    return (isinstance(second, ast.Constant) and second.value == 0) or isinstance(
        second, (ast.Call, ast.Name, ast.Attribute)
    )


def legacy_x2many_command(file: DataFile, ctx: Context):
    for element in file.elements():
        if element.tag not in ("field", "value"):
            continue
        value = element.get("eval")
        if not value or "(" not in value:
            continue
        try:
            node = ast.parse(value.strip(), mode="eval").body
        except SyntaxError:
            continue
        if isinstance(node, ast.List) and any(map(_is_command_tuple, node.elts)):
            yield element.sourceline, f"{element.get('name')}: {value.strip()[:60]}"


def menuitem_placement(file: DataFile, ctx: Context):
    if "menu" in Path(file.path).stem:
        return
    for element in file.root.iter("menuitem"):
        yield element.sourceline, f"{element.get('id')} in {Path(file.path).name}"


def data_root(file: DataFile, ctx: Context):
    if file.root.tag != "odoo":
        yield file.root.sourceline, f"<{file.root.tag}>"


def orphan_data_file(file: DataFile, ctx: Context):
    if not file.listed and not file.loaded_from_python:
        yield 1, "no manifest lists it and no Python loads it"


def unknown_model(file: DataFile, ctx: Context):
    def judge(element, model, what):
        if model and model not in ctx.declared_models:
            yield element.sourceline, f"{what} {model!r}"

    for record in file.records():
        yield from judge(record, record.get("model"), "record model")
        if record.get("model") == "ir.ui.view":
            yield from judge(record, _field_text(record, "model"), "view model")
        elif record.get("model") == "ir.actions.act_window":
            yield from judge(record, _field_text(record, "res_model"), "res_model")


_LIST_ROOTS = frozenset({"list", "tree"})

_NAMED_ARCH_TAGS = frozenset({"filter", "page", "group", "notebook"})

_LABEL_OWNERS = frozenset({"group", "setting"})

_TRUE = frozenset({"1", "True"})


def _under(element: etree._Element, tags: frozenset[str], stop: etree._Element) -> bool:
    parent = element.getparent()
    while parent is not None and parent is not stop:
        if parent.tag in tags:
            return True
        parent = parent.getparent()
    return False


def _arch_root(arch: etree._Element) -> str | None:
    return next((c.tag for c in arch if not callable(c.tag)), None)


def duplicate_arch_name(file: DataFile, ctx: Context):
    for record, arch in file.model_view_archs():
        seen: dict[tuple[str, str], etree._Element] = {}
        for element in arch.iter(*_NAMED_ARCH_TAGS):
            if callable(element.tag) or element.get("position") is not None:
                continue
            name = element.get("name")
            if not name:
                continue
            key = (element.tag, name)
            if key in seen:
                first = seen[key].sourceline
                message = f"{record.get('id')}: <{element.tag} name={name!r}> again"
                yield element.sourceline, f"{message} (first at line {first})"
            else:
                seen[key] = element


def special_button_type(file: DataFile, ctx: Context):
    for record, arch in file.model_view_archs():
        for element in arch.iter("button"):
            if callable(element.tag) or not element.get("special"):
                continue
            if element.get("type"):
                special, kind = element.get("special"), element.get("type")
                where = f"{record.get('id')}: special={special!r}"
                yield element.sourceline, f"{where} with type={kind!r}"


def readonly_duplicates_invisible(file: DataFile, ctx: Context):
    for record, arch in file.model_view_archs():
        for element in arch.iter("field"):
            if callable(element.tag):
                continue
            invisible, readonly = element.get("invisible"), element.get("readonly")
            if invisible and readonly and invisible.strip() == readonly.strip():
                field = f"{record.get('id')}: {element.get('name')}"
                yield (
                    element.sourceline,
                    f"{field} invisible == readonly == {invisible!r}",
                )


def nolabel_outside_group(file: DataFile, ctx: Context):
    for record, arch in file.model_view_archs():
        if _arch_root(arch) != "form":
            continue
        for element in arch.iter("field"):
            if callable(element.tag) or element.get("nolabel") not in _TRUE:
                continue
            if _under(element, _LIST_ROOTS | {"kanban"}, arch):
                continue
            if not _under(element, _LABEL_OWNERS, arch):
                yield element.sourceline, f"{record.get('id')}: {element.get('name')}"


def column_invisible_outside_list(file: DataFile, ctx: Context):
    for record, arch in file.model_view_archs():
        if _arch_root(arch) != "form":
            continue
        for element in arch.iter("field"):
            if callable(element.tag):
                continue
            value = element.get("column_invisible")
            if value is None or _under(element, _LIST_ROOTS, arch):
                continue
            what = "write invisible=" if value.strip() in _TRUE else "never evaluated"
            field = f"{record.get('id')}: {element.get('name')}"
            yield element.sourceline, f"{field} column_invisible={value!r} ({what})"


_BOOLEAN_SPELLING = {"true": "True", "false": "False"}


def boolean_spelling(file: DataFile, ctx: Context):
    for _record, arch in file.model_view_archs():
        for element in arch.iter():
            if callable(element.tag):
                continue
            for name in EXPRESSION_ATTRIBUTES.intersection(element.attrib):
                value = element.get(name).strip()
                if value in _BOOLEAN_SPELLING:
                    spelled = _BOOLEAN_SPELLING[value]
                    where = f"{name}={value!r} on <{element.tag}>"
                    yield element.sourceline, f"{where}, write {spelled}"


def optional_value(file: DataFile, ctx: Context):
    for element in file.elements():
        value = element.get("optional")
        if value is not None and value not in OPTIONAL_VALUES:
            yield element.sourceline, f"optional={value!r}"


def kanban_template_scope(file: DataFile, ctx: Context):
    for kanban in file.root.iter("kanban"):
        for templates in kanban.iter("templates"):
            named = {tpl.get("t-name"): tpl for tpl in templates if tpl.get("t-name")}
            if len(named) < 2:
                continue
            assigned = {
                name: {n.get("t-set") for n in tpl.iter() if n.get("t-set")}
                for name, tpl in named.items()
            }
            for name, tpl in named.items():
                if name not in KANBAN_ENTRY_TEMPLATES:
                    continue
                elsewhere = set().union(
                    *(names for key, names in assigned.items() if key != name)
                )
                leaked = elsewhere - assigned[name]
                for node in tpl.iter():
                    expr = (node.get("t-if") or "").strip()
                    if _BARE_NAME.match(expr) and expr in leaked:
                        setters = sorted(k for k, v in assigned.items() if expr in v)
                        message = (
                            f"<{node.tag} t-if={expr!r}> in t-name={name!r}, "
                            f"set only in {setters}"
                        )
                        yield node.sourceline, message


def groupby_filter_domain(file: DataFile, ctx: Context):
    for element in file.root.iter("filter"):
        if _is_groupby_filter(element) and element.get("domain") is not None:
            yield (
                element.sourceline,
                f"<filter name={element.get('name')!r} domain={element.get('domain')!r}>",
            )


RULES: tuple[XmlRule, ...] = (
    XmlRule(
        "attributes-spec-child",
        'only <attribute> children are read under position="attributes" '
        "(_apply_attributes iterates spec.iter('attribute')): a <field> there is "
        "never added to the view and a <t t-if> around an <attribute> guards "
        "nothing -- move the element out, or wrap it in its own xpath",
        attributes_spec_child,
    ),
    XmlRule(
        "duplicate-field",
        "the loader keeps the last <field> of a name and the earlier one is "
        "dead -- delete it, or merge the two values into one",
        duplicate_field,
    ),
    XmlRule(
        "expression-syntax",
        "a view attribute the client evaluates as Python must parse as Python; "
        "an empty one evaluates as nothing and belongs off the element",
        expression_syntax,
    ),
    XmlRule(
        "eval-syntax",
        "eval= is passed to safe_eval; an empty one is ignored and the field "
        "reads the element text instead -- write the value, or drop the attribute",
        eval_syntax,
    ),
    XmlRule(
        "xpath-syntax",
        "the expression fails at install with an XPath error; fix it",
        xpath_syntax,
    ),
    XmlRule(
        "tree-view",
        "the view type is `list`; `tree` is the pre-17.0 spelling",
        tree_view,
    ),
    XmlRule(
        "removed-attribute",
        "attrs= and states= were removed in 17.0; write the condition as a "
        "Python expression in invisible=, readonly=, required= or column_invisible=",
        removed_attribute,
    ),
    XmlRule(
        "kanban-box",
        'the kanban card template is t-name="card"; "kanban-box" is the '
        "pre-17.0 name and renders nothing",
        kanban_box,
    ),
    XmlRule(
        "search-item-name",
        "every <filter> needs a name so inheritance can reach it, and a search "
        "<group> takes no string= or expand= (both rejected by the RNG)",
        search_item_name,
    ),
    XmlRule(
        "deprecated-output-directive",
        "write t-out: ir.qweb logs a deprecation for every t-esc and t-raw it "
        "compiles, and t-raw is t-out with Markup()",
        deprecated_output_directive,
    ),
    XmlRule(
        "legacy-x2many-command",
        "write Command.create/update/delete/unlink/link/clear/set: Command is "
        "in the eval context and the tuple codes are the pre-15.0 spelling",
        legacy_x2many_command,
    ),
    XmlRule(
        "menuitem-placement",
        "a module's menus live together in views/<module>_menus.xml, not beside "
        "the view they open",
        menuitem_placement,
    ),
    XmlRule(
        "data-root",
        "the root element is <odoo>; <data> is a section inside it",
        data_root,
    ),
    XmlRule(
        "orphan-data-file",
        "list the file under data or demo in the manifest, or delete it: "
        "nothing loads it, so the records it declares never exist and every "
        "env.ref(..., raise_if_not_found=False) of them silently degrades",
        orphan_data_file,
    ),
    XmlRule(
        "unknown-model",
        "no Python class declares this _name; a typo here fails the install "
        "of every module that loads the file",
        unknown_model,
    ),
    XmlRule(
        "duplicate-arch-name",
        "two definitions with one name in one arch: an xpath by that name reaches "
        "only the first, and two filters with one name are toggled together by "
        "search_default_<name> -- rename the second",
        duplicate_arch_name,
    ),
    XmlRule(
        "special-button-type",
        "a special= button is handled before type= is read, so the type is dead "
        "-- drop it (name= stays: it is an xpath and tour target)",
        special_button_type,
    ),
    XmlRule(
        "readonly-duplicates-invisible",
        "a field that is readonly exactly when it is invisible is never edited "
        "either way; the readonly= is dead -- drop it",
        readonly_duplicates_invisible,
    ),
    XmlRule(
        "nolabel-outside-group",
        "the form compiler reads nolabel= only on the children of a <group> or a "
        "<setting>; anywhere else in a form it is dead -- drop it",
        nolabel_outside_group,
    ),
    XmlRule(
        "column-invisible-outside-list",
        "column_invisible= is a list attribute: a literal is promoted to "
        "invisible=, an expression is never evaluated and the field shows -- "
        "write invisible=",
        column_invisible_outside_list,
    ),
    XmlRule(
        "boolean-spelling",
        "a view condition is a Python expression: True and False, not the "
        "JavaScript spelling py.js happens to accept",
        boolean_spelling,
    ),
    XmlRule(
        "optional-value",
        'use optional="show" or optional="hide"; any other value hides the '
        'column, but only because the renderer compares against "show"',
        optional_value,
    ),
    XmlRule(
        "kanban-template-scope",
        "each t-name in a kanban <templates> is its own OWL template: repeat the "
        "t-set, or inline the expression -- OWL resolves the missing name to "
        "undefined, so the markup never renders and nothing reports it",
        kanban_template_scope,
    ),
    XmlRule(
        "groupby-filter-domain",
        "drop the domain: classifyByContext() promotes a filter whose context "
        "sets group_by to a groupBy item, and visitFilter() reads domain only "
        "while the item is still a filter, so it is never used",
        groupby_filter_domain,
    ),
)

BY_NAME: dict[str, XmlRule] = {rule.name: rule for rule in RULES}
