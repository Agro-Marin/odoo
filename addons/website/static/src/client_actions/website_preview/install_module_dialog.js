/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { WebsiteDialog } from "@website/components/dialog/dialog";

const log = makeLogger("website.dialog.install_module");

export class InstallModuleDialog extends Component {
    static components = { WebsiteDialog };
    static template = "website.InstallModuleDialog";
    static props = {
        title: String,
        installationText: String,
        installModule: Function,
        close: Function,
    };

    setup() {
        useLifecycleLog(log);
        this.installButtonTitle = _t("Install");
    }

    onClickInstall() {
        log.logic("install confirmed", () => ({ title: this.props.title }));
        this.props.close();
        this.props.installModule();
    }
}
