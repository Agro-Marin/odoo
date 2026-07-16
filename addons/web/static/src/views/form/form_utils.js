// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_utils - Utility functions for form views (sub-view loading, discard hooks, toolbar setup) */

/**
 * Extracted from form_controller.js to reduce file complexity; public API
 * preserved via re-exports.
 */

import { onWillDestroy } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { registry } from "@web/core/registry";
import { parseXML } from "@web/core/utils/dom/xml";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/services/user";
import { isX2Many } from "@web/views/view_utils";

const viewRegistry = registry.category("views");

/**
 * Fetch the list/kanban sub-view arch for each x2many field that needs one.
 *
 * @param {Object} fieldNodes - field node descriptors from the arch
 * @param {Object} fields - field definitions
 * @param {Object} context - current action context
 * @param {string} resModel - the parent model name
 * @param {Object} viewService - the view service instance
 * @param {boolean} isSmall - whether the screen is small (selects kanban over list)
 */
export async function loadSubViews(
    fieldNodes,
    fields,
    context,
    resModel,
    viewService,
    isSmall,
) {
    const fieldInfosToLoad = [];
    for (const fieldInfo of Object.values(fieldNodes)) {
        const fieldName = fieldInfo.name;
        const field = fields[fieldName];
        if (!isX2Many(field)) {
            continue; // what follows only concerns x2many fields
        }
        if (fieldInfo.invisible === "True" || fieldInfo.invisible === "1") {
            continue; // no need to fetch the sub view if the field is always invisible
        }
        if (!fieldInfo.field.useSubView) {
            continue; // the FieldComponent used to render the field doesn't need a sub view
        }

        fieldInfo.views = fieldInfo.views || {};
        let viewType = fieldInfo.viewMode || "list,kanban";
        if (viewType.includes(",")) {
            viewType = isSmall ? "kanban" : "list";
        }
        fieldInfo.viewMode = viewType;
        if (fieldInfo.views[viewType]) {
            continue; // the sub view is inline in the main form view
        }
        fieldInfosToLoad.push(fieldInfo);
    }

    // Fetch all sub-view archs in parallel: each iteration only mutates its own
    // fieldInfo, so there is no need to serialize the round-trips.
    await Promise.all(
        fieldInfosToLoad.map(async (fieldInfo) => {
            const field = fields[fieldInfo.name];
            const viewType = fieldInfo.viewMode;

            const fieldContext = {};
            // Matches both quote styles; any *_view_ref key spelling missed here is
            // silently dropped by the filter below instead of forwarded.
            const regex = /['"](\w+_view_ref)['"] *: *['"](.*?)['"]/g;
            let matches;
            while ((matches = regex.exec(fieldInfo.context)) !== null) {
                fieldContext[matches[1]] = matches[2];
            }
            const refinedContext = {};
            for (const key of Object.keys(context)) {
                if (!key.includes("_view_ref")) {
                    refinedContext[key] = context[key];
                }
            }

            const comodel = field.relation;
            const {
                fields: comodelFields,
                relatedModels,
                views,
            } = await viewService.loadViews({
                resModel: comodel,
                views: [[false, viewType]],
                context: makeContext([fieldContext, user.context, refinedContext]),
            });
            const { ArchParser } = viewRegistry.get(viewType);
            const xmlDoc = parseXML(views[viewType].arch);
            const archInfo = new ArchParser().parse(xmlDoc, relatedModels, comodel);
            fieldInfo.views[viewType] = {
                ...archInfo,
                limit: archInfo.limit || 40,
                fields: comodelFields,
            };
            fieldInfo.relatedFields = comodelFields;
        }),
    );
}

/**
 * Registers/unregisters a form-in-dialog with `form_dialog_stack` so the parent
 * FormController can suppress auto-save while a child form-in-dialog is open.
 */
export function useFormViewInDialog() {
    const formDialogStack = useService("form_dialog_stack");
    // Push synchronously in setup, NOT in onMounted: the dialog form spends
    // its whole willStart (loadViews / loadSubViews / initial record load)
    // unmounted, and during that window the parent FormController's tab-hide
    // auto-save (``beforeVisibilityChange``) would see an empty stack and
    // silently web_save the parent — staged x2many rows included.
    formDialogStack.push();
    // Pop in onWillDestroy, NOT onWillUnmount: a component destroyed before
    // it ever mounts (e.g. the dialog is closed while still loading) never
    // unmounts, which would leak the counter and permanently disable the
    // parent's auto-save. willDestroy runs in both cases.
    onWillDestroy(() => formDialogStack.pop());
}

const sharedComponents = registry.category("shared_components");
// Despite the name, entries are utility functions used to break import cycles
// between view layers, not Component classes — hence the typeof-function check.
sharedComponents.addValidation((entry) => typeof entry === "function");
sharedComponents.add("loadSubViews", loadSubViews);
sharedComponents.add("useFormViewInDialog", useFormViewInDialog);
