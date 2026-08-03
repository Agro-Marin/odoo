// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/attachment_image/attachment_image_field */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class AttachmentImageField extends Component {
    static template = "web.AttachmentImageField";
    static props = { ...standardFieldProps };
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const attachmentImageField = {
    component: AttachmentImageField,
    displayName: _t("Attachment Image"),
    supportedTypes: ["many2one"],
};

registerField("attachment_image", attachmentImageField);
