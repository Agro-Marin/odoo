// @ts-check

/**
 * AUDIT CHALLENGE — DynamicList._deleteRecords / _toggleArchive read `this.count`
 * as a RECORD count, but on a DynamicGroupList `count` is the NUMBER OF GROUPS
 * (see dynamic_group_list_create_group.test.js, which pins that meaning).
 *
 * Consequence: on a grouped list, the "only the first N were deleted" truncation
 * warning is gated behind `resIds.length < this.count` — i.e. 20000 < 12 — which
 * is false, so the warning is suppressed and the user is told nothing while the
 * remaining records survive.
 *
 * These tests assert the CORRECT behaviour (warning shown) and therefore fail
 * against the current implementation.
 */

import { describe, expect, test } from "@odoo/hoot";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";

const ACTIVE_IDS_LIMIT = 20000;
const TOTAL_RECORDS = 25000;
const NB_GROUPS = 12;

/**
 * @param {{ grouped: boolean }} options
 */
function makeList({ grouped }) {
    const proto = grouped ? DynamicGroupList.prototype : DynamicRecordList.prototype;
    const list = Object.create(proto);
    /** @type {string[]} */
    const notifications = [];

    list.isDomainSelected = true;
    list._config = {
        domain: [],
        orderBy: [],
        groupBy: grouped ? ["partner_id"] : [],
        context: {},
        resModel: "res.model",
        fields: {},
        activeFields: {},
        fieldsToAggregate: [],
        groups: {},
    };

    if (grouped) {
        list.count = NB_GROUPS;
        list.groups = [];
        list._nbRecordsMatchingDomain = TOTAL_RECORDS;
    } else {
        list.count = TOTAL_RECORDS;
        list._records = [];
    }

    list.model = {
        activeIdsLimit: ACTIVE_IDS_LIMIT,
        orm: {
            search: async () =>
                Array.from({ length: ACTIVE_IDS_LIMIT }, (_, i) => i + 1),
            unlink: async () => true,
            call: async () => ({}),
        },
        load: async () => {},
        hooks: {
            ui: {
                onDisplayLimitNotification: (msg) => notifications.push(msg),
                onDisplayArchiveAction: async () => {},
            },
        },
    };
    return { list, notifications };
}

describe("grouped bulk operations respect the active-ids limit warning", () => {
    test("ungrouped list warns when delete is truncated (control)", async () => {
        const { list, notifications } = makeList({ grouped: false });
        await list._deleteRecords([]);
        expect(notifications.length).toBe(1);
        expect(notifications[0]).toInclude("20000");
    });

    test("grouped list warns when delete is truncated", async () => {
        const { list, notifications } = makeList({ grouped: true });
        await list._deleteRecords([]);
        expect(notifications.length).toBe(1);
        expect(notifications[0]).toInclude("20000");
    });

    test("grouped list reports the record total, not the group count", async () => {
        const { list, notifications } = makeList({ grouped: true });
        await list._toggleArchive(true);
        expect(notifications.length).toBe(1);
        expect(notifications[0]).toInclude("25000");
    });
});
