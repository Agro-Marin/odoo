/** @odoo-module native */
import { Component, useChildSubEnv, useEffect, useRef } from "@odoo/owl";
import { CenteredIcon } from "@point_of_sale/app/components/centered_icon/centered_icon";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { TagsList } from "@web/components/tags_list";
import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/translation";

import { groupOrderlines } from "./orderline_groups.js";
export class OrderDisplay extends Component {
    static template = "point_of_sale.OrderDisplay";
    static components = { CenteredIcon, Orderline, TagsList };
    static props = {
        order: Object,
        slots: Object,
        mode: { type: String, optional: true },
    };
    static defaultProps = {
        mode: "display",
    };

    setup() {
        this.scrollableRef = useRef("scrollable");
        /** @type {Map<string, import("./orderline_groups").OrderlineGroup>} */
        this.groupOfLine = new Map();
        useChildSubEnv({ orderlineGroupOf: (line) => this.groupOfLine.get(line.uuid) });
        useEffect(
            () => {
                this.scrollableRef.el
                    ?.querySelector(".orderline.selected")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" });
            },
            () => [this.props.order?.uiState?.selected_orderline_uuid],
        );
    }

    formatCurrency(amount) {
        return formatCurrency(amount, this.order.currency.id);
    }

    get isGrouped() {
        return this.props.mode !== "receipt" && !this.order.finalized;
    }

    get orderlineHeaders() {
        return {
            quantity: _t("Qty."),
            product: _t("Product"),
            price: _t("Price"),
        };
    }

    get comboSortedLines() {
        const sorted = this.order.lines.reduce((acc, line) => {
            if (line.combo_line_ids?.length > 0) {
                acc.push(line, ...line.combo_line_ids);
            } else if (!line.combo_parent_id) {
                acc.push(line);
            }
            return acc;
        }, []);
        this.groupOfLine.clear();
        if (!this.isGrouped) {
            return sorted;
        }
        const { lines, groupOf } = groupOrderlines(sorted);
        for (const [uuid, group] of groupOf) {
            this.groupOfLine.set(uuid, group);
        }
        return lines;
    }

    get order() {
        return this.props.order;
    }

    getInternalNotes() {
        return JSON.parse(this.props.order.internal_note || "[]");
    }
}
