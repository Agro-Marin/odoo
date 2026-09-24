/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { areColsCustomized } from "@html_builder/utils/column_layout_utils";

export class SelectNumberColumn extends BaseOptionComponent {
    static template = "html_builder.SelectNumberColumn";

    setup() {
        super.setup();
        this.builderContext = useBuilderContext();
        this.state = useDomState((editingElement) => {
            const columnEls = editingElement.querySelector(":scope > .row")?.children;
            return {
                isCustomColumn:
                    columnEls &&
                    areColsCustomized(
                        columnEls,
                        this.builderContext.editor.config.isMobileView(editingElement),
                        this.builderContext.editor.config.mobileBreakpoint,
                    ),
                canHaveZeroColumns: editingElement.matches(".s_allow_columns"),
                hasFixedColumnCount: !!editingElement.querySelector(
                    ":scope > .row.s_nb_column_fixed",
                ),
            };
        });
    }
}
