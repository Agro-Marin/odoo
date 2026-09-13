/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { onWillStart } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { rpc } from "@web/core/network";

const log = makeLogger("website.builder.option.footer_copyright_option");

export class FooterCopyrightOption extends BaseOptionComponent {
    static template = "website.FooterCopyrightOption";
    static selector = ".o_footer_copyright";
    static editableOnly = false;
    static groups = ["website.group_website_designer"];

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.languages = null;

        onWillStart(async () => {
            const endLanguages = log.perf("FooterCopyrightOption load languages");
            this.languages = await rpc("/website/get_languages", {}, { cache: true });
            endLanguages(() => ({ count: this.languages?.length }));
        });
    }
}
