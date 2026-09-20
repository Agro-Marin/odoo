/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";

const log = makeLogger("website.dialog.edit_head_body");

export class EditHeadBodyDialog extends Component {
    static template = "website.EditHeadBodyDialog";
    static components = { CodeEditor, Dialog };
    static props = {
        close: Function,
    };

    setup() {
        useLifecycleLog(log);
        this.orm = useService("orm");
        this.website = useService("website");

        this.state = useState({
            head: "",
            body: "",
        });

        onWillStart(async () => {
            const endRead = log.perf("read custom code", () => ({
                websiteId: this.website.currentWebsite.id,
            }));
            const websites = await this.orm.read(
                "website",
                [this.website.currentWebsite.id],
                ["custom_code_head", "custom_code_footer"],
            );
            endRead();
            const website = websites[0];
            this.state.head = website.custom_code_head || "";
            this.state.body = website.custom_code_footer || "";
        });
    }

    async onSave() {
        const endWrite = log.perf("write custom code", () => ({
            websiteId: this.website.currentWebsite.id,
            headLength: this.state.head.length,
            bodyLength: this.state.body.length,
        }));
        await this.orm.write("website", [this.website.currentWebsite.id], {
            custom_code_head: this.state.head,
            custom_code_footer: this.state.body,
        });
        endWrite();
        this.props.close();
    }
}
