/** @odoo-module native */
import { useAccountContext } from "@account/account_context";
import { AttachmentView } from "@mail/core/common/attachment_view";
import { onMounted } from "@odoo/owl";
import { useBus } from "@web/core/utils/hooks";

export class AccountAttachmentView extends AttachmentView {
    static props = [...AttachmentView.props, "openInPopout"];
    static components = { AttachmentView };

    setup() {
        super.setup();
        this.accountContext = useAccountContext();
        if (this.props.openInPopout) {
            onMounted(this.onClickPopout);
        }
        useBus(this.uiService.bus, "resize", () =>
            this.accountContext.setPopout(false),
        );
    }
}
