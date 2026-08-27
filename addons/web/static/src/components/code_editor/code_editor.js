// @ts-check
/** @odoo-module native */

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { useAceEditor } from "@web/components/code_editor/ace_editor_hook";
import { loadBundle } from "@web/core/assets";
/**
 * @typedef {import("@web/components/code_editor/ace_editor_hook").CursorPosition} CursorPosition
 */
export class CodeEditor extends Component {
    static template = "web.CodeEditor";
    static props = {
        mode: {
            type: String,
            optional: true,
            validate: (mode) => CodeEditor.MODES.includes(mode),
        },
        value: { validate: (v) => typeof v === "string", optional: true },
        readonly: { type: Boolean, optional: true },
        onChange: { type: Function, optional: true },
        onBlur: { type: Function, optional: true },
        class: { type: String, optional: true },
        theme: {
            type: String,
            optional: true,
            validate: (theme) => CodeEditor.THEMES.includes(theme),
        },
        maxLines: { type: Number, optional: true },
        sessionId: { type: [Number, String], optional: true },
        initialCursorPosition: { type: Object, optional: true },
        showLineNumbers: { type: Boolean, optional: true },
    };
    static defaultProps = {
        readonly: false,
        value: "",
        onChange: () => {},
        class: "",
        theme: "",
        sessionId: 1,
        showLineNumbers: true,
    };

    /** @type {string[]} */
    static MODES = ["javascript", "xml", "qweb", "scss", "python"];
    /** @type {string[]} */
    static THEMES = ["", "monokai"];

    /** @type {import("@odoo/owl").Ref} */
    editorRef;
    /** @type {{ activeMode: string | undefined }} */
    state;
    /** @type {import("@web/components/code_editor/ace_editor_hook").AceEditorController} */
    controller;

    setup() {
        /** @type {import("@odoo/owl").Ref<HTMLElement>} */
        this.editorRef = useRef("editorRef");
        this.state = useState({
            /** @type {string | undefined} */
            activeMode: undefined,
        });

        onWillStart(async () => {
            await loadBundle("web.ace_lib");
        });

        this.controller = useAceEditor({
            ref: this.editorRef,
            getValue: () => this.props.value,
            getSessionId: () => this.props.sessionId,
            getMode: () => this.props.mode,
            getTheme: () => this.props.theme,
            isReadonly: () => this.props.readonly,
            showLineNumbers: () => this.props.showLineNumbers,
            getMaxLines: () => this.props.maxLines,
            onChange: (value, cursor) => this.props.onChange(value, cursor),
            onBlur: () => this.props.onBlur?.(),
            onModeChanged: (modeId) => {
                this.state.activeMode = modeId;
            },
            initialCursorPosition: this.props.initialCursorPosition,
        });
    }

    /**
     * @returns {any}
     */
    get aceEditor() {
        return this.controller.editor;
    }
}
