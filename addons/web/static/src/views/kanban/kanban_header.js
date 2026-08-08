// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_header */

import { Component, useRef } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { usePopover } from "@web/ui/popover/popover_hook";
import { utils } from "@web/ui/viewport";
import { useGroupManagement } from "@web/views/multi_record_group";
import { GroupConfigMenu } from "@web/views/view_components/group_config_menu";

import { ColumnProgress } from "./column_progress.js";

class KanbanHeaderTooltip extends Component {
    static template = "web.KanbanGroupTooltip";
    static props = {
        tooltip: Array,
        close: Function,
    };
}

export class KanbanHeader extends Component {
    static template = "web.KanbanHeader";
    static components = {
        ColumnProgress,
        Dropdown,
        DropdownItem,
        GroupConfigMenu,
    };
    static props = {
        activeActions: { type: Object },
        canQuickCreate: { type: Boolean, optional: true },
        deleteGroup: { type: Function },
        dialogClose: { type: Array },
        group: { type: Object },
        list: { type: Object },
        quickCreateState: { type: Object },
        scrollTop: { type: Function },
        tooltipInfo: { type: Object },
        progressBarState: { type: true, optional: true },
    };
    static defaultProps = {
        canQuickCreate: false,
    };

    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {ReturnType<typeof usePopover>} */
    popover;

    setup() {
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.rootRef = useRef("root");
        this.popover = usePopover(KanbanHeaderTooltip);
        this.onTitleMouseEnter = useDebounced(this.onTitleMouseEnter, 400);
        this.groupOps = useGroupManagement({
            getList: () => this.props.list,
            getMenuActiveActions: () => this.props.activeActions,
            getDialogClose: () => this.props.dialogClose,
            getExtraConfigItems: () => this.extraConfigItems,
            // Through the renderer's prop so its (overridable) delete flow
            // stays in charge.
            deleteGroup: (group) => this.props.deleteGroup(group),
        });
    }

    /**
     * @param {MouseEvent} ev
     */
    async onTitleMouseEnter(ev) {
        if (!this.hasTooltip) {
            return;
        }
        let tooltip;
        try {
            tooltip = await this.loadTooltip();
        } catch {
            return;
        }
        if (tooltip.length) {
            this.popover.open(/** @type {HTMLElement} */ (ev.target), { tooltip });
        }
    }

    onTitleMouseLeave() {
        /** @type {any} */ (this.onTitleMouseEnter).cancel();
        this.popover.close();
    }

    /**
     * Config items the kanban prepends to the registry-provided ones.
     *
     * @returns {Array<[string, Object]>}
     */
    get extraConfigItems() {
        return [
            [
                "toggle_group",
                {
                    label: _t("Fold"),
                    method: () => this.group.toggle(),
                    isVisible: () => !utils.isSmall(),
                    class: () => ({
                        o_kanban_toggle_fold: true,
                        disabled: this.props.list.model.useSampleModel,
                    }),
                    icon: "fa-compress",
                },
            ],
        ];
    }

    /** @returns {Object} */
    get configMenuProps() {
        return /** @type {any} */ (this.groupOps).getGroupConfigMenuProps(
            this.props.group,
        );
    }

    /** @returns {Object | undefined} */
    get progressBar() {
        return this.props.progressBarState?.getGroupInfo(this.group);
    }

    get group() {
        return this.props.group;
    }

    /** @returns {{ title: string, value: number }} */
    get groupAggregate() {
        const { group, progressBarState } = this.props;
        const { sumField } = progressBarState.progressAttributes;
        return progressBarState.getAggregateValue(group, sumField);
    }

    /** @returns {boolean} */
    get hasTooltip() {
        const { name, type } = this.group.groupByField;
        return (
            type === "many2one" && this.group.value && name in this.props.tooltipInfo
        );
    }

    /**
     * @returns {Promise<Array<{ title: string, value: any }>>}
     */
    loadTooltip = () => {
        this._tooltipProm ||= this._fetchTooltip().catch((error) => {
            this._tooltipProm = null;
            throw error;
        });
        return this._tooltipProm;
    };

    async _fetchTooltip() {
        const { name, relation: resModel } = this.group.groupByField;
        const tooltipInfo = this.props.tooltipInfo[name];
        const fieldNames = Object.keys(tooltipInfo);
        const [values] = await this.orm.silent.read(
            resModel,
            [this.group.value],
            ["display_name", ...fieldNames],
        );

        return fieldNames
            .filter((fieldName) => values[fieldName])
            .map((fieldName) => ({
                title: tooltipInfo[fieldName],
                value: values[fieldName],
            }));
    }

    quickCreate() {
        this.props.quickCreateState.groupId = this.group.id;
    }

    toggleGroup() {
        return this.group.toggle();
    }

    canQuickCreate() {
        return this.props.canQuickCreate;
    }

    /**
     * @param {*} value
     */
    async onBarClicked(value) {
        await this.props.progressBarState.selectBar(this.props.group.id, value);
        this.props.scrollTop();
    }
}
