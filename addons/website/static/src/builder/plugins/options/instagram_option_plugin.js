/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { SNIPPET_SPECIFIC_END } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { getCommonAncestor, selectElements } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

const log = makeLogger("website.builder.plugin.instagram_option");

const INSTAGRAM_URL_MARKER = "instagram.com/";

/**
 * @typedef { Object } InstagramOptionShared
 * @property { InstagramOptionPlugin['instagramPageNameFromUrl'] } instagramPageNameFromUrl
 */

export class InstagramOption extends BaseOptionComponent {
    static template = "website.InstagramOption";
    static selector = ".s_instagram_page";
}

class InstagramOptionPlugin extends Plugin {
    static id = "instagramOption";
    static dependencies = ["history"];
    static shared = ["instagramPageNameFromUrl"];

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(SNIPPET_SPECIFIC_END, InstagramOption)],
        builder_actions: {
            InstagramPageAction,
        },
        normalize_handlers: this.normalize.bind(this),
    };

    normalize(root) {
        const nodes = [
            ...selectElements(
                root,
                ".s_instagram_page[data-instagram-page-is-default]",
            ),
        ];
        if (nodes.length) {
            log.pipeline(
                "InstagramOptionPlugin normalize: default pages found",
                () => ({
                    nodes: nodes.length,
                }),
            );
            this.loadAndSetPage(nodes);
        }
    }

    async loadAndSetPage(nodes) {
        if (this.instagramUrl) {
            log.logic(
                "InstagramOptionPlugin loadAndSetPage: url already known",
                () => ({
                    instagramUrl: this.instagramUrl,
                }),
            );
            this.setPage(nodes);
            return;
        }
        const endRead = log.perf("InstagramOptionPlugin read social_instagram");
        const res = await this.services.orm.read(
            "website",
            [this.services.website.currentWebsite.id],
            ["social_instagram"],
        );
        endRead(() => ({ hasSocialInstagram: !!res?.[0]?.social_instagram }));
        if (res && res[0].social_instagram) {
            this.instagramUrl = this.instagramPageNameFromUrl(res[0].social_instagram);

            const hasChanged = this.dependencies.history.ignoreDOMMutations(() =>
                this.setPage(nodes),
            );

            log.logic("InstagramOptionPlugin default pages set", () => ({
                hasChanged,
                instagramUrl: this.instagramUrl,
            }));
            if (hasChanged) {
                const commonAncestor = getCommonAncestor(nodes, this.editable);
                this.dispatchTo("content_manually_updated_handlers", commonAncestor);
                this.config.onChange({ isPreviewing: false });
            }
        }
    }

    setPage(nodes) {
        let hasChanged = false;
        for (const element of nodes) {
            if (element.dataset.instagramPageIsDefault) {
                delete element.dataset.instagramPageIsDefault;
                if (this.instagramUrl) {
                    element.dataset.instagramPage = this.instagramUrl;
                }
                hasChanged = true;
            }
        }
        return hasChanged;
    }

    /**
     * @private
     * @param {string} url
     * @returns {string|undefined}
     */
    instagramPageNameFromUrl(url) {
        const pageName = url.split(INSTAGRAM_URL_MARKER)[1];
        if (
            !pageName ||
            pageName.includes("?") ||
            pageName.includes("#") ||
            (pageName.includes("/") && pageName.split("/")[1].length > 0)
        ) {
            return;
        }
        return pageName.split("/")[0];
    }
}

export class InstagramPageAction extends BuilderAction {
    static id = "instagramPage";
    static dependencies = ["instagramOption"];
    getValue({ editingElement }) {
        return editingElement.dataset["instagramPage"];
    }
    apply({ editingElement, value }) {
        delete editingElement.dataset.instagramPageIsDefault;
        log.logic("InstagramPageAction apply", () => ({
            value,
        }));
        if (value.includes(INSTAGRAM_URL_MARKER)) {
            value =
                this.dependencies.instagramOption.instagramPageNameFromUrl(value) || "";
        }
        editingElement.dataset["instagramPage"] = value;
        if (value === "") {
            log.logic("InstagramPageAction invalid page name");
            this.services.notification.add(_t("The Instagram page name is not valid"), {
                type: "warning",
            });
        }
    }
}

registry
    .category("website-plugins")
    .add(InstagramOptionPlugin.id, InstagramOptionPlugin);
