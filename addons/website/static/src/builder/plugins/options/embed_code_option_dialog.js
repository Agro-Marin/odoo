/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";
import { EditHeadBodyDialog } from "@website/components/edit_head_body_dialog/edit_head_body_dialog";

const log = makeLogger("website.builder.option.embed_code_option_dialog");

export class EmbedCodeOptionDialog extends Component {
    static template = "website.EmbedCodeOptionDialog";
    static components = { Dialog, CodeEditor };
    static props = {
        title: String,
        value: String,
        mode: String,
        confirm: Function,
        close: Function,
    };
    setup() {
        useLifecycleLog(log);
        this.dialog = useService("dialog");
        this.state = useState({ value: this.props.value });
    }
    onCodeChange(newValue) {
        this.state.value = newValue;
    }
    onConfirm() {
        log.logic("EmbedCodeOptionDialog confirm", () => ({
            length: this.state.value.length,
            changed: this.state.value !== this.props.value,
        }));
        this.props.confirm(this.state.value);
        this.props.close();
    }
    onInjectHeadOrBody() {
        log.lifecycle("EmbedCodeOptionDialog open EditHeadBodyDialog");
        this.dialog.add(EditHeadBodyDialog);
        this.props.close();
    }
}
