// @ts-check
/** @odoo-module native */

/** @module @web/fields/dynamic_placeholder_popover */

import { Component, onWillStart, useState } from "@odoo/owl";
import { ModelFieldSelectorPopover } from "@web/components/model_field_selector/model_field_selector_popover";
import { user } from "@web/core/user";
import { useAutofocus, useService } from "@web/core/utils/hooks";

export class DynamicPlaceholderPopover extends Component {
    static template = "web.DynamicPlaceholderPopover";
    static components = {
        ModelFieldSelectorPopover,
    };
    static props = ["resModel", "validate", "close"];

    /** @type {{ path: string; isPathSelected: boolean; defaultValue: string }} */
    state;

    setup() {
        useAutofocus();
        this.state = useState({
            path: "",
            isPathSelected: false,
            defaultValue: "",
        });
        this.getAllowedQwebExpressions = useService("allowed_qweb_expressions");
        onWillStart(() => this._loadAllowedExpressions());
    }

    async _loadAllowedExpressions() {
        [
            /** @type {any} */ (this).isTemplateEditor,
            /** @type {any} */ (this).allowedQwebExpressions,
        ] = /** @type {any} */ (
            await Promise.all([
                user.hasGroup("mail.group_mail_template_editor"),
                /** @type {any} */ (this).getAllowedQwebExpressions(
                    /** @type {any} */ (this.props).resModel,
                ),
            ])
        );
    }

    filter(fieldDef, path) {
        const fullPath = `object${path ? `.${path}` : ""}.${fieldDef.name}`;
        if (
            !(/** @type {any} */ (this).isTemplateEditor) &&
            !(/** @type {any} */ (this).allowedQwebExpressions.includes(fullPath))
        ) {
            return false;
        }
        if (fieldDef.is_property && fieldDef.type === "separator") {
            return false;
        }
        return (
            !["one2many", "boolean", "many2many"].includes(fieldDef.type) &&
            fieldDef.searchable
        );
    }
    closeFieldSelector(isPathSelected = false) {
        if (isPathSelected) {
            this.state.isPathSelected = true;
            return;
        }
        this.props.close();
    }
    setPath(path, fieldInfo) {
        this.state.path = path;
        /** @type {any} */ (this.state).fieldName = fieldInfo?.string;
        this.fieldType = fieldInfo?.type;
    }
    setDefaultValue(value) {
        this.state.defaultValue = value;
    }
    validate() {
        this.props.validate(this.state.path, this.state.defaultValue, this.fieldType);
        this.props.close();
    }

    onBack() {
        this.state.defaultValue = "";
        this.state.isPathSelected = false;
        this.state.path = "";
    }

    async onInputKeydown(ev) {
        switch (ev.key) {
            case "Enter": {
                this.validate();
                ev.stopPropagation();
                ev.preventDefault();
                break;
            }
            case "Escape": {
                this.props.close();
                break;
            }
        }
    }
}
