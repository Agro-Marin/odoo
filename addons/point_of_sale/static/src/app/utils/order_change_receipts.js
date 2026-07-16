/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";

// CONSOLE_COLOR lives on pos_store; importing it here mirrors the existing
// call-time circular imports (pos_config, data_service, indexed_db, …) — the
// binding is only read inside function bodies, so the cycle resolves fine.
import { CONSOLE_COLOR } from "../services/pos_store.js";
import { logPosMessage } from "./pretty_console_log.js";

const { DateTime } = luxon;

// Order-change → preparation/receipt data generation extracted from PosStore.
// Pure functions of the store; PosStore keeps thin delegating methods so the
// print orchestration (printChanges/sendOrderInPreparation, which modules patch)
// and its callers are unaffected. Cross-calls go through `pos.<method>()` so a
// module's patch still applies.

export function getStrNotes(note) {
    if (!note) {
        return "";
    }
    if (Array.isArray(note)) {
        return note.map((n) => (typeof n === "string" ? n : n.text)).join(", ");
    }
    if (typeof note === "string") {
        try {
            const parsed = JSON.parse(note);
            if (Array.isArray(parsed)) {
                return parsed
                    .map((n) => (typeof n === "string" ? n : n.text))
                    .join(", ");
            }
            return note;
        } catch (error) {
            logPosMessage(
                "Store",
                "getStrNotes",
                "Error while parsing note, not valid JSON",
                CONSOLE_COLOR,
                [error],
            );
            return note;
        }
    }
    return "";
}

export function getOrderData(pos, order, reprint) {
    return {
        reprint: reprint,
        pos_reference: order.getName(),
        config_name: order.config_id?.name || order.config.name,
        time: DateTime.now().toFormat("HH:mm"),
        tracking_number: order.tracking_number,
        preset_time: order.presetDateTime,
        preset_name: order.preset_id?.name || "",
        employee_name: order.employee_id?.name || order.user_id?.name,
        internal_note: pos.getStrNotes(order.internal_note),
        general_customer_note: order.general_customer_note,
        changes: {
            title: "",
            data: [],
        },
    };
}

export function generateOrderChange(
    pos,
    order,
    orderChange,
    categories,
    reprint = false,
) {
    const isPartOfCombo = (line) =>
        line.isCombo ||
        line.combo_parent_uuid ||
        pos.models["product.product"].get(line.product_id).type === "combo";
    const comboChanges = orderChange.new.filter(isPartOfCombo);
    const normalChanges = orderChange.new.filter((line) => !isPartOfCombo(line));
    normalChanges.sort((a, b) => {
        const sequenceA = a.pos_categ_sequence;
        const sequenceB = b.pos_categ_sequence;
        if (sequenceA === 0 && sequenceB === 0) {
            return a.pos_categ_id - b.pos_categ_id;
        }

        return sequenceA - sequenceB;
    });
    orderChange.new = [...comboChanges, ...normalChanges];

    const orderData = pos.getOrderData(order, reprint);

    const changes = pos.filterChangeByCategories(categories, orderChange);
    // Annotate COPIES: printChanges calls this once per printer, and mutating
    // the shared change items handed the second printer already-stringified
    // notes (re-parsed through the JSON failure path, logged as an error on
    // every multi-printer note print).
    const stringifyNotes = (items) =>
        items.map((changeItem) => ({
            ...changeItem,
            note: pos.getStrNotes(changeItem.note || "[]"),
        }));
    return {
        orderData,
        changes: {
            ...changes,
            new: stringifyNotes(changes.new),
            cancelled: stringifyNotes(changes.cancelled),
            noteUpdate: stringifyNotes(changes.noteUpdate),
        },
    };
}

export async function generateReceiptsDataToPrint(
    pos,
    orderData,
    changes,
    orderChange,
) {
    const receiptsData = [];
    if (changes.new.length) {
        const orderDataNew = { ...orderData };
        orderDataNew.changes = {
            title: _t("NEW"),
            data: changes.new,
        };
        receiptsData.push(await pos.prepareReceiptGroupedData(orderDataNew));
    }

    if (changes.cancelled.length) {
        const orderDataCancelled = { ...orderData };
        orderDataCancelled.changes = {
            title: _t("CANCELLED"),
            data: changes.cancelled,
        };
        receiptsData.push(await pos.prepareReceiptGroupedData(orderDataCancelled));
    }

    if (changes.noteUpdate.length) {
        const orderDataNoteUpdate = { ...orderData };
        const { noteUpdateTitle, printNoteUpdateData = true } = orderChange;
        orderDataNoteUpdate.changes = {
            title: noteUpdateTitle || _t("NOTE UPDATE"),
            data: printNoteUpdateData ? changes.noteUpdate : [],
        };
        receiptsData.push(await pos.prepareReceiptGroupedData(orderDataNoteUpdate));
    }

    if (orderChange.internal_note || orderChange.general_customer_note) {
        const orderDataNote = { ...orderData };
        orderDataNote.changes = { title: "", data: [] };
        receiptsData.push(await pos.prepareReceiptGroupedData(orderDataNote));
    }
    return receiptsData;
}

export async function prepareReceiptGroupedData(data) {
    const dataChanges = data.changes?.data;
    if (dataChanges && dataChanges.some((c) => c.group)) {
        const groupedData = dataChanges.reduce((acc, c) => {
            const { name = "", index = -1 } = c.group || {};
            if (!acc[name]) {
                acc[name] = { name, index, data: [] };
            }
            acc[name].data.push(c);
            return acc;
        }, {});
        data.changes.groupedData = Object.values(groupedData).sort(
            (a, b) => a.index - b.index,
        );
    }
    return data;
}

export function filterChangeByCategories(pos, categories, currentOrderChange) {
    const matchesCategories = (change) => {
        const product = pos.models["product.product"].get(change["product_id"]);
        const categoryIds = product.parentPosCategIds;
        for (const categoryId of categoryIds) {
            if (categories.includes(categoryId)) {
                return true;
            }
        }
        return false;
    };

    const filterChanges = (changes) => {
        // Combo line uuids to have at least one child line in the given categories
        const validComboUuids = new Set(
            changes
                .filter(
                    (change) => change.combo_parent_uuid && matchesCategories(change),
                )
                .map((change) => change.combo_parent_uuid),
        );
        return changes.filter(
            (change) =>
                (change.isCombo && validComboUuids.has(change.uuid)) ||
                (!change.isCombo && matchesCategories(change)),
        );
    };

    return {
        new: filterChanges(currentOrderChange["new"]),
        cancelled: filterChanges(currentOrderChange["cancelled"]),
        noteUpdate: filterChanges(currentOrderChange["noteUpdate"]),
    };
}
