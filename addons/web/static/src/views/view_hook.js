// @ts-check
/** @odoo-module native */

/** @module @web/views/view_hook */

import { useComponent, useEffect } from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { browser } from "@web/core/browser/browser";
import { SearchModelEvent } from "@web/core/events";
import { download } from "@web/core/network/download";
import { rpc } from "@web/core/network/rpc";
import { evaluateExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { orderByToString } from "@web/core/utils/order_by";
import { DynamicList } from "@web/model/relational_model/dynamic_list";
import {
    ConfirmationDialog,
    deleteConfirmationMessage,
} from "@web/ui/dialog/confirmation_dialog";
import { ExportDataDialog } from "@web/views/view_dialogs/export_data_dialog";

/**
 * @param {Object} params
 * @param {String} params.resModel
 * @param {Function} [params.reload]
 */
export function useActionLinks({ resModel, reload }) {
    const component = useComponent();
    const keepLast = component.env.keepLast;

    const orm = useService("orm");
    const { doAction } = useAction();

    /**
     * @param {Event} ev
     * @param {HTMLAnchorElement} target
     */
    async function handler(ev, target) {
        ev.preventDefault();
        ev.stopPropagation();
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
                name: target.getAttribute("title") || target.textContent?.trim() || "",
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
            keepLast.add(doAction(/** @type {any} */ (action), options));
        }
    }

    return (ev) => {
        const a = ev.target.closest(`a[type="action"]`);
        if (a && ev.currentTarget.contains(a)) {
            handler(ev, a);
        }
    };
}

/**
 * @param {{ el: HTMLElement | null }} containerRef
 * @param {(target: HTMLElement) => boolean} shouldBounce
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
 * @param {Object} env
 * @param {() => Object[]} getDefaultExportList
 * @returns {() => void}
 */
export function useExportRecords(env, getDefaultExportList) {
    const { model, searchModel } = env;
    const dialog = useService("dialog");
    useBus(searchModel, SearchModelEvent.DIRECT_EXPORT_DATA, () =>
        _downloadExport(getDefaultExportList(), false, "xlsx"),
    );
    const _getExportedFields = async (isCompatible, parentParams) => {
        const root = model.root;
        let domain = parentParams ? [] : root.domain;
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
        const orderBy = (root.orderBy || []).filter((o) => o.name !== "__count");
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
                    order: orderBy.length ? orderByToString(orderBy) : undefined,
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
 * @param {Object} model
 * @returns {(dialogProps?: Object, records?: Object[]) => void}
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
        let confirm = () => Promise.all((records ?? []).map((r) => r.delete()));
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
