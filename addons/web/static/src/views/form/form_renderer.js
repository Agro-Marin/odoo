// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_renderer - Compiles form arch into an OWL template and manages autofocus, sticky statusbar, and field ID uniqueness */

import {
    Component,
    onMounted,
    onWillUnmount,
    useEffect,
    useRef,
    useState,
    useSubEnv,
    xml,
} from "@odoo/owl";
import { Notebook } from "@web/components/notebook/notebook";
import { hasTouch } from "@web/core/browser/feature_detection";
import { AppEvent } from "@web/core/events";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { useBus, useService } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { useThrottleForAnimation } from "@web/core/utils/timing";
import { Field } from "@web/fields/field";
import { ButtonBox } from "@web/views/form/button_box/button_box";
import { InnerGroup, OuterGroup } from "@web/views/form/form_group/form_group";
import { ViewButton } from "@web/views/view_button/view_button";
import { useViewCompiler } from "@web/views/view_compiler";
import { Widget } from "@web/views/widgets/widget";

import { FormCompiler } from "./form_compiler.js";
import { FormLabel } from "./form_label.js";
import { Setting } from "./setting/setting.js";
import { StatusBarButtons } from "./status_bar_buttons/status_bar_buttons.js";

/**
 * Renderer for the form view.
 *
 * Compiles the form arch into an OWL template, manages autofocus on new
 * records, handles scroll-based sticky statusbar behavior, and ensures
 * field ID uniqueness when rendered inside a dialog.
 */
export class FormRenderer extends Component {
    static template = xml`<t t-call="{{ templates.FormRenderer }}" t-call-context="{ __comp__: Object.assign(Object.create(this), { this: this }) }" />`;
    static components = {
        Field,
        FormLabel,
        ButtonBox,
        ViewButton,
        Widget,
        Notebook,
        Setting,
        OuterGroup,
        InnerGroup,
        StatusBarButtons,
    };
    static props = {
        archInfo: Object,
        Compiler: { type: Function, optional: true },
        record: Object,
        // Template props : added by the FormCompiler
        class: { type: String, optional: 1 },
        onNotebookPageChange: { type: Function, optional: true },
        activeNotebookPages: { type: Object, optional: true },
        readonly: { type: Boolean, optional: true },
        saveRecord: { type: Function, optional: true },
        setFieldAsDirty: { type: Function, optional: true },
        slots: { type: Object, optional: true },
    };
    static defaultProps = {
        activeNotebookPages: {},
        onNotebookPageChange: () => {},
    };

    setup() {
        useRenderCounter("form.FormRenderer");
        this.evaluateBooleanExpr = evaluateBooleanExpr;
        const { archInfo, Compiler, record } = this.props;
        const templates = { FormRenderer: archInfo.xmlDoc };
        this.state = useState(/** @type {any} */ ({})); // Used by Form Compiler
        this.templates = useViewCompiler(Compiler || FormCompiler, templates);
        useSubEnv({ model: record.model });
        this.uiService = useService("ui");
        // The template only reads breakpoint-level sizes (e.g. uiService.size),
        // so re-render on breakpoint changes only, not on every resize event.
        useBus(this.uiService.bus, AppEvent.RESIZE, /** @type {any} */ (this.render));
        this.onScrollThrottled = useThrottleForAnimation(this.onScroll);

        const { autofocusFieldIds } = archInfo;
        const rootRef = useRef("compiled_view_root");
        if (this.shouldAutoFocus) {
            useEffect(
                (isNew, rootEl) => {
                    if (!rootEl) {
                        return;
                    }
                    let elementToFocus;
                    if (isNew) {
                        const focusableSelectors = [
                            'input[type="text"]',
                            "textarea",
                            "[contenteditable]",
                        ];
                        for (const id of autofocusFieldIds) {
                            elementToFocus = rootEl.querySelector(`#${id}`);
                            if (elementToFocus) {
                                break;
                            }
                        }
                        elementToFocus =
                            elementToFocus ||
                            rootEl.querySelector(
                                focusableSelectors
                                    .map((sel) => `.o_content .o_field_widget ${sel}`)
                                    .join(", "),
                            );
                    }
                    // Don't steal focus the user has already placed inside the
                    // form content — a re-render can re-fire this effect while
                    // they're typing. Same guard form_controller uses when
                    // focusing the primary button on leaving edition.
                    if (
                        elementToFocus &&
                        !rootEl
                            .querySelector(".o_content")
                            ?.contains(document.activeElement)
                    ) {
                        elementToFocus.focus();
                    }
                },
                () => [this.props.record.isNew, rootRef.el],
            );
        }

        if (this.env.inDialog) {
            // try to ensure ids unicity by temporarily removing similar ids that could already
            // exist in the DOM (e.g. in a form view displayed below this dialog which contains
            // same field names as this form view)
            const fieldNodeIds = new Set(Object.keys(this.props.archInfo.fieldNodes));
            const elementsByNodeIds = {};
            onMounted(() => {
                if (!rootRef.el) {
                    // t-ref is sometimes set on a <t> node, resulting in a null ref (e.g. footer case)
                    return;
                }
                // Single DOM pass: querying `[id=...]` once per field id would
                // rescan the whole document for each field.
                for (const el of document.querySelectorAll("[id]")) {
                    const id = el.getAttribute("id");
                    if (
                        fieldNodeIds.has(id) &&
                        !(id in elementsByNodeIds) &&
                        !rootRef.el.contains(el)
                    ) {
                        el.removeAttribute("id");
                        elementsByNodeIds[id] = el;
                    }
                }
            });
            onWillUnmount(() => {
                for (const [id, el] of Object.entries(elementsByNodeIds)) {
                    el.setAttribute("id", id);
                }
            });
        }
    }

    get shouldAutoFocus() {
        return !hasTouch() && !this.props.archInfo.disableAutofocus;
    }

    onScroll(ev) {
        this.state.isStatusbarStickyPinned =
            !this.env.inDialog && !this.env.isSmall && ev.target.scrollTop !== 0;
    }

    async onWillChangeNotebookPage(_notebookId, _page) {
        // Hack to force _askChanges
        await this.props.record.isDirty();
        // Notebook.activatePage vetoes the switch only on an explicit `false`
        // return (`canProceed !== false`); return true to allow the page change.
        return true;
    }
}
