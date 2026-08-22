import collections.abc
import typing
from collections import defaultdict
from difflib import get_close_matches, unified_diff
from hashlib import sha256
from operator import attrgetter
from typing import override

from markupsafe import Markup
from markupsafe import escape as markup_escape

from odoo.db import schema as sql
from odoo.exceptions import AccessError, UserError
from odoo.libs.colors import DEFAULT, GREEN, RED, colorize
from odoo.libs.sql import (
    pattern_to_translated_trigram_pattern,
    pg_varchar,
    value_to_translated_trigram_pattern,
)
from odoo.tools import SQL, html_normalize, html_sanitize
from odoo.tools.misc import PENDING, SENTINEL, OrderedSet, Sentinel
from odoo.tools.translate import html_translate

from ..primitives import COLLECTION_TYPES, SQL_OPERATORS
from .base import Field, _logger

_EN_US_KEY = ("en_US",)

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterable, MutableMapping

    from odoo.tools import Query

    from .._typing import IdType, ModelLike
    from ..models import BaseModel
    from ..runtime import Environment


class BaseString(Field[str | typing.Literal[False]]):
    translate: bool | Callable[[Callable[[str], str], str], str] = False
    size = None
    is_text = True
    falsy_value = ""

    def __init__(self, string: str | Sentinel = SENTINEL, **kwargs: typing.Any) -> None:
        if "translate" in kwargs and not callable(kwargs["translate"]):
            kwargs["translate"] = bool(kwargs["translate"])
        super().__init__(string=string, **kwargs)

    @typing.overload
    def __get__(self, record: None, owner: typing.Any = None) -> typing.Self: ...
    @typing.overload
    def __get__(
        self, record: BaseModel, owner: typing.Any = None
    ) -> str | typing.Literal[False]: ...
    @typing.overload
    def __get__(self, record: object, owner: typing.Any = None) -> typing.Any: ...

    @override
    def __get__(self, record: typing.Any, owner: typing.Any = None) -> typing.Any:
        if record is None:
            return self
        env = record.env
        if not (not self.groups or env.su or record._has_field_access(self, "read")):
            record._check_field_access(self, "read")
        ids = record._ids
        if len(ids) != 1:
            return super().__get__(record, owner)
        if callable(self.translate):
            return super().__get__(record, owner)
        if self.is_stored_computed and env._core.has_pending_field(self):
            self.recompute(record)
        record_id = ids[0]
        try:
            value = env.__dict__["_field_cache_memo"][self][record_id]
        except KeyError:
            pass
        else:
            if value is not PENDING:
                return False if value is None else value
        if self._needs_translate_fallback(record_id):
            fb_val = self._scalar_translate_fallback(env, record_id)
            if fb_val is not SENTINEL:
                return False if fb_val is None else fb_val
        return super().__get__(record, owner)

    def _needs_translate_fallback(self, record_id: typing.Any) -> bool:
        return self.translate is True and not (
            self.compute
            or (self.store and (record_id or getattr(record_id, "origin", None)))
        )

    def _lang_cache_key(self, env: Environment, lang: str) -> tuple:
        cache_key = env.cache_key(self)
        if len(cache_key) == 1:
            return _EN_US_KEY if lang == "en_US" else (lang,)
        return (lang, *cache_key[1:])

    def _lang_fallback_cache_key(self, env: Environment) -> tuple:
        return self._lang_cache_key(env, "en_US")

    def _scalar_translate_fallback(
        self, env: Environment, record_id: typing.Any
    ) -> typing.Any:
        cur_val = self._get_cache(env).get(record_id, SENTINEL)
        if cur_val is not SENTINEL:
            return cur_val
        fb_cache = env._core.get_field_data(self).get(
            self._lang_fallback_cache_key(env)
        )
        if fb_cache is not None:
            return fb_cache.get(record_id, SENTINEL)
        return SENTINEL

    _related_translate = property(attrgetter("translate"))

    def _description_translate(self, env: Environment) -> bool:
        return bool(self.translate)

    @override
    def setup_related(self, model: BaseModel) -> None:
        super().setup_related(model)
        if self.store and self.translate:
            _logger.warning(
                "Translated stored related field (%s) will not be computed correctly in all languages",
                self,
            )

    def get_depends(self, model: BaseModel) -> tuple[Iterable[str], Iterable[str]]:
        if self.translate is True:
            dep, dep_ctx = super().get_depends(model)
            extra = tuple(dict.fromkeys(ctx for ctx in dep_ctx if ctx != "lang"))
            if extra and self.store:
                _logger.warning(
                    "Translated stored fields (%s) cannot depend on context: "
                    "the flushed column keeps one value per language; "
                    "ignoring context dependencies %s",
                    self,
                    extra,
                )
                return dep, ("lang",)
            return dep, ("lang", *extra)
        if callable(self.translate) and self.store:
            dep, dep_ctx = super().get_depends(model)
            if dep_ctx:
                _logger.warning(
                    "Translated stored fields (%s) cannot depend on context",
                    self,
                )
            return dep, ()
        return super().get_depends(model)

    def _convert_db_column(
        self, model: ModelLike, column: dict[str, typing.Any]
    ) -> None:
        if self.translate or column["udt_name"] == "jsonb":
            sql.convert_column_translatable(
                model.env.cr, model._table, self.name, self.column_type[1]
            )
        else:
            sql.convert_column(
                model.env.cr, model._table, self.name, self.column_type[1]
            )

    def get_trans_terms(self, value: str | None) -> list[str]:
        if not callable(self.translate):
            return [value] if value else []
        terms = []
        self.translate(terms.append, value)
        return terms

    def get_text_content(self, term: str) -> str:
        func = getattr(self.translate, "get_text_content", lambda term: term)
        return func(term)

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict | None = None,
        validate: bool = True,
    ) -> str | None:
        return self.convert_to_cache(value, record, validate)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> str | None:
        if value is None or value is False:
            return None
        if (
            value.__class__ is str
            and self.size is None
            and not (validate and callable(self.translate))
        ):
            return value
        if isinstance(value, bytes):
            s = value.decode()
        else:
            s = str(value)
        if self.size is not None:
            s = s[: self.size]
        if validate and callable(self.translate):
            s = self.translate(lambda t: None, s)
        return s

    @override
    def _compute_related(self, records: BaseModel) -> None:
        if records.env.context.get("edit_translations"):
            records = records.with_context(
                edit_translations=None, check_translations=True
            )
        super()._compute_related(records)

    @override
    def convert_to_record(
        self, value: typing.Any, record: ModelLike
    ) -> str | typing.Literal[False]:
        if value is None:
            return False
        if not callable(self.translate):
            return value
        if isinstance(value, dict):
            lang = self.translation_lang(record.env)
            value = value[lang]
        field_ = self
        record_ = record
        while not field_.store and field_.related and field_.related_field is not None:
            path = ".".join(field_._related_names[:-1])
            record_ = record_.mapped(path)[:1] if path else record_
            field_ = field_.related_field
        if field_ is not self:
            return field_.convert_to_record(value, record_)
        if (
            callable(self.translate)
            and record.env.context.get("edit_translations")
            and self.get_trans_terms(value)
        ):
            base_lang = record._get_base_lang()
            lang = record.env.lang or "en_US"
            delay_translation = (
                value
                != record.with_context(
                    edit_translations=None, check_translations=None, lang=lang
                )[self.name]
            )

            if lang != base_lang:
                base_value = record.with_context(
                    edit_translations=None,
                    check_translations=True,
                    lang=base_lang,
                )[self.name]
                base_terms = self.get_trans_terms(base_value)
                translated_terms = (
                    self.get_trans_terms(value) if value != base_value else base_terms
                )
                if len(base_terms) != len(translated_terms):
                    value = base_value
                    translated_terms = base_terms
                get_base = dict(
                    zip(translated_terms, base_terms, strict=True)
                ).__getitem__
            else:

                def get_base(term):
                    return term

            def translate_func(term):
                source_term = get_base(term)
                translation_state = (
                    "translated"
                    if lang == base_lang or source_term != term
                    else "to_translate"
                )
                translation_source_sha = sha256(source_term.encode()).hexdigest()
                return (
                    "<span "
                    f"""{'class="o_delay_translation" ' if delay_translation else ""}"""
                    f'data-oe-model="{markup_escape(record._name)}" '
                    f'data-oe-id="{markup_escape(record.id)}" '
                    f'data-oe-field="{markup_escape(self.name)}" '
                    f'data-oe-translation-state="{translation_state}" '
                    f'data-oe-translation-source-sha="{translation_source_sha}"'
                    ">"
                    f"{term}"
                    "</span>"
                )

            value = self.translate(translate_func, value)
        return value

    @override
    def convert_to_write(self, value: typing.Any, record: ModelLike) -> typing.Any:
        return value

    def get_translation_dictionary(
        self,
        from_lang_value: str,
        to_lang_values: dict[str, str],
    ) -> dict[str, dict[str, str]]:

        from_lang_terms = self.get_trans_terms(from_lang_value)
        dictionary = defaultdict(lambda: defaultdict(dict))
        if not from_lang_terms:
            return dictionary
        dictionary.update(
            {from_lang_term: defaultdict(dict) for from_lang_term in from_lang_terms}
        )

        for lang, to_lang_value in to_lang_values.items():
            to_lang_terms = self.get_trans_terms(to_lang_value)
            if len(from_lang_terms) != len(to_lang_terms):
                for from_lang_term in from_lang_terms:
                    dictionary[from_lang_term][lang] = from_lang_term
            else:
                for from_lang_term, to_lang_term in zip(
                    from_lang_terms, to_lang_terms, strict=True
                ):
                    dictionary[from_lang_term][lang] = to_lang_term
        return dictionary

    def _get_stored_translations(self, record: BaseModel) -> dict[str, str] | None:
        record.flush_recordset([self.name])
        cr = record.env.cr
        cr.execute(
            SQL(
                "SELECT %s FROM %s WHERE id = %s",
                SQL.identifier(self.name),
                SQL.identifier(record._table),
                record.id,
            )
        )
        res = cr.fetchone()
        return res[0] if res else None

    def translation_lang(self, env: Environment) -> str:
        return (env.lang or "en_US") if self.translate is True else env._lang

    def get_translation_fallback_langs(self, env: Environment) -> tuple[str, ...]:
        lang = self.translation_lang(env)
        if lang == "_en_US":
            return "_en_US", "en_US"
        if lang == "en_US":
            return ("en_US",)
        if lang.startswith("_"):
            return lang, lang[1:], "_en_US", "en_US"
        return lang, "en_US"

    def _get_cache_impl(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
        if self.translate is True:
            return super()._get_cache_impl(env)
        cache = super()._get_cache_impl(env)
        if not self.translate or env.context.get("prefetch_langs"):
            return cache
        lang = self.translation_lang(env)
        return LangProxyDict(self, cache, lang)

    def _cache_missing_ids(self, records: ModelLike) -> typing.Iterator[IdType]:
        if callable(self.translate) and records.env.context.get("prefetch_langs"):
            records = records.with_context(prefetch_langs=False)
        return super()._cache_missing_ids(records)

    def _to_prefetch(self, record: BaseModel) -> BaseModel:
        if callable(self.translate) and record.env.context.get("prefetch_langs"):
            return (
                super()
                ._to_prefetch(record.with_context(prefetch_langs=False))
                .with_env(record.env)
            )
        return super()._to_prefetch(record)

    def _insert_cache(self, records: BaseModel, values: Iterable[typing.Any]) -> None:
        if not self.translate:
            super()._insert_cache(records, values)
            return

        env = records.env
        if self.translate is True:
            if env.context.get("prefetch_langs"):
                field_data = env._core.get_field_data(self)
                sub_caches: dict[str, dict] = {}

                def sub_cache(lang: str) -> dict:
                    sub = sub_caches.get(lang)
                    if sub is None:
                        sub = sub_caches[lang] = field_data.setdefault(
                            self._lang_cache_key(env, lang), {}
                        )
                    return sub

                installed = [lang for lang, _ in env["res.lang"].get_installed()]
                langs = OrderedSet[str](installed + ["en_US"])
                for id_, val in zip(records._ids, values, strict=True):
                    if val is None:
                        for lang in langs:
                            sub_cache(lang).setdefault(id_, None)
                    else:
                        merged = {
                            **dict.fromkeys(langs, val.get("en_US")),
                            **val,
                        }
                        for lang, scalar in merged.items():
                            if not lang.startswith("_"):
                                sub_cache(lang).setdefault(id_, scalar)
            else:
                super()._insert_cache(records, values)
            return

        field_cache = env._core.get_field_data(self)
        if env.context.get("prefetch_langs"):
            installed = [lang for lang, _ in env["res.lang"].get_installed()]
            langs = OrderedSet[str](installed + ["en_US"])
            u_langs: list[str] = (
                [f"_{lang}" for lang in langs] if env._lang.startswith("_") else []
            )
            for id_, val in zip(records._ids, values, strict=True):
                if val is None:
                    field_cache.setdefault(id_, None)
                else:
                    if u_langs:
                        val.update(
                            {
                                f"_{k}": v
                                for k, v in val.items()
                                if k in langs and f"_{k}" not in val
                            }
                        )
                    field_cache[id_] = {
                        **dict.fromkeys(langs, val["en_US"]),
                        **dict.fromkeys(u_langs, val.get("_en_US")),
                        **val,
                    }
        else:
            lang = self.translation_lang(env)
            for id_, val in zip(records._ids, values, strict=True):
                if val is None:
                    field_cache.setdefault(id_, None)
                else:
                    cache_value = field_cache.setdefault(id_, {})
                    if cache_value is not None:
                        cache_value.setdefault(lang, val)

    def _update_cache(
        self, records: ModelLike, cache_value: typing.Any, dirty: bool = False
    ) -> None:
        if (
            self.translate is True
            and cache_value is not None
            and isinstance(cache_value, dict)
        ):
            env = records.env
            field_data = env._core.get_field_data(self)
            ids = records._ids
            for lang, scalar in cache_value.items():
                if lang.startswith("_"):
                    continue
                sub = field_data.setdefault(self._lang_cache_key(env, lang), {})
                if len(ids) <= 1:
                    if ids:
                        sub[ids[0]] = scalar
                else:
                    sub.update(dict.fromkeys(ids, scalar))
            if self.is_column and dirty:
                env._core.mark_dirty(self, (id_ for id_ in ids if id_))
            return
        if self.translate is True and cache_value is not None:
            super()._update_cache(records, cache_value, dirty)
            if not self.compute and not any(
                id_ or getattr(id_, "origin", None) for id_ in records._ids
            ):
                en_cache = records.env._core.get_field_data(self).setdefault(
                    self._lang_fallback_cache_key(records.env), {}
                )
                for id_ in records._ids:
                    en_cache.setdefault(id_, cache_value)
            return
        if (
            callable(self.translate)
            and cache_value is not None
            and records.env.context.get("prefetch_langs")
        ):
            assert isinstance(cache_value, dict), f"invalid cache value for {self}"
            if len(records) > 1:
                for record in records:
                    super()._update_cache(record, dict(cache_value), dirty)
                return
        super()._update_cache(records, cache_value, dirty)

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        if not self.translate or value is False or value is None:
            if self.translate is True and (value is False or value is None):
                self._invalidate_cache(records.env, records._ids)
            super().mark_dirty(records, value)
            return
        records, cache_value = self._mark_dirty_prologue(records, value)
        if not records:
            return
        dirty_ids = records.env._core.get_dirty(self) or ()
        self._flush_pending_none(records, dirty_ids)

        lang = self.translation_lang(records.env)
        if not (self.store and any(records._ids)):
            self._mark_dirty_unstored(records, cache_value, lang)
        elif not callable(self.translate):
            self._mark_dirty_model_translation(records, cache_value, lang, dirty_ids)
        else:
            self._mark_dirty_model_term_translation(records, cache_value, lang)

    def _flush_pending_none(self, records: BaseModel, dirty_ids: typing.Any) -> None:
        dirty_records = records.filtered(lambda rec: rec.id in dirty_ids)
        if not dirty_records:
            return
        if self.translate is True:
            field_data = records.env._core.get_field_data(self)
            has_dirty_none = any(
                sub.get(rid, SENTINEL) is None
                for sub in field_data.values()
                for rid in dirty_records._ids
            )
        else:
            field_cache = self._get_cache(records.env)
            has_dirty_none = any(
                field_cache.get(record_id, SENTINEL) is None
                for record_id in dirty_records._ids
            )
        if has_dirty_none:
            dirty_records.flush_recordset([self.name])
            if self.translate is True:
                self._invalidate_cache(records.env, dirty_records._ids)

    def _mark_dirty_unstored(
        self, records: BaseModel, cache_value: typing.Any, lang: str
    ) -> None:
        if self.compute and self.inverse and any(records._ids):
            if self.translate is True:
                self._invalidate_cache(records.env, records._ids)
            self._update_cache(
                records.with_context(prefetch_langs=True),
                {lang: cache_value},
                dirty=False,
            )
        else:
            self._update_cache(records, cache_value, dirty=False)

    def _mark_dirty_model_translation(
        self,
        records: BaseModel,
        cache_value: typing.Any,
        lang: str,
        dirty_ids: typing.Any,
    ) -> None:
        in_sync = self._languages_in_sync_with(records, lang, dirty_ids)
        clean_records = records.filtered(lambda rec: rec.id not in dirty_ids)
        clean_records.invalidate_recordset([self.name])
        self._update_cache(records, cache_value, dirty=True)
        if lang != "en_US" and not records.env["res.lang"]._get_data(code="en_US"):
            self._update_cache(
                records.with_context(lang="en_US"), cache_value, dirty=True
            )
        for other_lang, ids in in_sync.items():
            self._update_cache(
                records.browse(ids).with_context(lang=other_lang),
                cache_value,
                dirty=True,
            )

    def _languages_in_sync_with(
        self,
        records: BaseModel,
        lang: str,
        dirty_ids: typing.Any,
    ) -> dict[str, list]:
        ids = [id_ for id_ in records._ids if id_]
        if not ids or not records.env.backend.supports_translation_terms:
            return {}
        if lang == "en_US" and not records.env["res.lang"]._get_data(code="en_US"):
            return {}
        stored = self._get_stored_translations_multi(records.browse(ids), dirty_ids)
        followers = defaultdict(list)
        for id_, translations in stored.items():
            if not translations or len(translations) < 2:
                continue
            current = translations.get(lang)
            if current is None:
                continue
            for other_lang, term in translations.items():
                if other_lang != lang and term == current:
                    followers[other_lang].append(id_)
        return followers

    def _get_stored_translations_multi(
        self,
        records: BaseModel,
        dirty_ids: typing.Any,
    ) -> dict[IdType, dict[str, str] | None]:
        pending = records.filtered(lambda rec: rec.id in (dirty_ids or ()))
        if pending:
            pending.flush_recordset([self.name])
        cr = records.env.cr
        cr.execute(
            SQL(
                "SELECT id, %s FROM %s WHERE id IN %s",
                SQL.identifier(self.name),
                SQL.identifier(records._table),
                tuple(records._ids),
            )
        )
        return dict(cr.fetchall())

    def _mark_dirty_model_term_translation(
        self, records: BaseModel, cache_value: typing.Any, lang: str
    ) -> None:
        new_translations_list = []
        new_terms = set(self.get_trans_terms(cache_value))
        delay_translations = records.env.context.get("delay_translations")
        for record in records:
            if not new_terms:
                new_translations_list.append({"en_US": cache_value, lang: cache_value})
                continue
            stored_translations = self._get_stored_translations(record)
            if not stored_translations:
                new_translations_list.append({"en_US": cache_value, lang: cache_value})
                continue
            old_translations = {
                k: stored_translations.get(f"_{k}", v)
                for k, v in stored_translations.items()
                if not k.startswith("_")
            }
            fallback_value = old_translations.get("en_US")
            if fallback_value is None:
                fallback_value = next(iter(old_translations.values()), cache_value)
            from_lang_value = old_translations.pop(lang, fallback_value)
            translation_dictionary = self.get_translation_dictionary(
                from_lang_value, old_translations
            )
            self._reconcile_obsolete_terms(
                translation_dictionary, new_terms, lang, records.env
            )
            new_translations = {
                l: self.translate(
                    lambda term, td=translation_dictionary, l=l: td.get(
                        term, {l: None}
                    )[l],
                    cache_value,
                )
                for l in old_translations
            }
            if delay_translations:
                new_store_translations = stored_translations
                new_store_translations.update(
                    {f"_{k}": v for k, v in new_translations.items()}
                )
                new_store_translations.pop(f"_{lang}", None)
            else:
                new_store_translations = new_translations
            new_store_translations[lang] = cache_value

            if not records.env["res.lang"]._get_data(code="en_US"):
                new_store_translations["en_US"] = cache_value
                new_store_translations.pop("_en_US", None)
            new_translations_list.append(new_store_translations)
        for record, new_translation in zip(
            records.with_context(prefetch_langs=True),
            new_translations_list,
            strict=True,
        ):
            self._update_cache(record, new_translation, dirty=True)

    def _reconcile_obsolete_terms(
        self,
        translation_dictionary: dict,
        new_terms: set,
        lang: str,
        env: Environment,
    ) -> None:
        text2terms = defaultdict(list)
        for term in new_terms:
            if term_text := self.get_text_content(term):
                text2terms[term_text].append(term)

        is_text = (
            self.translate.is_text
            if hasattr(self.translate, "is_text")
            else lambda term: True
        )
        term_adapter = (
            self.translate.term_adapter
            if hasattr(self.translate, "term_adapter")
            else None
        )
        for old_term in list(translation_dictionary.keys()):
            if old_term not in new_terms:
                old_term_text = self.get_text_content(old_term)
                matches = get_close_matches(old_term_text, text2terms, 1, 0.9)
                if matches:
                    closest_term = get_close_matches(
                        old_term, text2terms[matches[0]], 1, 0
                    )[0]
                    if closest_term in translation_dictionary:
                        continue
                    old_is_text = is_text(old_term)
                    closest_is_text = is_text(closest_term)
                    if old_is_text or not closest_is_text:
                        if (
                            not closest_is_text
                            and env.context.get("install_mode")
                            and lang == "en_US"
                            and term_adapter
                        ):
                            adapter = term_adapter(closest_term)
                            if adapter(old_term) is None:
                                continue
                            translation_dictionary[closest_term] = {
                                k: adapter(v)
                                for k, v in translation_dictionary.pop(old_term).items()
                            }
                        else:
                            translation_dictionary[closest_term] = (
                                translation_dictionary.pop(old_term)
                            )

    @override
    def to_sql(self, model: ModelLike, alias: str) -> SQL:
        sql_field = super().to_sql(model, alias)
        if self.translate and not model.env.context.get("prefetch_langs"):
            langs = self.get_translation_fallback_langs(model.env)
            sql_field_langs = [SQL("%s->>%s", sql_field, lang) for lang in langs]
            if len(sql_field_langs) == 1:
                return sql_field_langs[0]
            return SQL("COALESCE(%s)", SQL(", ").join(sql_field_langs))
        return sql_field

    def expression_getter(self, field_expr: str) -> Callable[[BaseModel], typing.Any]:
        if field_expr != "display_name.no_error":
            return super().expression_getter(field_expr)

        get_display_name = super().expression_getter("display_name")

        def getter(record):
            try:
                return get_display_name(record)
            except AccessError:
                return ""

        return getter

    @override
    def condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        if self.translate and model.env.context.get("prefetch_langs"):
            model = model.with_context(prefetch_langs=False)
        base_condition = super().condition_to_sql(
            field_expr, operator, value, model, alias, query
        )

        if (
            self.translate
            and value
            and operator in ("in", "like", "ilike", "=like", "=ilike")
            and self.index == "trigram"
            and model.pool.has_trigram
            and (
                isinstance(value, str)
                or (
                    isinstance(value, COLLECTION_TYPES)
                    and all(isinstance(v, str) for v in value)
                )
            )
        ):
            if operator == "in" and len(value) == 1:
                value = value_to_translated_trigram_pattern(next(iter(value)))
            elif operator != "in":
                assert isinstance(value, str)
                value = pattern_to_translated_trigram_pattern(value)
            else:
                value = "%"

            if value == "%":
                return base_condition

            raw_sql_field = self.to_sql(model.with_context(prefetch_langs=True), alias)
            sql_left = SQL("jsonb_path_query_array(%s, '$.*')::text", raw_sql_field)
            sql_operator = SQL_OPERATORS["like" if operator == "in" else operator]
            sql_right = SQL("%s", self.convert_to_column(value, model, validate=False))
            unaccent = model.env.registry.unaccent
            return SQL(
                "(%s%s%s AND %s)",
                unaccent(sql_left),
                sql_operator,
                unaccent(sql_right),
                base_condition,
            )
        return base_condition


class Char(BaseString):
    type = "char"
    trim: bool = True

    def _setup_attrs__(self, model_class: type[BaseModel], name: str) -> None:
        super()._setup_attrs__(model_class, name)
        assert self.size is None or isinstance(self.size, int), (
            f"Char field {self} with non-integer size {self.size!r}"
        )

    @property
    def _column_type(self) -> tuple[str, str]:
        return ("varchar", pg_varchar(self.size))

    @override
    def update_db_column(self, model: ModelLike, column: dict[str, typing.Any]) -> None:
        if (
            column
            and self.column_type[0] == "varchar"
            and column["udt_name"] == "varchar"
            and column["character_maximum_length"]
            and (self.size is None or column["character_maximum_length"] < self.size)
        ):
            sql.convert_column(
                model.env.cr, model._table, self.name, self.column_type[1]
            )
        super().update_db_column(model, column)

    _related_size = property(attrgetter("size"))
    _related_trim = property(attrgetter("trim"))
    _description_size = property(attrgetter("size"))
    _description_trim = property(attrgetter("trim"))

    def get_depends(self, model: BaseModel) -> tuple[Iterable[str], Iterable[str]]:
        depends, depends_context = super().get_depends(model)

        if (
            self.name == "display_name"
            and self.compute
            and not self.store
            and model._rec_name
            and model._fields[model._rec_name].base_field.translate
            and "lang" not in depends_context
        ):
            depends_context = [*depends_context, "lang"]

        return depends, depends_context


class Text(BaseString):
    type = "text"
    _column_type = ("text", "text")


class Html(BaseString):
    type = "html"
    _column_type = ("text", "text")

    if not typing.TYPE_CHECKING:

        def __get__(self, record, owner=None):
            if record is None or len(record._ids) != 1:
                return Field.__get__(self, record, owner)
            record_id = record._ids[0]
            if not self._needs_translate_fallback(record_id):
                return Field.__get__(self, record, owner)
            env = record.env
            if not (
                not self.groups or env.su or record._has_field_access(self, "read")
            ):
                record._check_field_access(self, "read")
            fb_val = self._scalar_translate_fallback(env, record_id)
            if fb_val is not SENTINEL:
                return self.convert_to_record(fb_val, record)
            return Field.__get__(self, record, owner)

    sanitize: bool = True
    sanitize_overridable: bool = False
    sanitize_tags: bool = True
    sanitize_attributes: bool = True
    sanitize_style: bool = False
    sanitize_form: bool = True
    sanitize_conditional_comments: bool = True
    sanitize_output_method: str = "html"
    strip_style: bool = False
    strip_classes: bool = False

    @override
    def _get_attrs(
        self, model_class: type[BaseModel], name: str
    ) -> dict[str, typing.Any]:
        attrs = super()._get_attrs(model_class, name)
        if attrs.get("sanitize") == "email_outgoing":
            attrs["sanitize"] = True
            attrs.update(
                {
                    key: value
                    for key, value in {
                        "sanitize_tags": False,
                        "sanitize_attributes": False,
                        "sanitize_conditional_comments": False,
                        "sanitize_output_method": "xml",
                    }.items()
                    if key not in attrs
                }
            )
        elif attrs.get("translate") is True and attrs.get("sanitize", True):
            attrs["translate"] = html_translate
        return attrs

    _related_sanitize = property(attrgetter("sanitize"))
    _related_sanitize_tags = property(attrgetter("sanitize_tags"))
    _related_sanitize_attributes = property(attrgetter("sanitize_attributes"))
    _related_sanitize_style = property(attrgetter("sanitize_style"))
    _related_strip_style = property(attrgetter("strip_style"))
    _related_strip_classes = property(attrgetter("strip_classes"))

    _description_sanitize = property(attrgetter("sanitize"))
    _description_sanitize_tags = property(attrgetter("sanitize_tags"))
    _description_sanitize_attributes = property(attrgetter("sanitize_attributes"))
    _description_sanitize_style = property(attrgetter("sanitize_style"))
    _description_strip_style = property(attrgetter("strip_style"))
    _description_strip_classes = property(attrgetter("strip_classes"))

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict | None = None,
        validate: bool = True,
    ) -> str | None:
        value = self._convert(value, record, validate=validate)
        return super().convert_to_column(value, record, values, validate=False)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> str | None:
        return self._convert(value, record, validate)

    def _convert(
        self, value: typing.Any, record: ModelLike, validate: bool
    ) -> str | None:
        if value is None or value is False:
            return None

        if not validate or not self.sanitize:
            return value

        sanitize_vals = {
            "silent": True,
            "sanitize_tags": self.sanitize_tags,
            "sanitize_attributes": self.sanitize_attributes,
            "sanitize_style": self.sanitize_style,
            "sanitize_form": self.sanitize_form,
            "sanitize_conditional_comments": self.sanitize_conditional_comments,
            "output_method": self.sanitize_output_method,
            "strip_style": self.strip_style,
            "strip_classes": self.strip_classes,
        }

        if self.sanitize_overridable:
            if record.env.user.has_group("base.group_sanitize_override"):
                return value

            for rec in record:
                self._check_overridable_content(rec, sanitize_vals)

        return html_sanitize(value, **sanitize_vals)

    def _check_overridable_content(
        self, record: ModelLike, sanitize_vals: dict
    ) -> None:
        original_value = record[self.name]
        if original_value:
            original_value_sanitized = html_sanitize(original_value, **sanitize_vals)
            original_value_normalized = html_normalize(original_value)

            if (
                not original_value_sanitized
                or original_value_normalized != original_value_sanitized
            ):
                diff = unified_diff(
                    original_value_sanitized.splitlines(),
                    original_value_normalized.splitlines(),
                )

                from odoo.logutils import root_handler_uses_colors

                with_colors = root_handler_uses_colors()
                diff_str = f"The field ({record._description}, {self.string}) will not be editable:\n"
                for line in list(diff)[2:]:
                    if with_colors:
                        color = {"-": RED, "+": GREEN}.get(line[:1], DEFAULT)
                        diff_str += colorize(line.rstrip() + "\n", color)
                    else:
                        diff_str += line.rstrip() + "\n"
                _logger.info(diff_str)

                raise UserError(
                    record.env._(
                        "The field value you're saving (%(model)s %(field)s) includes content that is "
                        "restricted for security reasons. It is possible that someone "
                        "with higher privileges previously modified it, and you are therefore "
                        "not able to modify it yourself while preserving the content.",
                        model=record._description,
                        field=self.string,
                    )
                )

    @override
    def convert_to_record(
        self, value: typing.Any, record: ModelLike
    ) -> Markup | typing.Literal[False]:
        r = super().convert_to_record(value, record)
        if isinstance(r, bytes):
            r = r.decode()
        return r and Markup(r)

    @override
    def convert_to_read(
        self,
        value: typing.Any,
        record: ModelLike,
        use_display_name: bool = True,
    ) -> Markup | typing.Literal[False]:
        r = super().convert_to_read(value, record, use_display_name)
        if isinstance(r, bytes):
            r = r.decode()
        return r and Markup(r)

    @override
    def get_trans_terms(self, value: str | None) -> list[str]:
        return list(map(str, super().get_trans_terms(value)))


class LangProxyDict(collections.abc.MutableMapping):
    __slots__ = ("_cache", "_field", "_lang")

    def __init__(self, field: BaseString, cache: dict, lang: str) -> None:
        super().__init__()
        self._field = field
        self._cache = cache
        self._lang = lang

    def get(self, key: IdType, default: typing.Any = None) -> typing.Any:
        vals = self._cache.get(key, SENTINEL)
        if vals is SENTINEL:
            return default
        if vals is None:
            return None
        if not (self._field.compute or (self._field.store and (key or key.origin))):
            return vals.get(self._lang, vals.get("en_US", default))
        return vals.get(self._lang, default)

    def __getitem__(self, key: IdType) -> typing.Any:
        vals = self._cache[key]
        if vals is None:
            return None
        if not (self._field.compute or (self._field.store and (key or key.origin))):
            return vals.get(self._lang, vals.get("en_US"))
        return vals[self._lang]

    def __setitem__(self, key: IdType, value: typing.Any) -> None:
        if value is None:
            self._cache[key] = None
            return
        vals = self._cache.get(key)
        if vals is None:
            self._cache[key] = vals = {self._lang: value}
        else:
            vals[self._lang] = value
        if not (self._field.compute or (self._field.store and (key or key.origin))):
            vals.setdefault("en_US", value)

    def __delitem__(self, key: IdType) -> None:
        vals = self._cache.get(key)
        if vals:
            vals.pop(self._lang, None)

    def __iter__(self) -> typing.Iterator[IdType]:
        for key, vals in self._cache.items():
            if vals is None or self._lang in vals:
                yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def clear(self) -> None:
        for vals in self._cache.values():
            if vals:
                vals.pop(self._lang, None)

    def __repr__(self) -> str:
        return f"<LangProxyDict lang={self._lang!r} size={len(self._cache)} at {hex(id(self))}>"
