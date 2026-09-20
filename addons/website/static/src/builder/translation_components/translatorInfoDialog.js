/** @odoo-module native */
import { Component } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { WebsiteDialog } from "@website/components/dialog/dialog";

export const localStorageNoDialogKey = "website_translator_nodialog";

const log = makeLogger("website.builder.translation.translator_info_dialog");

export class TranslatorInfoDialog extends Component {
    static components = { WebsiteDialog };
    static template = "website_builder.TranslatorInfoDialog";
    static props = {
        close: Function,
    };
    setup() {
        useLifecycleLog(log);
        this.strongOkButton = _t("Ok, never show me this again");
        this.okButton = _t("Ok");
    }

    onStrongOkClick() {
        log.logic("onStrongOkClick: never show translator dialog again");
        browser.localStorage.setItem(localStorageNoDialogKey, true);
    }
}
