/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { Plugin } from "@html_editor/plugin";
import { getCommonAncestor, selectElements } from "@html_editor/utils/dom_traversal";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

export class FacebookOption extends BaseOptionComponent {
    static template = "website.FacebookOption";
    static selector = ".o_facebook_page";
}

class FacebookOptionPlugin extends Plugin {
    static id = "facebookOption";
    static dependencies = ["history"];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [FacebookOption],
        so_content_addition_selector: [".o_facebook_page"],
        builder_actions: {
            DataAttributeListAction,
            CheckFacebookLinkAction,
        },
        normalize_handlers: this.normalize.bind(this),
    };

    normalize(root) {
        for (const element of selectElements(root, ".o_facebook_page")) {
            let desiredHeight;
            if (element.dataset.tabs) {
                desiredHeight = element.dataset.tabs === "events" ? 300 : 500;
            } else if (element.dataset.small_header) {
                desiredHeight = 70;
            } else {
                desiredHeight = 150;
            }
            if (String(desiredHeight) !== element.dataset.height) {
                element.dataset.height = desiredHeight;
            }
        }

        const nodes = [...selectElements(root, ".o_facebook_page:not([data-href])")];
        if (nodes.length) {
            this.loadAndSetEmptyLink(nodes);
        }
    }

    async loadAndSetEmptyLink(nodes) {
        if (this.facebookUrl) {
            this.setEmptyLink(nodes);
            return;
        }
        const res = await this.services.orm.read(
            "website",
            [this.services.website.currentWebsite.id],
            ["social_facebook"],
        );
        if (res) {
            this.facebookUrl =
                res[0].social_facebook || "https://www.facebook.com/Odoo";

            const hasChanged = this.dependencies.history.ignoreDOMMutations(() =>
                this.setEmptyLink(nodes),
            );

            if (hasChanged) {
                const commonAncestor = getCommonAncestor(nodes, this.editable);
                this.dispatchTo("content_manually_updated_handlers", commonAncestor);
                this.config.onChange({ isPreviewing: false });
            }
        }
    }

    setEmptyLink(nodes) {
        let hasChanged = false;
        for (const element of nodes) {
            if (!element.dataset.href) {
                element.dataset.href = this.facebookUrl;
                hasChanged = true;
            }
        }
        return hasChanged;
    }
}

export class DataAttributeListAction extends BuilderAction {
    static id = "dataAttributeList";
    isApplied({ editingElement, params: { mainParam } = {}, value }) {
        return (editingElement.dataset[mainParam]?.split(",") || []).includes(value);
    }
    apply({ editingElement, params: { mainParam } = {}, value }) {
        editingElement.dataset[mainParam] = [
            ...(editingElement.dataset[mainParam]?.split(",") || []),
            value,
        ].join(",");
    }
    clean({ editingElement, params: { mainParam } = {}, value }) {
        editingElement.dataset[mainParam] = (
            editingElement.dataset[mainParam]?.split(",") || []
        )
            .filter((e) => e !== value)
            .join(",");
    }
}
export class CheckFacebookLinkAction extends BuilderAction {
    static id = "checkFacebookLink";
    setup() {
        this.closeNotif = () => {};
    }
    apply({ editingElement, value }) {
        editingElement.dataset.id = "";
        const id = this.idFromFacebookLink(value);
        if (id) {
            editingElement.dataset.id = id;
            this.checkFacebookId(id).then((ok) => {
                this.closeNotif();
                if (ok) {
                    this.closeNotif = () => {};
                } else {
                    this.closeNotif = this.services.notification.add(
                        _t("We couldn't find the Facebook page"),
                        { type: "warning" },
                    );
                }
            });
        } else {
            this.closeNotif();
            this.closeNotif = this.services.notification.add(
                _t("You didn't provide a valid Facebook link"),
                { type: "warning" },
            );
        }
    }
    idFromFacebookLink(url) {
        const match = url
            .trim()
            .match(
                /^(https?:\/\/)?((www\.)?(fb|facebook)|(m\.)?facebook)\.com\/(((profile\.php\?id=|people\/([^/?#]+\/)?|(p\/)?[^/?#]+-)(?<id>[0-9]{12,16}))|(?<nameid>[\w.]+))($|[/?# ])/,
            );

        return match?.groups.nameid || match?.groups.id;
    }

    async checkFacebookId(id) {
        try {
            const res = await fetch(`https://graph.facebook.com/${id}/picture`);
            return res.ok;
        } catch {
            return false;
        }
    }
}

registry.category("website-plugins").add(FacebookOptionPlugin.id, FacebookOptionPlugin);
