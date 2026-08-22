import { models } from "@web/../tests/web_test_helpers";

export class AccountJournal extends models.ServerModel {
    _name = "account.journal";

    /** Called on start by both BillGuide and the journal dashboard cards. */
    is_sample_action_available() {
        return false;
    }
}
