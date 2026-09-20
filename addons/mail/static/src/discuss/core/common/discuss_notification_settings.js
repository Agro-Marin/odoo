// @ts-check
/** @odoo-module native */
import { MESSAGE_SOUND } from "@mail/core/common/settings_model";
import {
    removeLocalStorageItem,
    setLocalStorageItem,
} from "@mail/utils/common/local_storage";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
export class DiscussNotificationSettings extends Component {
    static props = {};
    static template = "mail.DiscussNotificationSettings";

    setup() {
        this.store = useService("mail.store");
        this.state = useState({
            selectedDuration: false,
        });
    }

    onChangeMessageSound() {
        if (this.store.settings.messageSound) {
            this.disableMessageSound();
        } else {
            this.enableMessageSound();
        }
    }

    enableMessageSound() {
        removeLocalStorageItem(this.store, MESSAGE_SOUND);
    }

    disableMessageSound() {
        setLocalStorageItem(this.store, MESSAGE_SOUND, String(false));
    }
}
