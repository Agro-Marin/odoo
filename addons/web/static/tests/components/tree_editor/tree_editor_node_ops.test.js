// @ts-check

import { expect, test } from "@odoo/hoot";
import { TreeEditor } from "@web/components/tree_editor/tree_editor";
import { condition, connector } from "@web/core/tree/condition_tree";

/**
 * The node-mutating primitives locate a node with `indexOf` and splice around
 * the result. A node that is not (or no longer) a child of `parent` yields -1,
 * which `splice` reads as "one from the end" -- silently hitting the wrong
 * position. These pin the -1 handling directly, without a mount.
 */
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
