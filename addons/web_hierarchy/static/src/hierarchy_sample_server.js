/** @odoo-module native */
import { registry } from "@web/core/registry";

/**
 * How many cards the sample hierarchy draws: one root and its direct reports.
 * Enough to show the shape of the view without filling the screen, and one
 * short of `SAMPLE_PEOPLE`, whose five names repeat past that -- two cards
 * bearing the same name read as a bug in the view rather than as sample data.
 */
const SAMPLE_CHILD_COUNT = 4;

/**
 * Stand in for `Base.hierarchy_read` while the view shows sample data.
 *
 * `SampleServer` generates a many2one by drawing a random id from the same
 * sample set, so the parent field of a self-referencing model describes a graph
 * with cycles rather than a hierarchy -- a payload this view would lay out flat,
 * or refuse to nest at all. The sample answer therefore imposes its own shape:
 * the first record is the root and the next few are its children. Every other
 * field keeps the value the sample server generated.
 *
 * @this {import("@web/model/sample_server").SampleServer}
 * @param {Object} params
 * @returns {Object[]}
 */
function mockHierarchyRead(params) {
    const [, specification, parentFieldName] = params.args;
    const { records } = this._mockWebSearchReadUnity({ ...params, specification });
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
