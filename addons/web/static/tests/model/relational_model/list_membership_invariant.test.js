// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { ListMembership } from "@web/model/relational_model/list_membership";

describe("ListMembership.count is derived, not stored", () => {
    test("count tracks the id list through every kind of mutation", () => {
        const membership = new ListMembership([1, 2, 3]);
        expect(membership.count).toBe(3);

        membership.ids.push(4);
        expect(membership.count).toBe(4);

        membership.ids.splice(0, 1);
        expect(membership.count).toBe(3);

        membership.ids = [9];
        expect(membership.count).toBe(1);

        membership.ids = [];
        expect(membership.count).toBe(0);
    });

    test("removeMember keeps count in step without touching it", () => {
        const membership = new ListMembership([1, 2, 3]);
        const record = /** @type {any} */ ({ resId: 2 });
        membership.records = [record];

        expect(membership.removeMember(2, record)).toBe(true);
        expect(membership.ids).toEqual([1, 3]);
        expect(membership.count).toBe(2);
        expect(membership.records).toEqual([]);

        expect(membership.removeMember(99)).toBe(false);
        expect(membership.count).toBe(2);
    });

    test("duplicate membership counts twice, as the pager total must", () => {
        const membership = new ListMembership([1, 1, 2]);
        expect(membership.count).toBe(3);

        membership.removeMember(1);
        expect(membership.ids).toEqual([1, 2]);
        expect(membership.count).toBe(2);
    });

    test("count cannot be assigned", () => {
        const membership = new ListMembership([1, 2]);
        expect(() => {
            /** @type {any} */ (membership).count = 99;
        }).toThrow();
        expect(membership.count).toBe(2);
    });
});
