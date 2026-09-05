// @ts-check
/** @odoo-module native */

import { DomainSelector } from "@web/components/domain_selector/domain_selector";
import { EditorDialog } from "@web/components/editor_dialog/editor_dialog";
import { Domain } from "@web/core/domain";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

export class DomainSelectorDialog extends EditorDialog {
    static template = "web.DomainSelectorDialog";
    static components = { ...EditorDialog.components, DomainSelector };
    static props = {
        close: Function,
        onConfirm: Function,
        resModel: String,
        className: { type: String, optional: true },
        defaultConnector: {
            type: [{ value: "&" }, { value: "|" }],
            optional: true,
        },
        domain: String,
        isDebugMode: { type: Boolean, optional: true },
        readonly: { type: Boolean, optional: true },
        text: { type: String, optional: true },
        confirmButtonText: { type: String, optional: true },
        disableConfirmButton: { type: Function, optional: true },
        discardButtonText: { type: String, optional: true },
        title: { type: String, optional: true },
        context: { type: Object, optional: true },
    };
    static defaultProps = {
        isDebugMode: false,
        readonly: false,
        context: {},
    };

    /** @returns {string} */
    get initialValue() {
        return this.props.domain;
    }

    /** @returns {string} */
    get invalidMessage() {
        return _t("Domain is invalid. Please correct it");
    }

    get confirmButtonText() {
        return this.props.confirmButtonText || _t("Confirm");
    }

    get dialogTitle() {
        return this.props.title || _t("Domain");
    }

    get disabled() {
        if (this.props.disableConfirmButton) {
            return this.props.disableConfirmButton(this.state.value);
        }
        return false;
    }

    get discardButtonText() {
        return this.props.discardButtonText || _t("Discard");
    }

    get domainSelectorProps() {
        return {
            className: this.props.className,
            resModel: this.props.resModel,
            readonly: this.props.readonly,
            isDebugMode: this.props.isDebugMode,
            defaultConnector: this.props.defaultConnector,
            domain: this.state.value,
            update: (/** @type {string} */ domain) => this.update(domain),
        };
    }

    /**
     * @returns {Promise<boolean>}
     */
    async isValueValid() {
        let domain;
        try {
            domain = new Domain(this.state.value).toList({
                ...user.context,
                ...this.props.context,
            });
        } catch {
            return false;
        }
        try {
            return await rpc("/web/domain/validate", {
                model: this.props.resModel,
                domain,
            });
        } catch {
            return false;
        }
    }
}
