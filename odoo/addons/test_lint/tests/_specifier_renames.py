# Specifiers upstream 19.0 still imports and the fork moved or retired. The
# specifier gate names the replacement when it meets one, so an upstream import
# is a lookup instead of a hunt. Add a row whenever a fork commit moves a module.

RENAMED = {
    "@web/core/l10n/translation": "@web/core/translation",
    "@web/core/confirmation_dialog/confirmation_dialog": (
        "@web/ui/dialog/confirmation_dialog"
    ),
    "@web/core/errors/error_dialogs": "@web/components/errors/error_dialogs",
    "@web/core/popover/popover_hook": "@web/ui/popover/popover_hook",
    "@web/core/tooltip/tooltip": "@web/ui/tooltip/tooltip",
    "@web/core/dialog/dialog": "@web/ui/dialog/dialog",
    "@web/core/dropdown/dropdown_item": "@web/components/dropdown/dropdown_item",
    "@web/core/utils/strings": "@web/core/utils/format/strings",
    "@web/core/orm_service": "@web/core/network/orm_service",
    "@web/views/fields/char/char_field": "@web/fields/basic/char/char_field",
    "@web/views/fields/selection/selection_field": (
        "@web/fields/selection/selection/selection_field"
    ),
}

RETIRED = {
    "@web/legacy/js/public/public_widget": (
        "public widgets were retired with @web/legacy; port to a "
        "registry.category('public.interactions') Interaction"
    ),
    "@web/legacy/js/core/dom": "retired with @web/legacy; use the DOM API directly",
    "@web/model/relational_model/utils": (
        "split across @web/model/relational_model/*; no single counterpart"
    ),
    "@website/js/content/menu": (
        "the website menu is a set of Interactions under @website/interactions/header/"
    ),
}


def hint(spec: str) -> str:
    if spec in RENAMED:
        return f"; the fork moved it to {RENAMED[spec]!r}"
    if spec in RETIRED:
        return f"; {RETIRED[spec]}"
    return ""
