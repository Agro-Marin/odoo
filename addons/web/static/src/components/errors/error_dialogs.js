// @ts-check
/** @odoo-module native */

/** @module @web/components/errors/error_dialogs */

import { Component, markup, useState } from "@odoo/owl";
import { CopyButton } from "@web/components/copy_button/copy_button";
import { useAction } from "@web/core/action_port";
import { browser } from "@web/core/browser/browser";
import { DateTime } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { capitalize } from "@web/core/utils/format/strings";
import { Dialog } from "@web/ui/dialog/dialog";

/**
 * @typedef {Object} StandardErrorDialogProps
 * @property {string | null} [traceback]
 * @property {string} [message]
 * @property {string} [name]
 * @property {string | null} [exceptionName]
 * @property {Object | null} [data]
 * @property {string | null} [subType]
 * @property {number | string | null} [code]
 * @property {string | null} [type]
 * @property {string | null} [serverHost]
 * @property {number | null} [id]
 * @property {string | null} [model]
 * @property {Function} close
 */

export const standardErrorDialogProps = {
    traceback: { type: [String, { value: null }], optional: true },
    message: { type: String, optional: true },
    name: { type: String, optional: true },
    exceptionName: { type: [String, { value: null }], optional: true },
    data: { type: [Object, { value: null }], optional: true },
    subType: { type: [String, { value: null }], optional: true },
    code: { type: [Number, String, { value: null }], optional: true },
    type: { type: [String, { value: null }], optional: true },
    serverHost: { type: [String, { value: null }], optional: true },
    id: { type: [Number, { value: null }], optional: true },
    model: { type: [String, { value: null }], optional: true },
    close: Function,
};

/** @type {Map<string, string>} */
export const odooExceptionTitleMap = new Map(
    Object.entries({
        "odoo.addons.base.models.ir_mail_server.MailDeliveryError":
            _t("MailDeliveryError"),
        "odoo.addons.base.models.ir_mail_server.MailDeliveryException": _t(
            "MailDeliveryException",
        ),
        "odoo.exceptions.AccessDenied": _t("Access Denied"),
        "odoo.exceptions.MissingError": _t("Missing Record"),
        "odoo.addons.web.controllers.action.MissingActionError": _t("Missing Action"),
        "odoo.addons.base.models.ir_actions_server.ServerActionWithWarningsError":
            _t("Invalid Operation"),
        "odoo.addons.base.models.ir_actions.ServerActionWithWarningsError":
            _t("Invalid Operation"),
        "odoo.exceptions.UserError": _t("Invalid Operation"),
        "odoo.exceptions.ValidationError": _t("Validation Error"),
        "odoo.exceptions.AccessError": _t("Access Error"),
        "werkzeug.exceptions.Forbidden": _t("Access Denied"),
        "odoo.exceptions.Warning": _t("Warning"),
    }),
);

export class ErrorDialog extends Component {
    static template = "web.ErrorDialog";
    static components = { CopyButton, Dialog };
    static title = _t("Odoo Error");
    static showTracebackButtonText = _t("See technical details");
    static hideTracebackButtonText = _t("Hide technical details");
    static props = { ...standardErrorDialogProps };

    setup() {
        this.state = useState({
            showTraceback: false,
        });
        this.contextDetails = "Occurred ";
        if (this.props.serverHost) {
            this.contextDetails += `on ${this.props.serverHost} `;
        }
        if (this.props.model) {
            this.contextDetails += `on model ${this.props.model} `;
        }
        this.contextDetails += `on ${DateTime.now()
            .setZone("UTC")
            .toFormat("yyyy-MM-dd HH:mm:ss")} GMT`;
    }

    /**
     * @returns {string}
     */
    get clipboardReport() {
        return `${this.props.name}\n\n${this.props.message}\n\n${this.contextDetails}\n\n${this.props.traceback}`;
    }

    /** @returns {string} */
    get copiedText() {
        return _t("Copied");
    }
}

export class ClientErrorDialog extends ErrorDialog {}
ClientErrorDialog.title = _t("Odoo Client Error");

export class NetworkErrorDialog extends ErrorDialog {}
NetworkErrorDialog.title = _t("Odoo Network Error");

export class RequestEntityTooLargeErrorDialog extends ErrorDialog {}
RequestEntityTooLargeErrorDialog.title = _t(
    "The request sent to the server was too large",
);

export class RPCErrorDialog extends ErrorDialog {
    setup() {
        super.setup();
        this.inferTitle();
        this.traceback = this.props.traceback;
        if (this.props.data && this.props.data.debug) {
            this.traceback = `${this.props.data.debug}\nThe above server error caused the following client error:\n${this.traceback}`;
        }
    }
    inferTitle() {
        if (
            this.props.exceptionName &&
            odooExceptionTitleMap.has(this.props.exceptionName)
        ) {
            this.title = odooExceptionTitleMap.get(this.props.exceptionName).toString();
            return;
        }
        if (!this.props.type) {
            return;
        }
        switch (this.props.type) {
            case "server":
                this.title = _t("Odoo Server Error");
                break;
            case "script":
                this.title = _t("Odoo Client Error");
                break;
            case "network":
                this.title = _t("Odoo Network Error");
                break;
        }
    }

    /** @returns {string} */
    get clipboardReport() {
        return `${this.props.name}\n\n${this.props.message}\n\n${this.contextDetails}\n\n${this.traceback}`;
    }
}

export class WarningDialog extends Component {
    static template = "web.WarningDialog";
    static components = { Dialog };
    static props = {
        ...standardErrorDialogProps,
        title: { type: String, optional: true },
    };

    setup() {
        this.title = this.inferTitle();
        const { data, message } = this.props;
        if (data?.arguments?.length > 0) {
            this.message = data.arguments[0];
        } else {
            this.message = message;
        }
    }
    /**
     * @returns {string}
     */
    inferTitle() {
        if (
            this.props.exceptionName &&
            odooExceptionTitleMap.has(this.props.exceptionName)
        ) {
            return odooExceptionTitleMap.get(this.props.exceptionName).toString();
        }
        return this.props.title || _t("Odoo Warning");
    }
}

export class RedirectWarningDialog extends Component {
    static template = "web.RedirectWarningDialog";
    static components = { Dialog };
    static props = { ...standardErrorDialogProps };

    setup() {
        this.actionService = useAction();
        const { data, subType } = this.props;
        const [message, actionId, buttonText, additionalContext] =
            data?.arguments || [];
        this.title = capitalize(subType) || _t("Odoo Warning");
        this.message = message;
        this.actionId = actionId;
        this.buttonText = buttonText;
        this.additionalContext = additionalContext;
    }
    async onClick() {
        if (!this.actionId) {
            return this.props.close();
        }
        const options = { forceLeave: true };
        if (this.additionalContext) {
            options.additionalContext = this.additionalContext;
        }
        if (this.actionId.help) {
            this.actionId.help = markup(this.actionId.help);
        }
        await this.actionService.doAction(this.actionId, options);
        this.props.close();
    }
}

export class Error504Dialog extends Component {
    static template = "web.Error504Dialog";
    static components = { Dialog };
    static props = { ...standardErrorDialogProps };
}

export class SessionExpiredDialog extends Component {
    static template = "web.SessionExpiredDialog";
    static components = { Dialog };
    static props = { ...standardErrorDialogProps };

    onClick() {
        browser.location.reload();
    }
}

registry
    .category("error_dialogs")
    .add("odoo.exceptions.AccessDenied", WarningDialog)
    .add("odoo.exceptions.AccessError", WarningDialog)
    .add("odoo.exceptions.MissingError", WarningDialog)
    .add("odoo.addons.web.controllers.action.MissingActionError", WarningDialog)
    .add(
        "odoo.addons.base.models.ir_actions_server.ServerActionWithWarningsError",
        WarningDialog,
    )
    .add(
        "odoo.addons.base.models.ir_actions.ServerActionWithWarningsError",
        WarningDialog,
    )
    .add("odoo.exceptions.UserError", WarningDialog)
    .add("odoo.exceptions.ValidationError", WarningDialog)
    .add("odoo.exceptions.RedirectWarning", RedirectWarningDialog)
    .add("odoo.http.SessionExpiredException", SessionExpiredDialog)
    .add("werkzeug.exceptions.Forbidden", WarningDialog)
    .add("504", Error504Dialog);
