"""What the framework requires of the addon-owned models it calls.

The core owns no business models. It nevertheless calls 69 members on 22 models
that live in ``addons/base``, reached by string key -- ``env["res.users"]``,
``registry["ir.model.data"]`` -- which compiles to no import and so is invisible
to every dependency gate. ``module.md`` calls this "the framework's largest real
coupling to its consumer"; ``env_model_surface_check.py`` bounds *which models*,
and ``model_member_surface_check.py`` bounds *which members*.

Neither says what those members are supposed to look like. That is this file.

**What a Protocol here buys.** Two failure modes, both otherwise silent:

* the core starts calling a member nothing implements. Adding
  ``env["res.users"]._invent_a_hook()`` to ``orm/`` passes `layer_check`,
  `env_surface_check`, `pool_surface_check` and `env_model_surface_check` --
  four gates, all green. It fails `model_member_surface_check`, and once a model
  is listed in that gate's ``PROTOCOLS`` map it fails for the sharper reason
  that the contract does not declare it.
* ``base`` renames a member or changes its signature under the framework.
  Nothing catches that today; ``addons/base/tests/test_framework_contracts.py``
  checks every Protocol below against the live model.

**These describe the framework's requirement, not the model.** ``res.users`` has
hundreds of members; ``ResUsersProtocol`` names the eleven the core cannot work
without. Widening one to match the implementation more closely is the wrong
direction -- the value is in the narrowness, which is what makes the set
reviewable and what tells an addon author which parts of ``base`` the framework
is standing on.

**Structural, not nominal.** Nothing inherits from these and nothing imports
them at run time; they exist to be checked. ``http/_protocols.py`` declares the
same thing for ``ir.http``, next to the code that calls it, and stays there.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from odoo.exceptions import AccessError

    from .domain import Domain


class RecordsetProtocol(Protocol):
    """The `BaseModel` surface the core uses *on addon-owned models*.

    Every Protocol below extends this one, which is what lets a typed accessor
    return a single type that satisfies both halves of what these values are: a
    recordset, and an implementor of an addon contract. Python has no
    intersection type -- there is no way to spell ``BaseModel & IrModelDataProtocol``
    -- but Protocol inheritance composes, so the intersection is expressed by
    construction instead of by an operator the language lacks.

    **Eleven members, and the number is measured rather than chosen.** It is
    exactly what the core calls on the thirteen models in
    :data:`FRAMEWORK_MODEL_PROTOCOLS`, derived by running
    ``model_member_surface_check``'s collector with the ``BaseModel``
    subtraction turned off. `BaseModel` has 216 non-dunder members; restating
    them here would be absurd and would also be a second copy of an interface
    that already exists.

    The narrowness is the point, and it is the same point the member gate
    makes one direction over: this bounds the *recordset* surface used on
    addon-owned models, as that bounds the *addon* surface used by the core. A
    twelfth member is a type error naming this class, which is a decision to
    take rather than a fact to discover later.
    """

    id: Any
    _fields: Any

    def browse(self, ids: Any = ()) -> Any: ...

    def create(self, vals_list: Any) -> Any: ...

    def invalidate_model(
        self, fnames: Collection[str] | None = None, flush: bool = True
    ) -> None: ...

    def search(
        self,
        domain: Any,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> Any: ...

    def search_count(self, domain: Any, limit: int | None = None) -> int: ...

    def search_fetch(
        self,
        domain: Any,
        field_names: Sequence[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> Any: ...

    def search_read(
        self,
        domain: Any = None,
        fields: Sequence[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        **read_kwargs: Any,
    ) -> list[Any]: ...

    def sudo(self, flag: bool = True) -> Any: ...

    def with_context(self, ctx: Any = None, /, **overrides: Any) -> Any: ...

    def with_user(self, user: Any) -> Any: ...


class IrModelDataProtocol(RecordsetProtocol, Protocol):
    """``ir.model.data`` -- the xml-id table, reached by `Environment.ref`."""

    def _load_xmlid(self, xml_id: str) -> Any: ...

    def _process_end(self, modules: list[str]) -> None: ...

    def _update_xmlids(
        self, data_list: list[dict[str, Any]], update: bool = False
    ) -> None: ...

    def _xmlid_to_res_model_res_id(
        self, xmlid: str, raise_if_not_found: bool = False
    ) -> tuple[Any, Any]: ...


class IrModelProtocol(RecordsetProtocol, Protocol):
    """``ir.model`` -- the model meta-table the registry reflects into."""

    def _get(self, name: str) -> Any: ...

    def _instantiate_attrs(self, model_data: dict[str, Any]) -> dict[str, Any]: ...

    def _reflect_models(self, model_names: list[str]) -> None: ...


class IrModelFieldsProtocol(RecordsetProtocol, Protocol):
    """``ir.model.fields`` -- the field meta-table, and the manual-field source."""

    def _get(self, model_name: str, name: str) -> Any: ...

    def _get_ids(self, model_name: str) -> dict[str, int]: ...

    def _get_manual_field_data(self, model_name: str) -> dict[str, Any]: ...

    def _instantiate_attrs(
        self, field_data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def _reflect_fields(self, model_names: list[str]) -> None: ...

    def get_field_help(self, model_name: str) -> dict[str, str | None]: ...

    def get_field_selection(
        self, model_name: str, field_name: str
    ) -> list[tuple[str, str]]: ...

    def get_field_string(self, model_name: str) -> dict[str, str]: ...


class IrModelConstraintProtocol(RecordsetProtocol, Protocol):
    """``ir.model.constraint`` -- where schema constraints are reflected."""

    def _reflect_constraint(
        self,
        model: Any,
        conname: str,
        # Shadows the builtin, and has to: a Protocol only checks a keyword
        # call if its parameter names match the implementation's, and
        # `ir.model.constraint._reflect_constraint` calls this one `type`.
        type: str,
        definition: str,
        module: str,
        message: str | None = None,
    ) -> Any: ...

    def _reflect_constraints(self, model_names: list[str]) -> None: ...


class IrModelAccessProtocol(RecordsetProtocol, Protocol):
    """``ir.model.access`` -- the model-level half of access control.

    Reached only through a local binding in ``orm/models/mixins/access.py``
    (``Access = self.env["ir.model.access"]``), which is why
    `model_member_surface_check` had to learn to follow single-assignment
    locals before it could see this model at all.
    """

    def check(
        self, model: str, mode: str = "read", raise_exception: bool = True
    ) -> bool: ...

    def _make_access_error(self, model: str, mode: str) -> AccessError: ...


class IrRuleProtocol(RecordsetProtocol, Protocol):
    """``ir.rule`` -- the record-level half of access control."""

    def _compute_domain(self, model_name: str, mode: str = "read") -> Domain | None: ...

    def _make_access_error(self, operation: str, records: Any) -> AccessError: ...


class IrDefaultProtocol(RecordsetProtocol, Protocol):
    """``ir.default`` -- user/company defaults and company-dependent fallbacks."""

    def _evaluate_condition_with_fallback(
        self, model_name: str, field_expr: str, operator: str, value: Any
    ) -> bool | None: ...

    def _get_field_column_fallbacks(self, model_name: str, field_name: str) -> str: ...

    def _get_model_defaults(
        self, model_name: str, condition: str | bool = False
    ) -> dict[str, Any]: ...


class IrAttachmentProtocol(RecordsetProtocol, Protocol):
    """``ir.attachment`` -- the filestore, reached by `Binary` fields."""

    def _content_checksum(self, bin_data: bytes) -> str: ...

    def _filestore(self) -> str: ...

    def _unsized(self) -> Any: ...


class IrUiViewProtocol(RecordsetProtocol, Protocol):
    """``ir.ui.view`` -- template rendering and view validation."""

    def _render_template(
        self, template: int | str, values: dict[str, Any] | None = None
    ) -> Any: ...

    def _validate_custom_views(self, model: Any) -> Any: ...

    def _validate_module_views(self, module: str) -> None: ...


class IrModuleModuleProtocol(RecordsetProtocol, Protocol):
    """``ir.module.module`` -- the module table the loader and CLI drive."""

    def _extract_resource_attachment_translations(
        self, module: Any, lang: Any
    ) -> Any: ...

    def _import_zipfile(
        self, module_file: Any, force: bool = False, with_demo: bool = False
    ) -> Any: ...

    def update_list(self) -> Any: ...


class ResLangProtocol(RecordsetProtocol, Protocol):
    """``res.lang`` -- language data, reached by every translated field."""

    def _get_data(self, **kwargs: Any) -> Any: ...

    def _lang_get(self, code: str) -> Any: ...

    def get_installed(self) -> list[tuple[str, str]]: ...


class ResUsersProtocol(RecordsetProtocol, Protocol):
    """``res.users`` -- the widest of them, and the one with fields in it.

    ``company_id``, ``company_ids``, ``lang`` and ``tz`` are *fields*, not
    methods: `Environment.company`, `Environment.tz` and `Environment.lang` read
    them off the user record. A Protocol declares them as attributes, which is
    what makes them checkable at all -- a method-only contract would have
    silently omitted four of the eleven members the framework depends on.
    """

    company_id: Any
    company_ids: Any
    lang: Any
    tz: Any

    def _check_uid_passwd(self, uid: int, passwd: str) -> None: ...

    def _compute_session_token(self, sid: str) -> str | bool: ...

    def _has_group(self, group_ext_id: str) -> bool: ...

    def _is_public(self) -> bool: ...

    def authenticate(
        self, credential: dict[str, Any], user_agent_env: dict[str, Any]
    ) -> dict[str, Any]: ...

    def context_get(self) -> Any: ...

    def has_group(self, group_ext_id: str) -> bool: ...

    def has_groups(self, group_spec: str) -> bool: ...


#: ``model name -> Protocol``, the map both the gate and the contract test read.
#:
#: One entry per model the core reaches for two or more members. The single-member
#: models are deliberately absent: a one-method contract is a call site with extra
#: steps, and the surface ratchet in `model_member_surface_check` already pins
#: those names exactly.
FRAMEWORK_MODEL_PROTOCOLS: dict[str, type] = {
    "ir.attachment": IrAttachmentProtocol,
    "ir.default": IrDefaultProtocol,
    "ir.model": IrModelProtocol,
    "ir.model.access": IrModelAccessProtocol,
    "ir.model.constraint": IrModelConstraintProtocol,
    "ir.model.data": IrModelDataProtocol,
    "ir.model.fields": IrModelFieldsProtocol,
    "ir.module.module": IrModuleModuleProtocol,
    "ir.rule": IrRuleProtocol,
    "ir.ui.view": IrUiViewProtocol,
    "res.lang": ResLangProtocol,
    "res.users": ResUsersProtocol,
}
