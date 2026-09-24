/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { useMailContext } from "@mail/utils/common/mail_context";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    setup() {
        super.setup(...arguments);
        this.mailContext = useMailContext();
    },

    get placeholder() {
        if (this.mailContext.inFrontendPortalChatter) {
            return _t("Write a message…");
        }
        return super.placeholder;
    },
});
