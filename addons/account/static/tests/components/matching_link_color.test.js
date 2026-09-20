import "@account/components/matching_link_widget/matching_link_widget";

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";

test("matching links keep full, partial and unmatched color classes", () => {
    const MatchingLink = registry
        .category("fields")
        .get("matching_link_widget").component;
    for (const [value, expected] of [
        ["*", 0],
        ["0", 1],
        ["P10", 11],
        ["11", 1],
        ["P22", 1],
    ]) {
        const link = Object.create(MatchingLink.prototype);
        link.props = {
            name: "matching_number",
            record: { data: { matching_number: value } },
        };
        expect(link.colorCode).toBe(expected);
    }
});
