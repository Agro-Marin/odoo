// @ts-check

import { expect, test } from "@odoo/hoot";
import { TreeEditor } from "@web/components/tree_editor";
import { condition, connector } from "@web/core/tree/condition_tree";

const proto = /** @type {any} */ (TreeEditor.prototype);

/** @param {any} tree */
const paths = (tree) => tree.children.map((/** @type {any} */ c) => c.path);

test("_delete ignores a node that is not a child", () => {
    const parent = connector("&", [
        condition("a", "=", 1),
        condition("b", "=", 2),
        condition("c", "=", 3),
    ]);
    proto._delete.call({ _delete: proto._delete }, [parent], condition("zzz", "=", 9));
    expect(paths(parent)).toEqual(["a", "b", "c"]);
});

test("_delete removes the requested child and prunes empty parents", () => {
    const inner = connector("|", [condition("b", "=", 2)]);
    const outer = connector("&", [condition("a", "=", 1), inner]);
    proto._delete.call({ _delete: proto._delete }, [outer, inner], inner.children[0]);
    expect(paths(outer)).toEqual(["a"]);
});

test("_addNewCondition appends when the sibling is not a child", () => {
    const parent = connector("&", [condition("a", "=", 1), condition("b", "=", 2)]);
    proto._addNewCondition.call(
        {
            _addNewCondition: proto._addNewCondition,
            makeCondition: () => condition("new", "=", 0),
        },
        parent,
        condition("zzz", "=", 9),
    );
    expect(paths(parent)).toEqual(["a", "b", "new"]);
});

test("_addNewCondition inserts right after a real sibling", () => {
    const parent = connector("&", [condition("a", "=", 1), condition("b", "=", 2)]);
    proto._addNewCondition.call(
        {
            _addNewCondition: proto._addNewCondition,
            makeCondition: () => condition("new", "=", 0),
        },
        parent,
        parent.children[0],
    );
    expect(paths(parent)).toEqual(["a", "new", "b"]);
});

test("_addNewConnector appends when the sibling is not a child", () => {
    const parent = connector("&", [condition("a", "=", 1), condition("b", "=", 2)]);
    proto._addNewConnector.call(
        {
            _addNewConnector: proto._addNewConnector,
            makeCondition: () => condition("new", "=", 0),
        },
        parent,
        condition("zzz", "=", 9),
    );
    expect(parent.children.length).toBe(3);
    expect(/** @type {any} */ (parent.children.at(-1)).type).toBe("connector");
});

test("_updateComplexCondition refuses an unreadable expression", () => {
    const node = { type: "complex_condition", value: "a == 1" };
    proto._updateComplexCondition.call({}, node, "not valid ((");
    expect(node.value).toBe("a == 1");

    proto._updateComplexCondition.call({}, node, "b == 2");
    expect(node.value).toBe("b == 2");
});

test("updateComplexCondition puts the node's value back into the input", () => {
    const node = { type: "complex_condition", value: "a == 1" };
    const input = /** @type {any} */ ({ value: "not valid ((" });
    const self = {
        _updateComplexCondition: proto._updateComplexCondition,
        updateNode: (/** @type {any} */ _n, /** @type {any} */ fn) => fn(),
    };

    proto.updateComplexCondition.call(self, node, input.value, input);

    expect(node.value).toBe("a == 1", { message: "the node kept its value" });
    expect(input.value).toBe("a == 1", {
        message: "and the box must not keep what was refused",
    });
});

test("updateComplexCondition leaves an accepted expression in place", () => {
    const node = { type: "complex_condition", value: "a == 1" };
    const input = /** @type {any} */ ({ value: "b == 2" });
    const self = {
        _updateComplexCondition: proto._updateComplexCondition,
        updateNode: (/** @type {any} */ _n, /** @type {any} */ fn) => fn(),
    };

    proto.updateComplexCondition.call(self, node, input.value, input);

    expect(node.value).toBe("b == 2");
    expect(input.value).toBe("b == 2");
});
