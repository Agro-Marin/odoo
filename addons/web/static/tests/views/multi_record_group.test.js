// @ts-check

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";
import { useGroupManagement } from "@web/views/multi_record_group";

/**
 * @param {object} [overrides]
 */
function makeCtx(overrides = {}) {
    const list = {
        groupByField: { type: "many2one", name: "product_id" },
        /** @type {any[][]} */
        deletedGroups: [],
        /** @type {string[]} */
        createdGroups: [],
        async deleteGroups(/** @type {any[]} */ groups) {
            this.deletedGroups.push(groups);
        },
        createGroup(/** @type {string} */ value) {
            this.createdGroups.push(value);
        },
    };
    const archInfo = {
        activeActions: { createGroup: true },
        defaultGroupBy: ["product_id"],
    };
    return {
        list,
        archInfo,
        ops: useGroupManagement({
            getList: () => list,
            getArchInfo: () => archInfo,
            ...overrides,
        }),
    };
}

test("canCreateGroup requires the arch option, a many2one grouping and the default groupby", async () => {
    const { ops, list, archInfo } = makeCtx();
    expect(ops.canCreateGroup()).toBe(true);

    archInfo.activeActions.createGroup = false;
    expect(!!ops.canCreateGroup()).toBe(false);
    archInfo.activeActions.createGroup = true;

    list.groupByField = { type: "char", name: "product_id" };
    expect(ops.canCreateGroup()).toBe(false);

    list.groupByField = { type: "many2one", name: "other_field" };
    expect(ops.canCreateGroup()).toBe(false);

    list.groupByField = { type: "many2one", name: "product_id" };
    archInfo.defaultGroupBy = ["other_field"];
    expect(ops.canCreateGroup()).toBe(false);
});

test("canCreateGroup is denied in readonly mode", async () => {
    const { ops } = makeCtx({ isReadonly: () => true });
    expect(ops.canCreateGroup()).toBe(false);
});

test("group config menu props: extra items first, then the registry entries", async () => {
    registry.category("group_config_items").add("test_item", {
        label: "Test item",
        method: "deleteGroup",
        isVisible: () => true,
        class: "o_test_item",
    });
    const extraItem = ["extra_item", { label: "Extra", method: () => {} }];
    const dialogClose = [() => {}];
    const activeActions = { delete: true };
    const { ops, list } = makeCtx({
        getMenuActiveActions: () => activeActions,
        getDialogClose: () => dialogClose,
        getExtraConfigItems: () => [extraItem],
    });

    const group = { id: "g1" };
    const props = /** @type {any} */ (ops.getGroupConfigMenuProps(group));

    expect(props.activeActions).toBe(activeActions);
    expect(props.dialogClose).toBe(dialogClose);
    expect(props.group).toBe(group);
    expect(props.list).toBe(list);
    expect(props.configItems[0]).toBe(extraItem);
    expect(props.configItems.map((/** @type {any} */ [key]) => key)).toInclude(
        "test_item",
    );

    await props.deleteGroup();
    expect(list.deletedGroups).toEqual([[group]]);
});

test("the menu's delete flow can be routed through the caller's own implementation", async () => {
    /** @type {any[]} */
    const deleted = [];
    const { ops, list } = makeCtx({
        deleteGroup: (/** @type {any} */ group) => deleted.push(group),
    });

    const group = { id: "g1" };
    await ops.getGroupConfigMenuProps(group).deleteGroup();

    expect(deleted).toEqual([group]);
    expect(list.deletedGroups).toEqual([], {
        message: "the default delete flow must not also run",
    });
});

test("deleteGroup deletes through the list and then notifies", async () => {
    /** @type {string[]} */
    const steps = [];
    const { ops, list } = makeCtx({
        onGroupDeleted: () => steps.push("notified"),
    });
    list.deleteGroups = async (/** @type {any[]} */ groups) => {
        steps.push(`deleted:${groups.length}`);
    };

    await ops.deleteGroup({ id: "g1" });

    expect(steps).toEqual(["deleted:1", "notified"]);
});

test("toggleGroup forwards to the group and returns its promise", async () => {
    const { ops } = makeCtx();
    const toggled = Promise.resolve("toggled");
    const group = { toggle: () => toggled };

    expect(ops.toggleGroup(group)).toBe(toggled);
});

test("createGroup treats an empty value as a cancel", async () => {
    const { ops, list } = makeCtx();

    ops.createGroup("");
    expect(list.createdGroups).toEqual([]);

    ops.createGroup("New column");
    expect(list.createdGroups).toEqual(["New column"]);
});
