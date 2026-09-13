/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { sendRequest } from "@website/js/utils";

const log = makeLogger("website.interaction.post_link");

export class PostLink extends Interaction {
    static selector = ".post_link";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _select: () => this.el.matches("select") && this.el,
        _nonSelect: () => !this.el.matches("select") && this.el,
    };
    dynamicContent = {
        _root: {
            "t-att-class": () => ({
                o_post_link_js_loaded: true,
            }),
        },
        _nonSelect: {
            "t-on-click.prevent": this.onClickPost,
        },
        _select: {
            "t-on-change.prevent": this.onClickPost,
        },
    };

    onClickPost() {
        const data = {};
        for (const [key, value] of Object.entries(this.el.dataset)) {
            if (key.startsWith("post_")) {
                data[key.slice(5)] = value;
            }
        }
        log.pipeline("PostLink onClickPost: send request", () => ({
            url: this.el.dataset.post || this.el.href || this.el.value,
            params: Object.keys(data),
        }));
        sendRequest(this.el.dataset.post || this.el.href || this.el.value, data);
    }
}

registry.category("public.interactions").add("website.post_link", PostLink);
