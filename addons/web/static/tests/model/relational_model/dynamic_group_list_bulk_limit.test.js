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

const ACTIVE_IDS_LIMIT = 20000; // session.active_ids_limit default (ir_http.py)
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
        // `count` == number of groups, per DynamicGroupList._setData.
        list.count = NB_GROUPS;
        list.groups = [];
        // The real record total lives here.
        list._nbRecordsMatchingDomain = TOTAL_RECORDS;
    } else {
        // `count` == number of records for a DynamicRecordList.
        list.count = TOTAL_RECORDS;
        // `records` is a getter backed by `_records` — assigning it throws.
        list._records = [];
    }

    list.model = {
        activeIdsLimit: ACTIVE_IDS_LIMIT,
        // The server caps the search at activeIdsLimit, so exactly that many
        // ids come back even though TOTAL_RECORDS match the domain.
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
        // Currently 0: the guard compares 20000 < 12 (groups) instead of
        // 20000 < 25000 (records), so the user is silently told nothing.
        expect(notifications.length).toBe(1);
        expect(notifications[0]).toInclude("20000");
    });

    test("grouped list reports the record total, not the group count", async () => {
        const { list, notifications } = makeList({ grouped: true });
        await list._toggleArchive(true);
        expect(notifications.length).toBe(1);
        // Must mention 25000 records — never "12".
        expect(notifications[0]).toInclude("25000");
    });
});
