// @ts-check
/** @odoo-module native */

import { status, useComponent } from "@odoo/owl";
import { WarningDialog } from "@web/components/errors/error_dialogs";
import { useAction } from "@web/core/action_port";
import { getFieldCodec } from "@web/core/field_codec";
import { registry } from "@web/core/registry";
import { sharedComponents } from "@web/core/shared_components";
import { _t } from "@web/core/translation";
import { omit } from "@web/core/utils/collections/objects";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { useService } from "@web/core/utils/hooks";
import { STATIC_ACTIONS_GROUP_NUMBER } from "@web/search/action_menus/action_menus";
import { session } from "@web/session";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";

/**
 * @typedef ViewActiveActions
 * @property {"view"} type
 * @property {boolean} edit
 * @property {boolean} create
 * @property {boolean} delete
 * @property {boolean} duplicate
 */

/**
 * @param {string | null | undefined} type
 * @returns {string | false}
 */
function getViewClass(type) {
    if (!type) {
        return false;
    }
    const isValidType = registry.category("views").contains(type);
    return isValidType && `o_${type}_view`;
}

/**
 * @param {string?} viewType
 * @param {Element?} rootNode
 * @param {string[]} additionalClassList
 * @returns {string}
 */
export function computeViewClassName(viewType, rootNode, additionalClassList = []) {
    const subType = rootNode?.getAttribute("js_class");
    const classList = rootNode?.getAttribute("class")?.split(" ") || [];
    const uniqueClasses = new Set([
        getViewClass(viewType),
        getViewClass(subType),
        ...classList,
        ...additionalClassList,
    ]);
    return Array.from(uniqueClasses)
        .filter((c) => c)
        .join(" ");
}

/**
 * @type {WeakMap<object, object>}
 */
const formatOptionsByFieldInfo = new WeakMap();

/**
 * @param {any} record
 * @param {string} fieldName
 * @param {any} [fieldInfo]
 * @returns {string}
 */
export function getFormattedValue(record, fieldName, fieldInfo = null) {
    const field = record.fields[fieldName];
    const codec = getFieldCodec(field.type);
    let formatOptions;
    if (fieldInfo) {
        let extracted = formatOptionsByFieldInfo.get(fieldInfo);
        if (extracted === undefined) {
            extracted = codec.extractOptions(fieldInfo);
            formatOptionsByFieldInfo.set(fieldInfo, extracted);
        }
        formatOptions = { ...extracted };
    } else {
        formatOptions = {};
    }
    formatOptions.data = record.data;
    formatOptions.field = field;
    return record.data[fieldName] !== undefined
        ? codec.format(record.data[fieldName], formatOptions)
        : "";
}

/**
 * @param {Element} rootNode
 * @returns {ViewActiveActions}
 */
export function getActiveActions(rootNode) {
    /** @type {ViewActiveActions} */
    const activeActions = {
        type: "view",
        edit: exprToBoolean(rootNode.getAttribute("edit"), true),
        create: exprToBoolean(rootNode.getAttribute("create"), true),
        delete: exprToBoolean(rootNode.getAttribute("delete"), true),
        duplicate: false,
    };
    activeActions.duplicate =
        activeActions.create && exprToBoolean(rootNode.getAttribute("duplicate"), true);
    return activeActions;
}

/**
 * @param {BeforeUnloadEvent} ev
 * @param {object} opts
 * @param {import("@web/model/relational_model/record").RelationalRecord | null | undefined} opts.record
 * @param {boolean} opts.inDialog
 * @param {boolean} opts.useSendBeacon
 * @param {() => Promise<any>} opts.urgentSave
 */
export function handleBeforeUnload(
    ev,
    { record, inDialog, useSendBeacon, urgentSave },
) {
    if (!record) {
        return;
    }
    const canBeacon = Boolean(record.resId) && !inDialog && useSendBeacon;
    if (!canBeacon) {
        /** @type {import("@web/model/relational_model/urgent_save_coordinator").UrgentSaveCoordinator} */ (
            record.model.urgentSave
        ).run(() => Promise.resolve());
        if (record.dirty) {
            ev.preventDefault();
            ev.returnValue = "Unsaved changes";
        }
        return;
    }
    return urgentSave()
        .then((ok) => {
            if (!ok) {
                ev.preventDefault();
                ev.returnValue = "Unsaved changes";
            }
        })
        .catch(() => {
            ev.preventDefault();
            ev.returnValue = "Unsaved changes";
        });
}

/**
 * @param {any} value
 * @returns {boolean}
 */
export function isNull(value) {
    return value === null || value === undefined;
}

/**
 * @param {string | null | undefined} str
 * @return {string}
 */
export function toStringExpression(str) {
    return `\`${(str ?? "").replaceAll("`", "\\`").replaceAll("${", "\\${")}\``;
}

/**
 * @param {Object} env
 * @param {Object} display
 * @returns {{ lazy: boolean }}
 */
export function computeModelOptions(env, display) {
    return {
        lazy:
            !env.config.isReloadingController &&
            !env.inDialog &&
            !!display.controlPanel,
    };
}

/**
 * @param {Object} args
 * @param {any} args.archInfo
 * @param {any} args.props
 * @param {any} args.uiHooks
 * @param {Object} args.config
 * @param {{ lifecycle?: Object, ui?: Object }} [args.hooks={}]
 * @param {Object} [args.extras={}]
 * @returns {Object}
 */
export function buildMultiRecordModelParams({
    archInfo,
    props,
    uiHooks,
    config,
    hooks = {},
    extras = {},
}) {
    return {
        config: props.state?.modelState?.config || config,
        state: props.state?.modelState,
        countLimit: archInfo.countLimit,
        defaultOrderBy: archInfo.defaultOrder,
        activeIdsLimit: session.active_ids_limit,
        hooks: {
            lifecycle: hooks.lifecycle,
            ui: { ...uiHooks, ...hooks.ui },
        },
        ...extras,
    };
}

/**
 * @param {Record<string, any>} genericProps
 * @param {Record<string, any>} view
 * @returns {Record<string, any>}
 */
export function defaultViewProps(genericProps, view) {
    const { arch, relatedModels, resModel } = genericProps;
    const archInfo = new view.ArchParser().parse(arch, relatedModels, resModel);
    return {
        ...genericProps,
        Model: view.Model,
        Renderer: view.Renderer,
        buttonTemplate: view.buttonTemplate,
        ...(view.Compiler ? { Compiler: view.Compiler } : {}),
        archInfo,
    };
}

/**
 * @param {Record<string, any>} genericProps
 * @param {Record<string, any>} view
 * @returns {Record<string, any>}
 */
export function multiRecordViewProps(genericProps, view) {
    const props = defaultViewProps(genericProps, view);
    props.readonly = genericProps.readonly || !props.archInfo.activeActions?.edit;
    return props;
}

/**
 * @param {Record<string, any>} genericProps
 * @param {Record<string, any>} view
 * @param {{
 * fromState: (state: any) => any,
 * fromArch: (archInfo: any, genericProps: Record<string, any>) => any,
 * }} buildModelParams
 * @returns {Record<string, any>}
 */
export function reportViewProps(genericProps, view, buildModelParams) {
    const { arch, relatedModels, resModel, state } = genericProps;
    const modelParams = state
        ? buildModelParams.fromState(state)
        : buildModelParams.fromArch(
              new view.ArchParser().parse(arch, relatedModels, resModel),
              genericProps,
          );
    return {
        ...genericProps,
        Model: view.Model,
        Renderer: view.Renderer,
        buttonTemplate: view.buttonTemplate,
        modelParams,
    };
}

/**
 * @returns {{ action: any, dialog: any, notification: any, orm: any, uiHooks: any }}
 */
export function useControllerServices() {
    const component = useComponent();
    const action = useAction();
    const dialog = useService("dialog");
    const notification = useService("notification");
    const orm = useService("orm");
    const uiHooks = makeModelUIHooks({
        action,
        dialog,
        notification,
        isAlive: () => status(component) !== "destroyed",
    });
    return { action, dialog, notification, orm, uiHooks };
}

/**
 * @param {Object} fields
 * @param {Object} [options]
 * @param {Object} [options.presentIn=fields]
 * @returns {boolean}
 */
export function computeArchiveEnabled(fields, { presentIn = fields } = {}) {
    for (const fieldName of ["active", "x_active"]) {
        if (fieldName in presentIn) {
            return Boolean(fields[fieldName]) && !fields[fieldName].readonly;
        }
    }
    return false;
}

/**
 * @type {Record<string, { sequence: number, icon: string, description: any, class?: string }>}
 */
export const STATIC_ACTION_MENU_DESCRIPTORS = {
    addPropertyFieldValue: {
        sequence: 10,
        icon: "fa-solid fa-cogs",
        description: _t("Edit Properties"),
    },
    export: {
        sequence: 10,
        icon: "fa-solid fa-upload",
        description: _t("Export"),
    },
    duplicate: {
        sequence: 30,
        icon: "fa-regular fa-clone",
        description: _t("Duplicate"),
    },
    archive: {
        sequence: 40,
        icon: "oi oi-archive",
        description: _t("Archive"),
    },
    unarchive: {
        sequence: 45,
        icon: "oi oi-unarchive",
        description: _t("Unarchive"),
    },
    delete: {
        sequence: 50,
        icon: "fa-regular fa-trash-can",
        description: _t("Delete"),
        class: "text-danger",
    },
};

/**
 * @param {Record<string, Object>} overlays
 * @returns {Record<string, Object>}
 */
export function buildStaticActionMenuItems(overlays) {
    const items = {};
    for (const [key, overlay] of Object.entries(overlays)) {
        const descriptor = STATIC_ACTION_MENU_DESCRIPTORS[key];
        if (!descriptor) {
            throw new Error(
                `No static action menu descriptor for "${key}"; add one to STATIC_ACTION_MENU_DESCRIPTORS`,
            );
        }
        items[key] = { ...descriptor, ...overlay };
    }
    return items;
}

/**
 * @param {() => any} archiveFn
 * @param {{ multi?: boolean }} [options]
 * @returns {Object}
 */
export function archiveConfirmationProps(archiveFn, { multi = false } = {}) {
    return {
        body: multi
            ? _t("Are you sure that you want to archive all the selected records?")
            : _t("Are you sure that you want to archive this record?"),
        cancel: () => {},
        confirm: () => {
            archiveFn();
        },
        confirmLabel: _t("Archive"),
    };
}

/**
 * @param {{ action: string, type: string }} openAction
 * @param {any} record
 * @returns {Object}
 */
export function buildOpenActionParams(openAction, record) {
    return {
        name: openAction.action,
        type: openAction.type,
        resModel: record.resModel,
        resId: record.resId,
        resIds: record.resIds,
        context: record.context,
        onClose: async () => {
            await record.model.root.load();
        },
    };
}

/**
 * @param {Object} staticItems
 * @param {Object} [actionMenus]
 * @returns {{ action: Object[], print: Object[] }}
 */
export function buildActionMenuItems(staticItems, actionMenus) {
    const staticActionItems = Object.entries(staticItems)
        .filter(([, item]) => item.isAvailable === undefined || item.isAvailable())
        .sort(([, item1], [, item2]) => (item1.sequence || 0) - (item2.sequence || 0))
        .map(([key, item]) =>
            Object.assign(
                { key, groupNumber: STATIC_ACTIONS_GROUP_NUMBER },
                omit(item, "isAvailable", "sequence"),
            ),
        );

    return {
        action: [...staticActionItems, ...(actionMenus?.action || [])],
        print: actionMenus?.print || [],
    };
}

/**
 * @param {Object} services
 * @param {Object} services.action
 * @param {Object} services.dialog
 * @param {Object} services.notification
 * @param {() => boolean} [services.isAlive]
 * @returns {Object}
 */
export function makeModelUIHooks({
    action,
    dialog,
    notification,
    isAlive = () => true,
}) {
    return {
        onDisplayOnchangeWarning(warning) {
            const { type, title, message, className, sticky } = warning;
            if (type === "dialog") {
                dialog.add(WarningDialog, { title, message });
            } else {
                notification.add(message, {
                    className,
                    sticky,
                    title,
                    type: "warning",
                });
            }
        },
        onDisplayInvalidFields() {
            return notification.add(_t("Missing required fields"), {
                type: "danger",
            });
        },
        onDisplayUrgentSave(message) {
            return notification.add(message, { sticky: true });
        },
        onDisplayPropertyWarning(message) {
            notification.add(message, { type: "warning" });
        },
        onDisplayArchiveAction(actionResult, reload) {
            const reloadIfAlive = () => (isAlive() ? reload() : undefined);
            if (actionResult && Object.keys(actionResult).length) {
                return action.doAction(actionResult, { onClose: reloadIfAlive });
            } else {
                return reloadIfAlive();
            }
        },
        onConfirmArchive(archiveFn, dialogProps = {}) {
            dialog.add(ConfirmationDialog, {
                ...archiveConfirmationProps(archiveFn, { multi: true }),
                ...dialogProps,
            });
        },
        onConfirmDuplicate(resIds, copyFn) {
            if (resIds.length > 1) {
                dialog.add(ConfirmationDialog, {
                    body: _t(
                        "Are you sure that you want to duplicate all the selected records?",
                    ),
                    confirm: async () => copyFn(resIds),
                    cancel: () => {},
                    confirmLabel: _t("Confirm"),
                });
            } else {
                return copyFn(resIds);
            }
        },
        onDisplayLimitNotification(msg) {
            notification.add(msg);
        },
    };
}

sharedComponents.add("computeViewClassName", computeViewClassName);
