import { DeletePlugin } from "@html_editor/core/delete_plugin";
import { FormatPlugin } from "@html_editor/core/format_plugin";
import { InputPlugin } from "@html_editor/core/input_plugin";
import { LineBreakPlugin } from "@html_editor/core/line_break_plugin";
import { SplitPlugin } from "@html_editor/core/split_plugin";
import { InlineCodePlugin } from "@html_editor/main/inline_code";
import { LinkPlugin } from "@html_editor/main/link/link_plugin";
import { ListPlugin } from "@html_editor/main/list/list_plugin";
import { PositionPlugin } from "@html_editor/main/position_plugin";
import { PowerButtonsPlugin } from "@html_editor/main/power_buttons_plugin";
import { SearchPowerboxPlugin } from "@html_editor/main/powerbox/search_powerbox_plugin";
import { CollaborationSelectionPlugin } from "@html_editor/others/collaboration/collaboration_selection_plugin";
import { describe, expect, test } from "@odoo/hoot";

describe("Implicit plugin dependencies", () => {
    test("input as an implicit dependency", async () => {
        for (const P of [
            DeletePlugin,
            FormatPlugin,
            InlineCodePlugin,
            LineBreakPlugin,
            LinkPlugin,
            ListPlugin,
            SearchPowerboxPlugin,
            SplitPlugin,
        ]) {
            expect(P.dependencies).toInclude(InputPlugin.id);
        }
    });
    test("position as an implicit dependency", async () => {
        for (const P of [PowerButtonsPlugin, CollaborationSelectionPlugin]) {
            expect(P.dependencies).toInclude(PositionPlugin.id);
        }
    });
});
