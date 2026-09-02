import collections.abc
import typing
from collections import defaultdict
from difflib import get_close_matches
from hashlib import sha256

from markupsafe import escape as markup_escape

from odoo.tools import SQL
from odoo.tools.misc import SENTINEL, OrderedSet

from ..primitives import NewId
from .base import Field

_EN_US_KEY = ("en_US",)

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, MutableMapping

    from .._typing import BaseModel, IdType, ModelLike
    from ..runtime import Environment
    from .textual import BaseString


def _term_lookup(
    dictionary: dict[str, dict[str, str]], lang: str
) -> typing.Callable[[str], str | None]:
    return lambda term: dictionary.get(term, {lang: None})[lang]


def _id_or_origin(key: IdType) -> IdType | None:
    return key or (key.origin if isinstance(key, NewId) else None)


def is_fallback_required(field: BaseString, record_id: typing.Any) -> bool:
    return field.translate is True and not (
        field.compute
        or (field.store and (record_id or getattr(record_id, "origin", None)))
    )


def lang_cache_key(field: BaseString, env: Environment, lang: str) -> tuple:
    cache_key = env.cache_key(field)
    if len(cache_key) == 1:
        return _EN_US_KEY if lang == "en_US" else (lang,)
    return (lang, *cache_key[1:])


def fallback_cache_key(field: BaseString, env: Environment) -> tuple:
    return lang_cache_key(field, env, "en_US")


def scalar_fallback(
    field: BaseString, env: Environment, record_id: typing.Any
) -> typing.Any:
    cur_val = field._get_cache(env).get(record_id, SENTINEL)
    if cur_val is not SENTINEL:
        return cur_val
    fb_cache = env._core.get_context_data_or_none(field, fallback_cache_key(field, env))
    if fb_cache is not None:
        return fb_cache.get(record_id, SENTINEL)
    return SENTINEL


def trans_terms(field: BaseString, value: str | None) -> list[str]:
    if not callable(field.translate):
        return [value] if value else []
    terms: list[str] = []
    field.translate(terms.append, value)
    return terms


def text_content(field: BaseString, term: str) -> str:
    func = getattr(field.translate, "get_text_content", lambda term: term)
    return func(term)


def translation_lang(field: BaseString, env: Environment) -> str:
    return (env.lang or "en_US") if field.translate is True else env._lang


def fallback_langs(field: BaseString, env: Environment) -> tuple[str, ...]:
    lang = translation_lang(field, env)
    if lang == "_en_US":
        return "_en_US", "en_US"
    if lang == "en_US":
        return ("en_US",)
    if lang.startswith("_"):
        return lang, lang[1:], "_en_US", "en_US"
    return lang, "en_US"


def translation_dictionary(
    field: BaseString,
    from_lang_value: str,
    to_lang_values: dict[str, str],
) -> dict[str, dict[str, str]]:
    from_lang_terms = field.get_trans_terms(from_lang_value)
    dictionary: defaultdict[str, dict[str, str]] = defaultdict(dict)
    if not from_lang_terms:
        return dictionary
    dictionary.update({from_lang_term: {} for from_lang_term in from_lang_terms})

    for lang, to_lang_value in to_lang_values.items():
        to_lang_terms = field.get_trans_terms(to_lang_value)
        if len(from_lang_terms) != len(to_lang_terms):
            for from_lang_term in from_lang_terms:
                dictionary[from_lang_term][lang] = from_lang_term
        else:
            for from_lang_term, to_lang_term in zip(
                from_lang_terms, to_lang_terms, strict=True
            ):
                dictionary[from_lang_term][lang] = to_lang_term
    return dictionary


def stored_translations(field: BaseString, record: ModelLike) -> dict[str, str] | None:
    record.flush_recordset([field.name])
    cr = record.env.cr
    cr.execute(
        SQL(
            "SELECT %s FROM %s WHERE id = %s",
            SQL.identifier(field.name),
            SQL.identifier(record._table),
            record.id,
        )
    )
    res = cr.fetchone()
    return res[0] if res else None


def edit_translations_value(
    field: BaseString, value: typing.Any, record: ModelLike
) -> typing.Any:
    dialect = field.translate
    assert callable(dialect)
    base_lang = record._get_base_lang()
    lang = record.env.lang or "en_US"
    delay_translation = (
        value
        != record.with_context(
            edit_translations=None, check_translations=None, lang=lang
        )[field.name]
    )

    if lang != base_lang:
        base_value = record.with_context(
            edit_translations=None,
            check_translations=True,
            lang=base_lang,
        )[field.name]
        base_terms = field.get_trans_terms(base_value)
        translated_terms = (
            field.get_trans_terms(value) if value != base_value else base_terms
        )
        if len(base_terms) != len(translated_terms):
            value = base_value
            translated_terms = base_terms
        get_base = dict(zip(translated_terms, base_terms, strict=True)).__getitem__
    else:

        def get_base(term):
            return term

    def translate_func(term):
        source_term = get_base(term)
        translation_state = (
            "translated" if lang == base_lang or source_term != term else "to_translate"
        )
        translation_source_sha = sha256(source_term.encode()).hexdigest()
        return (
            "<span "
            f"""{'class="o_delay_translation" ' if delay_translation else ""}"""
            f'data-oe-model="{markup_escape(record._name)}" '
            f'data-oe-id="{markup_escape(record.id)}" '
            f'data-oe-field="{markup_escape(field.name)}" '
            f'data-oe-translation-state="{translation_state}" '
            f'data-oe-translation-source-sha="{translation_source_sha}"'
            ">"
            f"{term}"
            "</span>"
        )

    return dialect(translate_func, value)


def insert_cache(
    field: BaseString, records: ModelLike, values: Iterable[typing.Any]
) -> None:
    env = records.env
    if field.translate is True:
        if env.context.get("prefetch_langs"):
            core = env._core
            sub_caches: dict[str, dict] = {}

            def sub_cache(lang: str) -> dict:
                sub = sub_caches.get(lang)
                if sub is None:
                    sub = sub_caches[lang] = core.get_context_data(
                        field, lang_cache_key(field, env, lang)
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
            Field._insert_cache(field, records, values)
        return

    field_cache = env._core.get_field_data(field)
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
        lang = translation_lang(field, env)
        for id_, val in zip(records._ids, values, strict=True):
            if val is None:
                field_cache.setdefault(id_, None)
            else:
                cache_value = field_cache.setdefault(id_, {})
                if cache_value is not None:
                    cache_value.setdefault(lang, val)


def update_cache(
    field: BaseString, records: ModelLike, cache_value: typing.Any, dirty: bool
) -> bool:
    if field.translate is True and isinstance(cache_value, dict):
        env = records.env
        core = env._core
        ids = records._ids
        for lang, scalar in cache_value.items():
            if lang.startswith("_"):
                continue
            sub = core.get_context_data(field, lang_cache_key(field, env, lang))
            if len(ids) <= 1:
                if ids:
                    sub[ids[0]] = scalar
            else:
                sub.update(dict.fromkeys(ids, scalar))
        if field.is_column and dirty:
            core.mark_dirty(field, (id_ for id_ in ids if id_))
        return True
    if field.translate is True:
        Field._update_cache(field, records, cache_value, dirty)
        if not field.compute and not any(
            id_ or getattr(id_, "origin", None) for id_ in records._ids
        ):
            en_cache = records.env._core.get_context_data(
                field, fallback_cache_key(field, records.env)
            )
            for id_ in records._ids:
                en_cache.setdefault(id_, cache_value)
        return True
    if records.env.context.get("prefetch_langs"):
        assert isinstance(cache_value, dict), f"invalid cache value for {field}"
        if len(records) > 1:
            for record in records:
                Field._update_cache(field, record, dict(cache_value), dirty)
            return True
    return False


def mark_dirty(field: BaseString, records: BaseModel, value: typing.Any) -> None:
    records, cache_value = field._mark_dirty_prologue(records, value)
    if not records:
        return
    dirty_ids = records.env._core.get_dirty(field) or ()
    _flush_pending_none(field, records, dirty_ids)

    lang = translation_lang(field, records.env)
    if not (field.store and any(records._ids)):
        _mark_dirty_unstored(field, records, cache_value, lang)
    elif not callable(field.translate):
        _mark_dirty_model_translation(field, records, cache_value, lang, dirty_ids)
    else:
        mark_dirty_model_term_translation(field, records, cache_value, lang)


def _flush_pending_none(
    field: BaseString, records: BaseModel, dirty_ids: typing.Any
) -> None:
    dirty_records = records.filtered(lambda rec: rec.id in dirty_ids)
    if not dirty_records:
        return
    if field.translate is True:
        has_dirty_none = any(
            sub.get(rid, SENTINEL) is None
            for _key, sub in records.env._core.iter_context_caches(field)
            for rid in dirty_records._ids
        )
    else:
        field_cache = field._get_cache(records.env)
        has_dirty_none = any(
            field_cache.get(record_id, SENTINEL) is None
            for record_id in dirty_records._ids
        )
    if has_dirty_none:
        dirty_records.flush_recordset([field.name])
        if field.translate is True:
            field._invalidate_cache(records.env, dirty_records._ids)


def _mark_dirty_unstored(
    field: BaseString, records: BaseModel, cache_value: typing.Any, lang: str
) -> None:
    if field.compute and field.inverse and any(records._ids):
        if field.translate is True:
            field._invalidate_cache(records.env, records._ids)
        field._update_cache(
            records.with_context(prefetch_langs=True),
            {lang: cache_value},
            dirty=False,
        )
    else:
        field._update_cache(records, cache_value, dirty=False)


def _mark_dirty_model_translation(
    field: BaseString,
    records: BaseModel,
    cache_value: typing.Any,
    lang: str,
    dirty_ids: typing.Any,
) -> None:
    mirrored_ids = get_mirrored_ids_by_language(field, records, lang, dirty_ids)
    clean_records = records.filtered(lambda rec: rec.id not in dirty_ids)
    clean_records.invalidate_recordset([field.name])
    field._update_cache(records, cache_value, dirty=True)
    if lang != "en_US" and not records.env["res.lang"]._get_data(code="en_US"):
        field._update_cache(records.with_context(lang="en_US"), cache_value, dirty=True)
    for other_lang, ids in mirrored_ids.items():
        field._update_cache(
            records.browse(ids).with_context(lang=other_lang),
            cache_value,
            dirty=True,
        )


def get_mirrored_ids_by_language(
    field: BaseString,
    records: BaseModel,
    lang: str,
    dirty_ids: typing.Any,
) -> dict[str, list]:
    ids = [id_ for id_ in records._ids if id_]
    if not ids or not records.env.backend.supports_translation_terms:
        return {}
    if lang == "en_US" and not records.env["res.lang"]._get_data(code="en_US"):
        return {}
    stored = _stored_translations_multi(field, records.browse(ids), dirty_ids)
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


def _stored_translations_multi(
    field: BaseString,
    records: BaseModel,
    dirty_ids: typing.Any,
) -> dict[IdType, dict[str, str] | None]:
    pending = records.filtered(lambda rec: rec.id in (dirty_ids or ()))
    if pending:
        pending.flush_recordset([field.name])
    cr = records.env.cr
    cr.execute(
        SQL(
            "SELECT id, %s FROM %s WHERE id IN %s",
            SQL.identifier(field.name),
            SQL.identifier(records._table),
            tuple(records._ids),
        )
    )
    return dict(cr.fetchall())


def mark_dirty_model_term_translation(
    field: BaseString, records: BaseModel, cache_value: typing.Any, lang: str
) -> None:
    dialect = field.translate
    if not callable(dialect):
        raise TypeError(f"{field} has no translation dialect to mark terms with")
    new_translations_list: list[dict[str, typing.Any]] = []
    new_terms = set(field.get_trans_terms(cache_value))
    delay_translations = records.env.context.get("delay_translations")
    for record in records:
        if not new_terms:
            new_translations_list.append({"en_US": cache_value, lang: cache_value})
            continue
        stored = field._get_stored_translations(record)
        if not stored:
            new_translations_list.append({"en_US": cache_value, lang: cache_value})
            continue
        old_translations = {
            k: stored.get(f"_{k}", v)
            for k, v in stored.items()
            if not k.startswith("_")
        }
        fallback_value = old_translations.get("en_US")
        if fallback_value is None:
            fallback_value = next(iter(old_translations.values()), cache_value)
        from_lang_value = old_translations.pop(lang, fallback_value)
        dictionary = field.get_translation_dictionary(from_lang_value, old_translations)
        reconcile_obsolete_terms(field, dictionary, new_terms, lang, records.env)
        new_translations: dict[str, typing.Any] = {
            l: dialect(_term_lookup(dictionary, l), cache_value)
            for l in old_translations
        }
        if delay_translations:
            new_store_translations = stored
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
        field._update_cache(record, new_translation, dirty=True)


def reconcile_obsolete_terms(
    field: BaseString,
    translation_dictionary: dict,
    new_terms: set,
    lang: str,
    env: Environment,
) -> None:
    text2terms = defaultdict(list)
    for term in new_terms:
        if term_text := field.get_text_content(term):
            text2terms[term_text].append(term)

    is_text = getattr(field.translate, "is_text", None) or (lambda term: True)
    term_adapter = getattr(field.translate, "term_adapter", None)
    for old_term in list(translation_dictionary.keys()):
        if old_term in new_terms:
            continue
        old_term_text = field.get_text_content(old_term)
        matches = get_close_matches(old_term_text, text2terms, 1, 0.9)
        if not matches:
            continue
        closest_term = get_close_matches(old_term, text2terms[matches[0]], 1, 0)[0]
        if closest_term in translation_dictionary:
            continue
        old_is_text = is_text(old_term)
        closest_is_text = is_text(closest_term)
        if not (old_is_text or not closest_is_text):
            continue
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
                k: adapter(v) for k, v in translation_dictionary.pop(old_term).items()
            }
        else:
            translation_dictionary[closest_term] = translation_dictionary.pop(old_term)


class LangProxyDict(collections.abc.MutableMapping):
    __slots__ = ("_cache", "_field", "_lang")

    def __init__(
        self, field: BaseString, cache: MutableMapping[IdType, typing.Any], lang: str
    ) -> None:
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
        if not (self._field.compute or (self._field.store and _id_or_origin(key))):
            return vals.get(self._lang, vals.get("en_US", default))
        return vals.get(self._lang, default)

    def __getitem__(self, key: IdType) -> typing.Any:
        vals = self._cache[key]
        if vals is None:
            return None
        if not (self._field.compute or (self._field.store and _id_or_origin(key))):
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
        if not (self._field.compute or (self._field.store and _id_or_origin(key))):
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
