// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onWillStart,
    status,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
/**
 * @typedef {{ row: number, column: number }} CursorPosition
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

        const sessions = {};
        let ignoredAceChange = false;
        const onSessionChange = () => {
            if (this.props.onChange && !ignoredAceChange) {
                this.props.onChange(
                    this.aceEditor.getValue(),
                    this.aceEditor.getCursorPosition(),
                );
            }
        };
        useEffect(
            (el) => {
                if (!el) {
                    return;
                }

                const aceEditor = window.ace.edit(el);
                this.aceEditor = aceEditor;

                this.aceEditor.setOptions({
                    showPrintMargin: false,
                    useWorker: false,
                });
                this.aceEditor.$blockScrolling = true;

                this.aceEditor.on("changeMode", () => {
                    this.state.activeMode = this.aceEditor
                        .getSession()
                        .$modeId.split("/")
                        .at(-1);
                });

                const session = aceEditor.getSession();
                if (!sessions[this.props.sessionId]) {
                    sessions[this.props.sessionId] = session;
                }
                session.setValue(this.props.value);
                session.on("change", onSessionChange);
                this.aceEditor.on("blur", () => {
                    if (this.props.onBlur) {
                        this.props.onBlur();
                    }
                });

                return () => {
                    aceEditor.destroy();
                    for (const sessionId of Object.keys(sessions)) {
                        sessions[sessionId].destroy?.();
                        delete sessions[sessionId];
                    }
                };
            },
            () => [this.editorRef.el],
        );

        useEffect(
            (theme) => this.aceEditor.setTheme(theme ? `ace/theme/${theme}` : ""),
            () => [this.props.theme],
        );

        useEffect(
            (readonly, showLineNumbers, maxLines) => {
                this.aceEditor.setOptions({
                    readOnly: readonly,
                    highlightActiveLine: !readonly,
                    highlightGutterLine: !readonly,
                    maxLines,
                });

                this.aceEditor.renderer.setOptions({
                    displayIndentGuides: !readonly,
                    showGutter: !readonly && showLineNumbers,
                });

                this.aceEditor.renderer.$cursorLayer.element.style.display = readonly
                    ? "none"
                    : "block";
            },
            () => [
                this.props.readonly,
                this.props.showLineNumbers,
                this.props.maxLines,
            ],
        );

        useEffect(
            (sessionId, mode) => {
                let session = sessions[sessionId];
                if (!session) {
                    const value = this.props.value;
                    session = new window.ace.EditSession(value);
                    session.setUndoManager(new window.ace.UndoManager());
                    session.setOptions({
                        useWorker: false,
                        tabSize: 2,
                        useSoftTabs: true,
                    });
                    session.on("change", onSessionChange);
                    sessions[sessionId] = session;
                }
                session.setMode(mode ? `ace/mode/${mode}` : "");
                this.aceEditor.setSession(session);
            },
            () => [this.props.sessionId, this.props.mode],
        );

        useEffect(
            (sessionId, value) => {
                const session = sessions[sessionId];
                if (session && session.getValue() !== value) {
                    ignoredAceChange = true;
                    session.setValue(value);
                    ignoredAceChange = false;
                }
            },
            () => [this.props.sessionId, this.props.value],
        );

        const initialCursorPosition = this.props.initialCursorPosition;
        if (initialCursorPosition) {
            onMounted(() => {
                browser.requestAnimationFrame(() => {
                    if (status(this) !== "destroyed" && this.aceEditor) {
                        this.aceEditor.focus();
                        const { row, column } = initialCursorPosition;
                        const pos = {
                            row: row || 0,
                            column: column || 0,
                        };
                        this.aceEditor.selection.moveToPosition(pos);
                        this.aceEditor.renderer.scrollCursorIntoView(pos, 0.5);
                    }
                });
            });
        }
    }
}
