// @ts-check
/** @odoo-module native */

/** @module @web/views/view_hook - Hooks for action links, record export, and record deletion in views */

import { useComponent, useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { SearchModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { download } from "@web/core/network/download";
import { rpc } from "@web/core/network/rpc";
import { evaluateExpr } from "@web/core/py_js/py";
import { useBus, useService } from "@web/core/utils/hooks";
import { DynamicList } from "@web/model/relational_model/dynamic_list";
import {
    ConfirmationDialog,
    deleteConfirmationMessage,
} from "@web/ui/dialog/confirmation_dialog";
import { ExportDataDialog } from "@web/views/view_dialogs/export_data_dialog";

/**
 * Allows for a component (usually a View component) to handle links with
 * attribute type="action". This is used to support onboarding banners and content helpers.
 *
 * A @web/core/concurrency:KeepLast must be present in the owl environment to allow coordinating
 * between clicks. (env.keepLast)
 *
 * This is similar but quite different from action buttons, since action links
 * are not dynamic according to the record.
 * @param {Object} params
 * @param  {String} params.resModel The default resModel to which actions will apply
 * @param  {Function} [params.reload] The function to execute to reload, if a button has data-reload-on-close
 */
export function useActionLinks({ resModel, reload }) {
    const component = useComponent();
    const keepLast = component.env.keepLast;

    const orm = useService("orm");
    const { doAction } = useService("action");

    async function handler(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        let target = ev.target;
        if (target.tagName !== "A") {
            target = target.closest("a");
        }
        const data = target.dataset;

        if (data.method !== undefined && data.model !== undefined) {
            const options = {};
            if (data.reloadOnClose) {
                options.onClose = reload || (() => component.render());
            }
            const action = await keepLast.add(orm.call(data.model, data.method));
            if (action !== undefined) {
                keepLast.add(Promise.resolve(doAction(action, options)));
            }
        } else if (target.getAttribute("name")) {
            const options = {};
            if (data.context) {
                options.additionalContext = evaluateExpr(data.context);
            }
            keepLast.add(doAction(target.getAttribute("name"), options));
        } else {
            let views;
            const parsedId = data.resid ? Number.parseInt(data.resid, 10) : null;
            const resId = Number.isNaN(parsedId) ? null : parsedId;
            if (data.views) {
                views = evaluateExpr(data.views);
            } else {
                views = resId
                    ? [[false, "form"]]
                    : [
                          [false, "list"],
                          [false, "form"],
                      ];
            }
            const action = {
                name: target.getAttribute("title") || target.textContent.trim(),
                type: "ir.actions.act_window",
                res_model: data.model || resModel,
                target: "current",
                views,
                domain: data.domain ? evaluateExpr(data.domain) : [],
            };
            if (resId) {
                action.res_id = resId;
            }

            const options = {};
            if (data.context) {
                options.additionalContext = evaluateExpr(data.context);
            }
            // ``action`` is a synthesised ``ir.actions.act_window`` descriptor
            // built from the anchor's data attributes; the ``ActionRequest``
            // ambient type doesn't model every legal field combination so we
            // narrow at the boundary.
            keepLast.add(doAction(/** @type {any} */ (action), options));
        }
    }

    return (ev) => {
        const a = ev.target.closest(`a[type="action"]`);
        if (a && ev.currentTarget.contains(a)) {
            handler(ev);
        }
    };
}

/**
 * Applies a brief CSS bounce animation to a `[data-bounce-button]` element
 * whenever a click occurs inside `containerRef` and `shouldBounce` returns true.
 *
 * @param {{ el: HTMLElement | null }} containerRef - OWL ref wrapping the click zone
 * @param {(target: HTMLElement) => boolean} shouldBounce - predicate checked on every click
 */
export function useBounceButton(containerRef, shouldBounce) {
    let timeout;
    const ui = useService("ui");
    useEffect(
        (containerEl) => {
            if (!containerEl) {
                return;
            }
            const handler = (ev) => {
                // Cast: TS cannot synthesize a call signature for the
                // ``Document | HTMLElement`` union's generic querySelector.
                const activeElement = /** @type {ParentNode} */ (ui.activeElement);
                const button = activeElement?.querySelector("[data-bounce-button]");
                if (button && shouldBounce(ev.target)) {
                    button.classList.add("o_catch_attention");
                    browser.clearTimeout(timeout);
                    timeout = browser.setTimeout(() => {
                        button.classList.remove("o_catch_attention");
                    }, 400);
                }
            };
            containerEl.addEventListener("click", handler);
            return () => {
                browser.clearTimeout(timeout);
                containerEl.removeEventListener("click", handler);
            };
        },
        () => [containerRef.el],
    );
}

/**
 * Hook that wires up the export-records flow (dialog + direct download).
 *
 * Listens for `direct-export-data` on the searchModel bus and opens the
 * ExportDataDialog when the returned callback is invoked.
 *
 * @param {Object} env - OWL component environment (must have `model` and `searchModel`)
 * @param {Object} context - action context
 * @param {() => Object[]} getDefaultExportList - returns default fields for export
 * @returns {() => void} callback that opens the export dialog
 */
export function useExportRecords(env, context, getDefaultExportList) {
    const { model, searchModel } = env;
    const dialog = useService("dialog");
    useBus(searchModel, SearchModelEvent.DIRECT_EXPORT_DATA, async () => {
        _downloadExport(getDefaultExportList(), false, "xlsx");
    });
    const _getExportedFields = async (isCompatible, parentParams) => {
        const root = model.root;
        let domain = parentParams ? [] : root.domain;
        // Only scope by the current selection for the ROOT model's own fields.
        // A subfield expansion (parentParams set) queries a *child* model, so
        // the parent recordset ids must not leak in as its domain — that would
        // filter the child's fields by a bogus, foreign id set.
        if (!parentParams && !root.isDomainSelected && root.selection.length) {
            const ids = root.selection.map((e) => e.resId);
            domain = [["id", "in", ids]];
        }
        return await rpc("/web/export/get_fields", {
            model: root.resModel,
            domain,
            import_compat: isCompatible,
            ...parentParams,
        });
    };

    const _downloadExport = async (fields, import_compat, format) => {
        const root = model.root;
        const exportedFields = fields.map((field) => ({
            name: field.name || field.id,
            label: field.label || field.string,
            store: field.store,
            type: field.field_type || field.type,
        }));
        if (import_compat) {
            exportedFields.unshift({
                name: "id",
                label: _t("External ID"),
            });
        }
        await download({
            data: {
                data: JSON.stringify({
                    import_compat,
                    context: root.context,
                    domain: root.domain,
                    fields: exportedFields,
                    groupby: root.groupBy,
                    ids:
                        !root.isDomainSelected && root.selection.length
                            ? root.selection.map((e) => e.resId)
                            : false,
                    model: root.resModel,
                }),
            },
            url: `/web/export/${format}`,
        });
    };

    return () => {
        const root = model.root;
        dialog.add(ExportDataDialog, {
            context: root.context,
            defaultExportList: getDefaultExportList(),
            download: _downloadExport,
            getExportedFields: _getExportedFields,
            root,
        });
    };
}

/**
 * Hook that returns a callback for deleting records with a confirmation dialog.
 *
 * Handles both single-record (form) and multi-record (list/kanban) deletion,
 * adjusting the dialog body text and confirm callback accordingly.
 *
 * @param {Object} model - the view's relational model instance
 * @returns {(dialogProps?: Object, records?: Object[]) => void} opens a confirmation dialog then deletes
 */
export function useDeleteRecords(model) {
    const dialog = useService("dialog");
    function getDefaultDialogProps(records) {
        const isDynamicList = model.root instanceof DynamicList;
        let body = deleteConfirmationMessage;
        if (
            records?.length > 1 ||
            (isDynamicList &&
                (model.root.isDomainSelected || model.root.selection.length > 1))
        ) {
            body = _t("Are you sure you want to delete these records?");
        }
        let confirm = () => Promise.all(records.map((r) => r.delete()));
        if (isDynamicList) {
            confirm = () => model.root.deleteRecords(records);
        }
        return {
            body,
            cancel: () => {},
            cancelLabel: _t("No, keep it"),
            confirm,
            confirmLabel: _t("Delete"),
            title: _t("Bye-bye, record!"),
        };
    }
    return (dialogProps, records) => {
        const defaultProps = getDefaultDialogProps(records);
        dialog.add(ConfirmationDialog, { ...defaultProps, ...dialogProps });
    };
}
