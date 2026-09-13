/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.grid_column_option");

export class GridColumnsOption extends BaseOptionComponent {
    static template = "website.GridColumnsOption";
    static selector = ".row:not(.s_col_no_resize) > div";

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.state = useDomState((editingElement) => ({
            isGridMode: editingElement.parentElement.classList.contains("o_grid_mode"),
        }));
    }
}
