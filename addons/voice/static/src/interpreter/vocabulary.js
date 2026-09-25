// @ts-check
/** @odoo-module native */

import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { getPeriodOptions } from "@web/search/utils/dates";
import { isGroupableField } from "@web/search/utils/misc";
import { flattenMenuTree } from "@web/webclient/menus/menu_utils";

/**
 * @typedef {{ menu: any, label: string, phrases: string[], isApp: boolean, appLabel: string, inCurrentApp: boolean }} MenuTerm
 * @typedef {{ name: string, label: string }} FilterTerm
 * @typedef {{ name: string, label: string, fieldName: string, generatorIds: string[] }} DateFilterTerm
 * @typedef {{ fieldName: string, label: string, isDate: boolean }} GroupByTerm
 * @typedef {{ fieldName: string, label: string, fieldType: string }} SearchFieldTerm
 * @typedef {{ name: string, label: string, type: string, relation?: string, selection?: [any, string][] }} FormFieldTerm
 * @typedef {{ label: string, clickParams: Record<string, any> }} ButtonTerm
 * @typedef {{
 *   viewType: string,
 *   resModel: string,
 *   viewTypes: string[],
 *   filters: FilterTerm[],
 *   dateFilters: DateFilterTerm[],
 *   groupBys: GroupByTerm[],
 *   searchFields: SearchFieldTerm[],
 *   recordCount: number,
 *   form: { fields: FormFieldTerm[], buttons: ButtonTerm[], displayName: string } | null,
 * }} ViewTerms
 * @typedef {{ name: string, category?: string, action: Function }} CommandTerm
 * @typedef {{ label: string, risk: number }} TargetTerm
 * @typedef {{
 *   menus: MenuTerm[],
 *   view: ViewTerms | null,
 *   commands: CommandTerm[],
 *   today: any,
 *   targets?: TargetTerm[],
 *   numbersShown?: boolean,
 *   canDictate?: boolean,
 * }} Vocabulary
 */

/**
 * @param {any} menuService
 * @returns {MenuTerm[]}
 */
function compileMenus(menuService) {
    const { apps, menuItems } = flattenMenuTree(menuService.getMenuAsTree("root"));
    const currentAppId = menuService.getCurrentApp()?.id;
    const appLabels = new Map(apps.map((app) => [app.appID ?? app.id, app.label]));
    return [
        ...apps.map((app) => ({
            menu: app,
            label: app.label,
            phrases: [app.label, ...(app.searchTerms || [])],
            isApp: true,
            appLabel: app.label,
            inCurrentApp: app.id === currentAppId,
        })),
        ...menuItems.map((item) => {
            const appLabel = appLabels.get(item.appID) || "";
            const parent = (item.parents || "").split(" / ").pop() || "";
            return {
                menu: item,
                label: item.label,
                phrases: [
                    item.label,
                    `${parent} ${item.label}`,
                    `${item.label} ${appLabel}`,
                ],
                isApp: false,
                appLabel,
                inCurrentApp: item.appID === currentAppId,
            };
        }),
    ];
}

/**
 * @param {any} searchModel
 * @param {any} item
 * @returns {string[]}
 */
function knownGeneratorIds(searchModel, item) {
    if (!item.optionsParams) {
        return [];
    }
    return getPeriodOptions(searchModel.referenceMoment, item.optionsParams).map(
        (/** @type {any} */ option) => option.id,
    );
}

/**
 * @param {any} searchModel
 * @returns {Pick<ViewTerms, "filters" | "dateFilters" | "groupBys" | "searchFields">}
 */
function compileSearch(searchModel) {
    const items = searchModel.getSearchItems();
    /** @type {GroupByTerm[]} */
    const groupBys = [];
    const groupedFields = new Set();
    for (const item of items) {
        if (item.type === "groupBy" || item.type === "dateGroupBy") {
            groupBys.push({
                fieldName: item.fieldName,
                label: item.description,
                isDate: item.type === "dateGroupBy",
            });
            groupedFields.add(item.fieldName);
        }
    }
    for (const [fieldName, field] of Object.entries(
        searchModel.searchViewFields || {},
    )) {
        if (!groupedFields.has(fieldName) && isGroupableField(fieldName, field)) {
            groupBys.push({
                fieldName,
                label: field.string || fieldName,
                isDate: ["date", "datetime"].includes(field.type),
            });
        }
    }
    return {
        filters: items
            .filter((/** @type {any} */ item) => item.type === "filter" && item.name)
            .map((/** @type {any} */ item) => ({
                name: item.name,
                label: item.description,
            })),
        dateFilters: items
            .filter(
                (/** @type {any} */ item) => item.type === "dateFilter" && item.name,
            )
            .map((/** @type {any} */ item) => ({
                name: item.name,
                label: item.description,
                fieldName: item.fieldName,
                generatorIds: knownGeneratorIds(searchModel, item),
            })),
        groupBys,
        searchFields: items
            .filter((/** @type {any} */ item) => item.type === "field")
            .map((/** @type {any} */ item) => ({
                fieldName: item.fieldName,
                label: item.description,
                fieldType: item.fieldType,
            })),
    };
}

/**
 * @param {Element} node
 * @param {any} record
 * @returns {boolean}
 */
function isVisible(node, record) {
    const invisible = node.getAttribute("invisible");
    if (!invisible) {
        return true;
    }
    return !evaluateBooleanExpr(invisible, record.evalContextWithVirtualIds);
}

const BUTTON_ATTRIBUTES = [
    "name",
    "type",
    "context",
    "confirm",
    "confirm-title",
    "confirm-label",
    "cancel-label",
    "special",
    "close",
    "args",
];

/**
 * Buttons are read from the arch, not the page: a statusbar or button box
 * folds what does not fit into a dropdown, where the page has no button.
 *
 * @param {any} archInfo
 * @param {any} record
 * @returns {ButtonTerm[]}
 */
function compileButtons(archInfo, record) {
    /** @type {ButtonTerm[]} */
    const buttons = [];
    const selector = "header button[name], div[name='button_box'] button[name]";
    for (const node of archInfo.xmlDoc.querySelectorAll(selector)) {
        const type = node.getAttribute("type");
        if (!["object", "action"].includes(type) || !isVisible(node, record)) {
            continue;
        }
        const label = (node.getAttribute("string") || node.textContent || "").trim();
        if (!label) {
            continue;
        }
        /** @type {Record<string, any>} */
        const clickParams = {};
        for (const attribute of BUTTON_ATTRIBUTES) {
            if (node.hasAttribute(attribute)) {
                clickParams[attribute] = node.getAttribute(attribute);
            }
        }
        buttons.push({ label, clickParams });
    }
    return buttons;
}

/**
 * @param {any} controller
 * @returns {ViewTerms["form"]}
 */
function compileForm(controller) {
    const record = controller?.model?.root;
    const archInfo = controller?.archInfo;
    if (!record || !archInfo?.fieldNodes) {
        return null;
    }
    /** @type {FormFieldTerm[]} */
    const fields = [];
    const seen = new Set();
    for (const node of Object.values(archInfo.fieldNodes)) {
        const field = record.fields[node.name];
        if (!field || seen.has(node.name) || record.isFieldReadonly(node.name)) {
            continue;
        }
        if (
            node.invisible &&
            evaluateBooleanExpr(node.invisible, record.evalContextWithVirtualIds)
        ) {
            continue;
        }
        seen.add(node.name);
        fields.push({
            name: node.name,
            label: node.string || field.string || node.name,
            type: field.type,
            relation: field.relation,
            selection: field.selection,
        });
    }
    return {
        fields,
        buttons: archInfo.xmlDoc ? compileButtons(archInfo, record) : [],
        displayName: record.data.display_name || "",
    };
}

/**
 * @param {import("@web/views/active_view").ActiveView | null} activeView
 * @returns {ViewTerms | null}
 */
function compileView(activeView) {
    if (!activeView) {
        return null;
    }
    const { config, searchModel, controller } = activeView;
    const viewType = config.viewType || "";
    return {
        viewType,
        resModel: searchModel.resModel,
        viewTypes: (config.viewSwitcherEntries || []).map(
            (/** @type {any} */ v) => v.type,
        ),
        ...compileSearch(searchModel),
        recordCount: controller?.model?.root?.records?.length ?? 0,
        form: viewType === "form" ? compileForm(controller) : null,
    };
}

/**
 * What the user can name right now: every menu, the view in front of them
 * unless the home menu covers it, and the commands in scope.
 *
 * @param {{ menu: any, activeView: any, homeMenu?: any, commands?: CommandTerm[], today: any }} sources
 * @returns {Vocabulary}
 */
export function compileVocabulary({
    menu,
    activeView,
    homeMenu,
    commands = [],
    today,
}) {
    return {
        menus: compileMenus(menu),
        view: homeMenu?.hasHomeMenu ? null : compileView(activeView),
        commands,
        today,
    };
}
