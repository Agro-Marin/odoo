// @ts-check
/** @odoo-module native */

import { Component, useRef, useSubEnv } from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { useAction } from "@web/core/action_port";
import { Layout } from "@web/search/layout";
import { getDefaultConfig } from "@web/views/view";
import { useEnrichWithActionLinks } from "@web/webclient/actions/reports/report_hook";

export class ReportAction extends Component {
    static components = { Layout };
    static template = "web.ReportAction";
    static props = ["*"];
    /**
     * Assigned in setup() and read from other methods, a sequence TypeScript
     * cannot follow, so the field is declared.
     *
     * @type {import("@web/core/action_port").ActionPort}
     */
    action;

    setup() {
        useSubEnv({
            config: {
                ...getDefaultConfig(),
                ...this.env.config,
            },
        });
        useSetupAction();

        this.action = useAction();
        this.title = this.props.display_name || this.props.name;
        this.reportUrl = this.props.report_url;
        this.iframe = useRef("iframe");
        useEnrichWithActionLinks(this.iframe);
    }

    /** @param {Event} ev */
    onIframeLoaded(ev) {
        const iframe = /** @type {HTMLIFrameElement} */ (ev.target);
        if (!iframe.contentWindow) {
            return;
        }
        const iframeDocument = iframe.contentWindow.document;
        iframeDocument.body.classList.add("o_in_iframe", "container-fluid");
        iframeDocument.body.classList.remove("container");
    }

    print() {
        this.action.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: this.props.report_name,
            report_file: this.props.report_file,
            data: this.props.data || {},
            context: this.props.context || {},
            display_name: this.title,
        });
    }
}
