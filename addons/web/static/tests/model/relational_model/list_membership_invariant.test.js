// @ts-check

/**
 * ``count`` is the x2many pager total. It used to be a stored field that every
 * mutator kept in step with ``_currentIds`` by hand -- ``_addRecord``,
 * ``_commitSave``, ``_discard``, ``_replaceWith``, ``_load``,
 * ``removeMember`` and three sites in the command engine -- and a run of the
 * whole web model + view suites with an assertion wired into the getter found
 * exactly one production path where the two disagreed: ``_addRecord`` under an
 * ``orderBy`` reaches ``_load`` through ``sort()`` with the new id already in
 * ``nextCurrentIds`` but ``count`` not yet incremented. That window was
 * synchronous, so nothing could observe it -- it was one ``await`` away from a
 * wrong pager total, not a live bug.
 *
 * Deriving ``count`` removes the question: there is no second copy to drift.
 * These tests pin the derivation itself, so a future "optimisation" that
 * reintroduces a stored counter has to break them first.
 */

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

        // An id that is not a member must not shift the total.
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
