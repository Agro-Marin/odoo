/** @odoo-module native */
import { LinkPopover } from "@html_editor/main/link/link_popover";
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("website.builder.option.navbar_link_popover");

export class NavbarLinkPopover extends LinkPopover {
    static template = "website.navbarLinkPopover";
    static props = {
        ...LinkPopover.props,
        onClickEditLink: Function,
        onClickEditMenu: Function,
    };

    /**
     * @override
     */
    onClickEdit() {
        const updateUrlAndLabel = this.updateUrlAndLabel.bind(this);
        const applyDeducedUrl = this.applyDeducedUrl.bind(this);
        const callback = () => {
            log.pipeline("NavbarLinkPopover edit link callback: update url and label");
            updateUrlAndLabel();
            applyDeducedUrl();
        };
        log.lifecycle("NavbarLinkPopover open edit link dialog");
        this.props.onClickEditLink(this, callback);
    }

    onClickEditMenu() {
        log.lifecycle("NavbarLinkPopover open edit menu dialog");
        this.props.onClickEditMenu();
    }
}
