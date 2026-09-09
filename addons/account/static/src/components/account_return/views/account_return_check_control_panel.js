/** @odoo-module native */
import { ControlPanel } from "@web/search/control_panel/control_panel";

export class AccountReturnCheckControlPanel extends ControlPanel {
    static template = "account.account_return_check_control_panel";

    setup() {
        super.setup();
        this.state.embeddedInfos.showEmbedded = true;
        // This panel shows every embedded action, not the user's saved subset.
        // It used to say so by overriding `_isEmbeddedActionVisible`, which
        // ControlPanel stopped declaring when the member moved to
        // EmbeddedActionsBar -- the override went dead and the panel silently
        // fell back to the saved subset, with no error and no failing test.
        // The flag is read by EmbeddedActions.isVisible per action per render,
        // so it survives the asynchronous arrival of the action list that
        // seeding `visibleEmbeddedActions` here would not.
        this.state.embeddedInfos.showAllEmbeddedActions = true;
    }
}
