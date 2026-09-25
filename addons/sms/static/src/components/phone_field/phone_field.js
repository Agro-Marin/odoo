/** @odoo-module native */
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";
import {
    PhoneField,
    phoneField,
    formPhoneField,
    phoneFieldDefaultProps,
    phoneFieldProps,
} from "@web/fields/basic/phone/phone_field";
import { SendSMSButton } from "@sms/components/sms_button/sms_button";

patch(PhoneField, {
    components: {
        ...PhoneField.components,
        SendSMSButton,
    },
});
Object.assign(phoneFieldDefaultProps, {
    enableButton: true,
});
Object.assign(phoneFieldProps, {
    enableButton: { type: Boolean, optional: true },
});

const patchDescr = () => ({
    extractProps({ options }) {
        const props = super.extractProps(...arguments);
        props.enableButton = options.enable_sms;
        return props;
    },
    supportedOptions: [
        {
            label: _t("Enable SMS"),
            name: "enable_sms",
            type: "boolean",
            default: true,
        },
    ],
});

patch(phoneField, patchDescr());
patch(formPhoneField, patchDescr());
