/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { serializeDate } from "@web/core/l10n/dates";
import { user } from "@web/core/user";

const { DateTime } = luxon;
const FAVORITES_COUNT = 6;

export async function fetchUserFavoritesWorkEntries(orm) {
    const groups = await orm.formattedReadGroup(
        "hr.work.entry",
        [
            ["create_uid", "=", user.userId],
            ["create_date", ">", serializeDate(DateTime.local().minus({ months: 3 }))],
        ],
        ["work_entry_type_id", "create_date:day"],
        [],
        { order: "create_date:day desc" },
    );
    const workEntryTypeIds = [
        ...new Set(groups.map((group) => group.work_entry_type_id?.[0]).filter(Boolean)),
    ].slice(0, FAVORITES_COUNT);
    if (!workEntryTypeIds.length) {
        return [];
    }
    const workEntryTypes = await orm.read("hr.work.entry.type", workEntryTypeIds, [
        "display_name",
        "display_code",
        "color",
    ]);
    return workEntryTypes.sort((a, b) =>
        a.display_code
            ? a.display_code.localeCompare(b.display_code)
            : a.display_name.localeCompare(b.display_name),
    );
}
