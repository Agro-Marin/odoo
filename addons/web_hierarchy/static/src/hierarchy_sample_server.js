// @ts-check
/** @odoo-module native */
import { registry } from "@web/core/registry";

const SAMPLE_CHILD_COUNT = 4;

/**
 * @this {import("@web/model/sample_server").SampleServer}
 * @param {Object} params
 * @returns {Object[]}
 */
function mockHierarchyRead(params) {
    const [, specification, parentFieldName] = params.args;
    const { records } = this.mockRpc({
        model: params.model,
        method: "web_search_read",
        specification,
    });
    const sample = records.slice(0, SAMPLE_CHILD_COUNT + 1);
    if (!sample.length) {
        return [];
    }
    const [root, ...children] = sample;
    root[parentFieldName] = false;
    const parentValue = {
        id: root.id,
        display_name: String(root.display_name ?? root.name ?? ""),
    };
    for (const child of children) {
        child[parentFieldName] = parentValue;
    }
    return sample;
}

registry.category("sample_server").add("hierarchy_read", mockHierarchyRead);
