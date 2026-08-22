/** @odoo-module native */
import {
    getEmbeddedProps,
    StateChangeManager,
    useEmbeddedState,
} from "@html_editor/others/embedded_component_utils";
import { nodeSize } from "@html_editor/utils/position";
import {
    Component,
    onMounted,
    onWillStart,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { colorScheme } from "@web/core/color_scheme";

import {
    getPreValue,
    highlightPre,
} from "../../core/syntax_highlighting/syntax_highlighting_utils.js";
import { CodeToolbar } from "./code_toolbar.js";

export class EmbeddedSyntaxHighlightingComponent extends Component {
    static template = "html_editor.EmbeddedSyntaxHighlighting";

    static components = { CodeToolbar };
    static props = {
        value: { type: String },
        languageId: { type: String },
        onTextareaFocus: { type: Function },
        convertToParagraph: { type: Function },
        setSelection: { type: Function },
        host: { type: Object },
    };

    setup() {
        super.setup();
        this.state = useState({
            host: this.props.host,
            highlightedValue: "",
        });
        this.embeddedState = useEmbeddedState(this.props.host);
        this.preRef = useRef("pre");
        this.textareaRef = useRef("textarea");

        onWillStart(() => this.loadPrism());
        onMounted(() => {
            this.pre = this.preRef.el;
            this.textarea = this.textareaRef.el;
            this.document = this.textarea.ownerDocument;
            this.highlight();
        });

        useEffect(this.highlight.bind(this), () => [
            this.embeddedState.value,
            this.embeddedState.languageId,
        ]);
    }

    loadPrism() {
        return loadBundle(
            `html_editor.assets_prism${colorScheme.isDark ? "_dark" : ""}`,
            { targetDoc: this.props.host.ownerDocument },
        );
    }

    highlight() {
        const focus = this.document.activeElement === this.textarea;

        highlightPre(this.pre, this.embeddedState.value, this.embeddedState.languageId);

        const preValue = getPreValue(this.pre);
        if (this.textarea.value !== preValue) {
            this.textarea.value = preValue;
        }
        if (focus) {
            this.textarea.focus({ preventScroll: true });
            this.props.onTextareaFocus();
        }
        this.embeddedState.value = this.textarea.value;
    }

    onInput() {
        this.textarea.focus();
        this.props.onTextareaFocus();
        this.embeddedState.value = this.textarea.value;
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onKeydown(ev) {
        if (ev.key === "Tab") {
            ev.preventDefault();
            const tabSize = +getComputedStyle(this.textarea).tabSize || 4;
            const tab = " ".repeat(tabSize);
            const { selectionStart, selectionEnd } = this.textarea;
            const collapsed = selectionStart === selectionEnd;
            let start = this.textarea.value.slice(0, selectionStart).lastIndexOf("\n");
            start = start === -1 ? 0 : start;
            let newValue;
            let spacesRemovedAtStart = 0;
            if (ev.shiftKey) {
                let end = this.textarea.value
                    .slice(selectionEnd, this.textarea.value.length)
                    .indexOf("\n");
                end = end === -1 ? 0 : end;
                end = selectionEnd + end;
                newValue = this.textarea.value.slice(0, start);
                const regex = new RegExp(`(\n|^)( |\u00A0){1,${tabSize}}`, "g");
                const startSlice = this.textarea.value.slice(start, selectionStart);
                const cleanStartSlice = startSlice.replace(regex, "$1");
                spacesRemovedAtStart = startSlice.length - cleanStartSlice.length;
                newValue += cleanStartSlice;
                newValue += this.textarea.value
                    .slice(selectionStart, selectionEnd)
                    .replace(regex, "$1");
                newValue += this.textarea.value
                    .slice(selectionEnd, end)
                    .replace(regex, "$1");
                newValue += this.textarea.value.slice(end, this.textarea.value.length);
            } else {
                if (
                    collapsed &&
                    /\S/.test(this.textarea.value.slice(start, selectionStart))
                ) {
                    newValue =
                        this.textarea.value.slice(0, selectionStart) +
                        tab +
                        this.textarea.value.slice(
                            selectionStart,
                            this.textarea.value.length,
                        );
                } else {
                    newValue = start ? this.textarea.value.slice(0, start) : tab;
                    newValue += this.textarea.value
                        .slice(start, selectionEnd)
                        .replaceAll("\n", `\n${tab}`);
                    newValue += this.textarea.value.slice(
                        selectionEnd,
                        this.textarea.value.length,
                    );
                }
            }
            const insertedChars = newValue.length - this.textarea.value.length;
            this.textarea.value = newValue;
            const newStart =
                selectionStart + (ev.shiftKey ? -spacesRemovedAtStart : tabSize);
            const newEnd = collapsed ? newStart : selectionEnd + insertedChars;
            this.textarea.setSelectionRange(
                newStart,
                newEnd,
                this.textarea.selectionDirection,
            );
            this.embeddedState.value = this.textarea.value;
        } else if (ev.key === "Backspace") {
            if (this.textarea.value === "") {
                ev.preventDefault();
                this.props.convertToParagraph({ target: this.pre });
            }
        } else if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
            const { value, selectionStart, selectionEnd } = this.textarea;
            if (selectionStart !== selectionEnd) {
                return;
            }
            const isArrowUp = ev.key === "ArrowUp";
            const isCursorAtBoundary = isArrowUp
                ? value.slice(0, selectionStart).lastIndexOf("\n") === -1
                : value.indexOf("\n", selectionEnd) === -1;
            if (!isCursorAtBoundary) {
                return;
            }
            ev.preventDefault();
            this.textarea.blur();
            const node = isArrowUp
                ? this.props.host.previousElementSibling
                : this.props.host.nextElementSibling;
            this.props.setSelection({
                anchorNode: node,
                anchorOffset: isArrowUp ? nodeSize(node) : 0,
            });
        }
    }

    onScroll() {
        this.pre.scrollTop = this.textarea.scrollTop;
        this.pre.scrollLeft = this.textarea.scrollLeft;
    }

    /**
     * @param {string} languageId
     */
    onLanguageChange(languageId) {
        if (languageId && this.embeddedState.languageId !== languageId) {
            this.textarea.focus();
            this.props.onTextareaFocus();
            this.embeddedState.languageId = languageId;
        }
    }
}

export const syntaxHighlightingEmbedding = {
    name: "syntaxHighlighting",
    Component: EmbeddedSyntaxHighlightingComponent,
    getProps: (host) => ({ host, ...getEmbeddedProps(host) }),
    getStateChangeManager: (config) => new StateChangeManager(config),
};
