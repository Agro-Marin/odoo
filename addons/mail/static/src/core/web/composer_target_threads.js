/** @odoo-module native */

/**
 * @param {import("models").Store} store
 * @param {import("@web/model/relational_model/record").RelationalRecord} record
 * @returns {import("models").Thread[]}
 */
export function getComposerTargetThreads(store, record) {
    let resIds;
    if (record.resModel === "mail.scheduled.message") {
        resIds = [record.data.res_id?.resId];
    } else if (record.data.res_ids) {
        resIds = JSON.parse(record.data.res_ids);
    } else {
        resIds = record.context.active_ids ?? [];
    }
    return resIds
        .filter((resId) => resId)
        .map((resId) => store.Thread.insert({ model: record.data.model, id: resId }));
}
