/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { Plugin } from "@html_editor/plugin";
import { closestElement } from "@html_editor/utils/dom_traversal";
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

import { MobileTablePicker } from "./mobile_table_picker.js";
import { TableMenu } from "./table_menu.js";
import { TablePicker } from "./table_picker.js";

export class TableUIPlugin extends Plugin {
    static id = "tableUi";
    static dependencies = ["history", "overlay", "selection", "table"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "openTablePicker",
                title: _t("Table"),
                description: _t("Insert a table"),
                icon: "fa-table",
                run: this.openPickerOrInsertTable.bind(this),
                isAvailable: isHtmlContentSupported,
            },
        ],
        powerbox_items: [
            {
                categoryId: "structure",
                commandId: "openTablePicker",
            },
        ],
        selectionchange_handlers: this.updateActiveCell.bind(this),
    };

    setup() {
        /** @type {import("@html_editor/core/overlay_plugin").Overlay} */
        this.picker = this.dependencies.overlay.createOverlay(TablePicker, {
            positionOptions: {
                updatePositionOnResize: false,
                onPositioned: (picker, position) => {
                    const popperRect = picker.getBoundingClientRect();
                    const { left } = position;
                    if (this.config.direction === "rtl") {
                        picker.style.right = `${window.innerWidth - left - popperRect.width}px`;
                        picker.style.removeProperty("left");
                    }
                },
            },
        });

        /** @type {import("@html_editor/core/overlay_plugin").Overlay} */
        this.mobilePicker = this.dependencies.overlay.createOverlay(MobileTablePicker, {
            positionOptions: {
                updatePositionOnResize: false,
                // Docked to the bottom edge: on a phone the caret sits
                // near the middle and an anchored popover would land
                // under the virtual keyboard.
                onPositioned: (picker) => {
                    picker.style.bottom = 0;
                    picker.style.width = "100%";
                    picker.style.removeProperty("top");
                },
            },
        });

        this.columnMenuOverlayKey = "table-column-menu";
        this.rowMenuOverlayKey = "table-row-menu";
        this.activeTd = null;

        // Dropdown reads `state` once, in setup, so the same object has to
        // serve every cell the menu is re-targeted at: handing it a fresh one
        // per hover throws out of onWillUpdateProps.
        this.rowMenuDropdownState = this.createDropdownState(
            this.closeColumnMenu.bind(this),
        );
        this.columnMenuDropdownState = this.createDropdownState(
            this.closeRowMenu.bind(this),
        );

        this.addDomListener(this.document, "pointermove", this.onMouseMove);
        const closeMenus = () => {
            if (this.isMenuOpened) {
                this.isMenuOpened = false;
                this.closeColumnMenu();
                this.closeRowMenu();
            }
        };
        this.addDomListener(this.document, "scroll", closeMenus, true);
    }

    openPicker() {
        this.picker.open({
            props: {
                editable: this.editable,
                overlay: this.picker,
                direction: this.config.direction || "ltr",
                insertTable: (params) => this.dependencies.table.insertTable(params),
            },
        });
    }

    openMobilePicker() {
        this.mobilePicker.open({
            props: {
                editable: this.editable,
                close: () => {
                    this.mobilePicker.close();
                    this.dependencies.selection.focusEditable();
                },
                insertTable: (params) => this.dependencies.table.insertTable(params),
            },
        });
    }

    openPickerOrInsertTable() {
        if (this.services.ui.isSmall) {
            this.openMobilePicker();
        } else {
            this.openPicker();
        }
    }

    updateActiveCell(selectionData) {
        const selection = selectionData.editableSelection;
        const selectedTd = closestElement(selection.startContainer, ".o_selected_td");
        if (selection.isCollapsed || !selectedTd) {
            return;
        }
        this.activeTd = false;
    }

    onMouseMove(ev) {
        const target = ev.target;
        if (this.isMenuOpened) {
            return;
        }
        const targetCell = closestElement(target, "td, th");
        if (
            targetCell &&
            targetCell !== this.activeTd &&
            this.editable.contains(targetCell)
        ) {
            if (
                ev.target.isContentEditable &&
                closestElement(target, "table").isContentEditable
            ) {
                this.setActiveTd(targetCell);
            }
        } else if (this.activeTd) {
            const isOverlay = target.closest(".o-we-table-menu");
            if (isOverlay) {
                return;
            }
            if (!targetCell) {
                this.setActiveTd(null);
            }
        }
    }

    createDropdownState(closeMenu) {
        const dropdownState = reactive({
            isOpen: false,
            open: () => {
                dropdownState.isOpen = true;
                closeMenu();
                this.isMenuOpened = true;
            },
            close: () => {
                dropdownState.isOpen = false;
                this.isMenuOpened = false;
            },
        });
        return dropdownState;
    }

    closeColumnMenu() {
        registry
            .category(this.config.localOverlayContainers.key)
            .remove(this.columnMenuOverlayKey);
    }

    closeRowMenu() {
        registry
            .category(this.config.localOverlayContainers.key)
            .remove(this.rowMenuOverlayKey);
    }

    setActiveTd(td) {
        this.activeTd = td;
        this.closeColumnMenu();
        this.closeRowMenu();
        // Both overlays are gone, so neither menu is open on the cell we are
        // leaving; the shared state has to say so before the next cell mounts.
        this.rowMenuDropdownState.isOpen = false;
        this.columnMenuDropdownState.isOpen = false;
        if (!td) {
            return;
        }
        const withAddStep =
            (fn) =>
            (...args) => {
                fn(...args);
                this.dependencies.history.addStep();
                this.dependencies.selection.focusEditable();
            };
        const tableMethods = {
            moveColumn: withAddStep(this.dependencies.table.moveColumn),
            addColumn: withAddStep(this.dependencies.table.addColumn),
            removeColumn: withAddStep(this.dependencies.table.removeColumn),
            moveRow: withAddStep(this.dependencies.table.moveRow),
            addRow: withAddStep(this.dependencies.table.addRow),
            removeRow: withAddStep(this.dependencies.table.removeRow),
            turnIntoHeader: withAddStep(this.dependencies.table.turnIntoHeader),
            turnIntoRow: withAddStep(this.dependencies.table.turnIntoRow),
            resetRowHeight: withAddStep(this.dependencies.table.resetRowHeight),
            resetColumnWidth: withAddStep(this.dependencies.table.resetColumnWidth),
            resetTableSize: withAddStep(this.dependencies.table.resetTableSize),
            clearColumnContent: withAddStep(this.dependencies.table.clearColumnContent),
            clearRowContent: withAddStep(this.dependencies.table.clearRowContent),
            mergeSelectedCells: withAddStep(this.dependencies.table.mergeSelectedCells),
            unmergeSelectedCell: withAddStep(
                this.dependencies.table.unmergeSelectedCell,
            ),
            buildTableGrid: this.dependencies.table.buildTableGrid,
        };
        if (td.cellIndex === 0) {
            registry
                .category(this.config.localOverlayContainers.key)
                .add(this.rowMenuOverlayKey, {
                    Component: TableMenu,
                    props: {
                        document: this.document,
                        type: "row",
                        target: td,
                        dropdownState: this.rowMenuDropdownState,
                        direction: this.config.direction || "ltr",
                        close: () => this.closeRowMenu(),
                        ...tableMethods,
                    },
                });
        }
        if (td.parentElement.rowIndex === 0) {
            registry
                .category(this.config.localOverlayContainers.key)
                .add(this.columnMenuOverlayKey, {
                    Component: TableMenu,
                    props: {
                        document: this.document,
                        type: "column",
                        target: td,
                        dropdownState: this.columnMenuDropdownState,
                        direction: this.config.direction || "ltr",
                        close: () => this.closeColumnMenu(),
                        ...tableMethods,
                    },
                });
        }
    }
}
