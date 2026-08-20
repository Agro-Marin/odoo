// @ts-check
/** @odoo-module native */

/** @module @web/fields/dynamic_placeholder_popover */

import { Component, onWillStart, useState } from "@odoo/owl";
import { ModelFieldSelectorPopover } from "@web/components/model_field_selector/model_field_selector_popover";
import { user } from "@web/core/user";
import { useAutofocus, useService } from "@web/core/utils/hooks";

import {
    isRenderableFieldType,
    placeholderExpression,
} from "./dynamic_placeholder_syntax.js";

export class DynamicPlaceholderPopover extends Component {
    static template = "web.DynamicPlaceholderPopover";
    static components = {
        ModelFieldSelectorPopover,
    };
    static props = {
        resModel: String,
        validate: Function,
        close: Function,
        /** the placeholder lands in a char/text field, so markup shows as tags */
        plainText: { type: Boolean, optional: true },
        /** the expression the caller will write for a path; see below */
        expressionFor: { type: Function, optional: true },
    };
    static defaultProps = {
        plainText: false,
        expressionFor: (path) => placeholderExpression(path),
    };

    /** @type {{ path: string; isPathSelected: boolean; defaultValue: string; fieldName: string; fieldType: string }} */
    state;
    /** @type {boolean} */
    isTemplateEditor = false;
    /** @type {string[]} */
    allowedQwebExpressions = [];

    setup() {
        useAutofocus();
        this.state = useState({
            path: "",
            isPathSelected: false,
            defaultValue: "",
            fieldName: "",
            fieldType: "",
        });
        this.getAllowedQwebExpressions = useService("allowed_qweb_expressions");
        onWillStart(() => this._loadAllowedExpressions());
    }

    async _loadAllowedExpressions() {
        this.isTemplateEditor = await user.hasGroup("mail.group_mail_template_editor");
        if (this.isTemplateEditor) {
            // An editor may write any expression, so the allow-list has no say
            // and fetching it is one RPC per model spent on nothing.
            return;
        }
        this.allowedQwebExpressions = await this.getAllowedQwebExpressions(
            this.props.resModel,
        );
    }

    /**
     * The server tests the *expression* a placeholder will carry
     * (`ir_qweb._is_expression_allowed`), not the path it was picked from. A
     * datetime is written as `format_datetime(object.x, tz=...)`, which no
     * allow-list holds, so filtering on `object.x` offered fields whose
     * placeholder the save would then refuse -- with an error naming a string
     * the user never wrote.
     */
    filter(fieldDef, path) {
        if (!isRenderableFieldType(fieldDef, { plainText: this.props.plainText })) {
            return false;
        }
        if (this.isTemplateEditor) {
            return true;
        }
        const fullPath = `${path ? `${path}.` : ""}${fieldDef.name}`;
        return this.allowedQwebExpressions.includes(
            this.props.expressionFor(fullPath, fieldDef),
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
        this.state.fieldName = fieldInfo?.string || "";
        this.state.fieldType = fieldInfo?.type || "";
    }
    setDefaultValue(value) {
        this.state.defaultValue = value;
    }
    validate() {
        this.props.validate(
            this.state.path,
            this.state.defaultValue,
            this.state.fieldType,
        );
        this.props.close();
    }

    onBack() {
        this.state.defaultValue = "";
        this.state.isPathSelected = false;
        this.state.path = "";
        this.state.fieldName = "";
        this.state.fieldType = "";
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
