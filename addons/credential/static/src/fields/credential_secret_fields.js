/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class CredentialSecretFields extends Component {
    static template = "credential.SecretFields";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.revealed = useState({});
    }

    get entries() {
        return this.props.record.data[this.props.name] || [];
    }

    displayValue(entry) {
        if (typeof entry.value === "string") {
            return entry.value;
        }
        return this.revealed[entry.code] ?? "";
    }

    placeholder(entry) {
        if (entry.filled && !(entry.code in this.revealed)) {
            return _t("Stored — type to replace");
        }
        return entry.placeholder || "";
    }

    onInput(entry, value) {
        const entries = this.entries.map((candidate) =>
            candidate.code === entry.code ? { ...candidate, value } : candidate,
        );
        this.props.record.update({ [this.props.name]: entries });
    }

    async onReveal(entry) {
        if (entry.code in this.revealed) {
            delete this.revealed[entry.code];
            return;
        }
        const id = this.props.record.resId;
        if (!id) {
            return;
        }
        const value = await this.orm.call(
            this.props.record.resModel,
            "action_reveal_secret_field",
            [[id], entry.code],
        );
        this.revealed[entry.code] = value;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const credentialSecretFields = {
    component: CredentialSecretFields,
    displayName: _t("Credential Secret Fields"),
    supportedTypes: ["json"],
};

registerField("credential_secret_fields", credentialSecretFields);
