// @ts-check

import { luxon } from "@web/core/l10n/luxon";

/**
 * @param {string} label
 * @param {string[]} searchTerms
 */
function app(label, searchTerms = []) {
    return {
        menu: { id: label, label },
        label,
        phrases: [label, ...searchTerms],
        isApp: true,
        appLabel: label,
        inCurrentApp: false,
    };
}

/**
 * @param {string} label
 * @param {string} appLabel
 * @param {string} [parent]
 */
function item(label, appLabel, parent = appLabel) {
    return {
        menu: { id: `${appLabel}/${label}`, label },
        label,
        phrases: [label, `${parent} ${label}`, `${label} ${appLabel}`],
        isApp: false,
        appLabel,
        inCurrentApp: false,
    };
}

export const MENUS = [
    app("Ventas", ["Sales", "sale"]),
    app("Contabilidad", ["Accounting", "Invoicing"]),
    app("Inventario", ["Inventory", "stock"]),
    item("Facturas de cliente", "Contabilidad", "Clientes"),
    item("Facturas de proveedor", "Contabilidad", "Proveedores"),
    item("Pedidos", "Ventas"),
    item("Configuración", "Ventas"),
    item("Configuración", "Inventario"),
    item("Transferencias", "Inventario"),
];

export const INVOICE_LIST = {
    viewType: "list",
    resModel: "account.move",
    viewTypes: ["list", "kanban", "form", "pivot"],
    filters: [
        { name: "unpaid", label: "Sin pagar" },
        { name: "my_invoices", label: "Mis facturas" },
        { name: "draft", label: "Borrador" },
    ],
    dateFilters: [
        {
            name: "invoice_date",
            label: "Fecha de factura",
            fieldName: "invoice_date",
            generatorIds: ["month", "month-1", "month-2", "year", "year-1"],
        },
    ],
    groupBys: [
        { fieldName: "invoice_user_id", label: "Vendedor", isDate: false },
        { fieldName: "partner_id", label: "Cliente", isDate: false },
        { fieldName: "invoice_date", label: "Fecha de factura", isDate: true },
    ],
    searchFields: [
        { fieldName: "name", label: "Número", fieldType: "char" },
        { fieldName: "partner_id", label: "Cliente", fieldType: "many2one" },
    ],
    recordCount: 5,
    form: null,
};

export const ORDER_FORM = {
    viewType: "form",
    resModel: "sale.order",
    viewTypes: ["list", "form"],
    filters: [],
    dateFilters: [],
    groupBys: [],
    searchFields: [],
    recordCount: 1,
    form: {
        fields: [
            {
                name: "partner_id",
                label: "Cliente",
                type: "many2one",
                relation: "res.partner",
            },
            { name: "note", label: "Notas", type: "text" },
            { name: "quantity", label: "Cantidad", type: "float" },
            {
                name: "priority",
                label: "Prioridad",
                type: "selection",
                selection: [
                    ["0", "Normal"],
                    ["1", "Urgente"],
                ],
            },
            { name: "is_gift", label: "Es regalo", type: "boolean" },
            { name: "commitment_date", label: "Fecha de entrega", type: "date" },
        ],
        buttons: [
            {
                label: "Confirmar",
                clickParams: { name: "action_confirm", type: "object" },
            },
            {
                label: "Cancelar",
                clickParams: { name: "action_cancel", type: "object" },
            },
        ],
        displayName: "S00042",
    },
};

export const COMMANDS = [
    { name: "Asignarme", category: "smart_action", action: () => {} },
    { name: "Mostrar vista de lista", category: "view_switcher", action: () => {} },
];

/**
 * @param {any} view
 * @returns {import("@voice/interpreter/vocabulary").Vocabulary}
 */
export function vocabulary(view = null) {
    return {
        menus: MENUS,
        view,
        commands: COMMANDS,
        today: luxon.DateTime.fromISO("2019-07-31T10:00:00"),
    };
}
