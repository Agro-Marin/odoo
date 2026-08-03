// @ts-check
/** @odoo-module native */

/** @module @web/core/record_dialog_port */

import { registry } from "@web/core/registry";

/**
 * The consumer-facing surface of the two record dialogs implemented in `views/`.
 *
 * `SelectCreateDialog` and `FormViewDialog` are implemented in
 * `@web/views/view_dialogs/` because they mount a real view — arch, model,
 * controller, the lot — which is a `views/` concern. Their *interface* is not:
 * `components/` and `fields/` both need "let the user pick a record" and
 * "let the user create one in a form", and reaching the implementation directly
 * makes each of them depend upward on `views/`.
 *
 * This port publishes that interface below both consumers so they depend on the
 * contract instead. The two remaining upward edges are here, named and
 * deliberate, rather than spread across 5 call sites in 5 files — see
 * `tooling/architecture/js_registry_layering.py`, whose docstring prescribes
 * exactly this move ("a port published at the consumer's layer").
 *
 * **Why these return a constructor rather than opening the dialog.** Every
 * caller already owns a dialog-adding function — `useOwnedDialogs()`, or the
 * `dialog` service — and three of them pass a third `options` argument to it.
 * A port that opened the dialog itself would have to re-publish that whole
 * surface, so it publishes the one thing callers cannot get for themselves: the
 * component, resolved without naming `views/`.
 *
 * The lookup stays lazy. Both dialogs are registered by `views/` at module
 * evaluation time, and resolving at call time rather than at import time is what
 * lets a `core/`-layer module publish them at all without an import cycle.
 */

/** @typedef {import("registries").DialogsRegistryItemShape} DialogConstructor */

/**
 * The "pick one or more existing records, optionally creating one" dialog.
 *
 * @returns {DialogConstructor}
 */
export function getSelectCreateDialog() {
    return registry.category("dialogs").get("select_create");
}

/**
 * The "create or edit a record in a form view" dialog.
 *
 * @returns {DialogConstructor}
 */
export function getFormViewDialog() {
    return registry.category("dialogs").get("form_view");
}
