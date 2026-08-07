import logging
import typing
from contextlib import closing
from enum import IntEnum

from psycopg.types.json import Json

import odoo.api
import odoo.modules
import odoo.tools
from odoo.db import schema as _db_schema

from .registry import Registry

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor, Cursor

_logger = logging.getLogger(__name__)

_AUTO_INSTALL_CANDIDATES_QUERY = """
    SELECT m.name FROM ir_module_module m
    WHERE m.auto_install
    AND state not in ('to install', 'uninstallable')
    AND NOT EXISTS (
        SELECT 1 FROM ir_module_module_dependency d
        LEFT JOIN ir_module_module mdep ON (d.name = mdep.name)
        WHERE d.module_id = m.id
          AND (
              mdep.id IS NULL
              -- an uninstallable dependency (required or not) can never be
              -- satisfied, so the module cannot be installed at all
              OR mdep.state = 'uninstallable'
              OR (d.auto_install_required AND mdep.state != 'to install')
          )
    )"""

_AUTO_INSTALL_CLOSURE_QUERY = """
    SELECT d.name FROM ir_module_module_dependency d
    JOIN ir_module_module m ON (d.module_id = m.id)
    JOIN ir_module_module mdep ON (d.name = mdep.name)
    WHERE (m.state = 'to install' OR m.name = any(%s))
        -- don't re-mark marked modules
    AND NOT (mdep.state = 'to install' OR mdep.name = any(%s))
        -- never mark an uninstallable module: it cannot be installed, and
        -- overwriting its state would corrupt it (the dependent module is
        -- reported and skipped by the module graph at load time instead)
    AND mdep.state != 'uninstallable'
    """


def is_initialized(cr: Cursor) -> bool:
    return _db_schema.table_exists(cr, "ir_module_module")


def initialize(cr: Cursor) -> None:
    try:
        f = odoo.tools.misc.file_path("base/data/base_data.sql")
    except FileNotFoundError as e:
        m = "File not found: 'base/data/base_data.sql' (provided by module 'base')."
        _logger.critical(m)
        raise OSError(m) from e

    with odoo.tools.misc.file_open(f) as base_sql_file:
        cr.execute(base_sql_file.read())

    all_data_rows = []
    all_dep_rows = []
    category_cache: dict[str, int] = {}

    for info in odoo.modules.Manifest.all_addon_manifests():
        module_name = info.name
        categories = info["category"].split("/")
        category_id = create_categories(cr, categories, category_cache)

        if info["installable"]:
            state = "uninstalled"
        else:
            state = "uninstallable"

        cr.execute(
            """
            INSERT INTO ir_module_module
                (author, website, name, shortdesc, description,
                 category_id, auto_install, state, web, license, application, icon, sequence, summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                info["author"],
                info["website"],
                module_name,
                Json({"en_US": info["name"]}),
                Json({"en_US": info["description"]}),
                category_id,
                info["auto_install"] is not False,
                state,
                info["web"],
                info["license"],
                info["application"],
                info["icon"],
                info["sequence"],
                Json({"en_US": info["summary"]}),
            ),
        )
        row = cr.fetchone()
        assert row is not None
        module_id = row[0]

        all_data_rows.append(
            (
                "module_" + module_name,
                "ir.module.module",
                "base",
                module_id,
                True,
            ),
        )
        dependencies = info["depends"]
        all_dep_rows.extend(
            (module_id, d, d in (info["auto_install"] or ())) for d in dependencies
        )

    if all_data_rows:
        cr.copy_from(
            "ir_model_data",
            ["name", "model", "module", "res_id", "noupdate"],
            all_data_rows,
        )
    if all_dep_rows:
        cr.copy_from(
            "ir_module_module_dependency",
            ["module_id", "name", "auto_install_required"],
            all_dep_rows,
        )

    if odoo.tools.config.get("skip_auto_install"):
        cr.execute(
            """UPDATE ir_module_module SET state='to install' WHERE name = 'base'"""
        )
        return

    while True:
        cr.execute(_AUTO_INSTALL_CANDIDATES_QUERY)
        to_auto_install = [x[0] for x in cr.fetchall()]
        cr.execute(_AUTO_INSTALL_CLOSURE_QUERY, [to_auto_install, to_auto_install])
        to_auto_install.extend(x[0] for x in cr.fetchall())

        if not to_auto_install:
            break
        cr.execute(
            """UPDATE ir_module_module SET state='to install' WHERE name = ANY(%s)""",
            (list(to_auto_install),),
        )


def create_categories(
    cr: Cursor,
    categories: list[str],
    category_cache: dict[str, int] | None = None,
) -> int | None:
    p_id = None
    built = []
    for cat_name in categories:
        built.append(cat_name)
        xml_id = "module_category_" + ("_".join(x.lower() for x in built)).replace(
            "&", "and"
        ).replace(" ", "_")
        if category_cache is not None and xml_id in category_cache:
            p_id = category_cache[xml_id]
            continue
        cr.execute(
            "SELECT res_id FROM ir_model_data WHERE name=%s AND module=%s AND model=%s",
            (xml_id, "base", "ir.module.category"),
        )

        row = cr.fetchone()
        if not row:
            cr.execute(
                """
                INSERT INTO ir_module_category (name, parent_id)
                VALUES (%s, %s) RETURNING id
            """,
                (Json({"en_US": cat_name}), p_id),
            )
            row = cr.fetchone()
            assert row is not None
            p_id = row[0]
            cr.execute(
                """
                INSERT INTO ir_model_data (module, name, res_id, model, noupdate)
                VALUES (%s, %s, %s, %s, %s)
            """,
                ("base", xml_id, p_id, "ir.module.category", True),
            )
        else:
            p_id = row[0]
        assert isinstance(p_id, int)
        if category_cache is not None:
            category_cache[xml_id] = p_id
    return p_id


class FunctionStatus(IntEnum):
    MISSING = 0
    PRESENT = 1
    INDEXABLE = 2


def has_unaccent(cr: BaseCursor) -> FunctionStatus:
    cr.execute("""
        SELECT p.provolatile
        FROM pg_proc p
        WHERE p.proname = 'unaccent'
              AND p.pronamespace = current_schema::regnamespace
              AND p.pronargs = 1
    """)
    result = cr.fetchone()
    if not result:
        return FunctionStatus.MISSING
    return FunctionStatus.INDEXABLE if result[0] == "i" else FunctionStatus.PRESENT


def has_trigram(cr: BaseCursor) -> bool:
    cr.execute("""
        SELECT 1 FROM pg_proc
        WHERE proname = 'word_similarity'
          AND pronamespace = current_schema::regnamespace
    """)
    return bool(cr.fetchone())


def initialize_db(
    db_name: str,
    demo: bool,
    lang: str | None,
    user_password: str,
    login: str = "admin",
    country_code: str | None = None,
    phone: str | None = None,
) -> None:
    normalized_country = country_code.upper() if country_code else None

    saved_load_language = odoo.tools.config.get("load_language")
    try:
        odoo.tools.config["load_language"] = lang

        registry = Registry.new(db_name, update_module=True, new_db_demo=demo)

        with closing(registry.cursor()) as cr:
            env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})

            if lang:
                modules = env["ir.module.module"].search([("state", "=", "installed")])
                modules._update_translations(lang)

            if normalized_country:
                country = env["res.country"].search(
                    [("code", "ilike", normalized_country)], limit=1
                )
                if country:
                    company_values = {"country_id": country.id}
                    if country.currency_id:
                        company_values["currency_id"] = country.currency_id.id
                    env["res.company"].browse(1).write(company_values)
                    from odoo.libs.datetime import country_timezones

                    tz_mapping = country_timezones()
                    if len(tz_mapping.get(normalized_country, [])) == 1:
                        users = env["res.users"].search([])
                        users.write({"tz": tz_mapping[normalized_country][0]})

            if phone:
                env["res.company"].browse(1).write({"phone": phone})

            if login and "@" in login:
                env["res.company"].browse(1).write({"email": login})

            values = {"password": user_password, "lang": lang}
            if login:
                values["login"] = login
                emails = odoo.tools.email_split(login)
                if emails:
                    values["email"] = emails[0]
            env.ref("base.user_admin").write(values)

            cr.commit()
    except Exception:
        _logger.exception("CREATE DATABASE failed:")
        raise
    finally:
        if saved_load_language is None:
            odoo.tools.config.pop("load_language", None)
        else:
            odoo.tools.config["load_language"] = saved_load_language
