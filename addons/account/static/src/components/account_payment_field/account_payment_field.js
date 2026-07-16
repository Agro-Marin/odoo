/** @odoo-module native */
import { Component } from "@odoo/owl";
import { deserializeDate, formatDate } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/fields/formatters";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { usePopover } from "@web/ui/popover/popover_hook";

class AccountPaymentPopOver extends Component {
    static props = { "*": { optional: true } };
    static template = "account.AccountPaymentPopOver";
}

export class AccountPaymentField extends Component {
    static props = { ...standardFieldProps };
    static template = "account.AccountPaymentField";

    setup() {
        const position = localization.direction === "rtl" ? "bottom" : "left";
        this.popover = usePopover(AccountPaymentPopOver, { position });
        this.orm = useService("orm");
        this.action = useService("action");
    }

    getInfo() {
        const info = this.props.record.data[this.props.name] || {
            content: [],
            outstanding: false,
            title: "",
            move_id: this.props.record.resId,
        };
        // Derive display fields into new objects instead of mutating the record's
        // data in place on every render. (The former `index` field was never read.)
        const lines = info.content.map((line) => ({
            ...line,
            amount_formatted: formatMonetary(line.amount, {
                currencyId: line.currency_id,
            }),
            // line.date is a string; parse and format it to the user's date format.
            ...(line.date
                ? { formattedDate: formatDate(deserializeDate(line.date)) }
                : {}),
        }));
        return {
            lines,
            outstanding: info.outstanding,
            title: info.title,
            moveId: info.move_id,
        };
    }

    onInfoClick(ev, line) {
        this.popover.open(ev.currentTarget, {
            title: _t("Journal Entry Info"),
            ...line,
            _onRemoveMoveReconcile: this.removeMoveReconcile.bind(this),
            _onOpenMove: this.openMove.bind(this),
        });
    }

    async assignOutstandingCredit(moveId, id) {
        await this.orm.call(
            this.props.record.resModel,
            "js_assign_outstanding_line",
            [moveId, id],
            {},
        );
        await this.props.record.model.root.load();
    }

    async removeMoveReconcile(moveId, partialId) {
        this.popover.close();
        await this.orm.call(
            this.props.record.resModel,
            "js_remove_outstanding_partial",
            [moveId, partialId],
            {},
        );
        await this.props.record.model.root.load();
    }

    async openMove(moveId) {
        const action = await this.orm.call(
            this.props.record.resModel,
            "action_view_business_doc",
            [moveId],
            {},
        );
        this.action.doAction(action);
    }
}

export const accountPaymentField = {
    component: AccountPaymentField,
    supportedTypes: ["binary"],
};

registry.category("fields").add("payment", accountPaymentField);
