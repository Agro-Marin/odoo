// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_controller - Calendar view orchestrator: date navigation, event CRUD, quick-create, and multi-selection */

import { Component, reactive, useState } from "@odoo/owl";
import { CallbackRecorder, useSetupAction } from "@web/core/action_hook";
import { browser } from "@web/core/browser/browser";
import { ModelEvent } from "@web/core/events";
import { getLocalYearAndWeek } from "@web/core/l10n/dates";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";
import { useBus, useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { useModelWithSampleData } from "@web/model/model";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import {
    ConfirmationDialog,
    deleteConfirmationMessage,
} from "@web/ui/dialog/confirmation_dialog";
import { CalendarSidePanel } from "@web/views/calendar/calendar_side_panel/calendar_side_panel";
import { standardViewProps } from "@web/views/standard_view_props";
import { MultiSelectionButtons } from "@web/views/view_components/multi_selection_buttons";
import { ViewScaleSelector } from "@web/views/view_components/view_scale_selector";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

import { CalendarMobileFilterPanel } from "./mobile_filter_panel/calendar_mobile_filter_panel.js";
import { CalendarQuickCreate } from "./quick_create/calendar_quick_create.js";

export const SCALE_LABELS = {
    day: _t("Day"),
    week: _t("Week"),
    month: _t("Month"),
    year: _t("Year"),
};

/** Dialog hook that auto-closes the previous dialog when opening a new one. */
function useUniqueDialog() {
    const displayDialog = useOwnedDialogs();
    let close = null;
    return (...args) => {
        if (close) {
            close();
        }
        close = displayDialog(...args);
    };
}

/** Orchestrates the model, renderer, side panel, search bar, and scale selector. */
export class CalendarController extends Component {
    static components = {
        MobileFilterPanel: CalendarMobileFilterPanel,
        QuickCreate: CalendarQuickCreate,
        QuickCreateFormView: FormViewDialog,
        Layout,
        SearchBar,
        ViewScaleSelector,
        CogMenu,
        CalendarSidePanel,
        MultiSelectionButtons,
    };
    static template = "web.CalendarController";
    static props = {
        ...standardViewProps,
        Model: Function,
        Renderer: Function,
        archInfo: Object,
        buttonTemplate: String,
        itemCalendarProps: { type: Object, optional: true },
    };

    /** @type {any} */
    action;
    /** @type {any} */
    displayDialog;
    /** @type {any} */
    model;
    /** @type {any} */
    state;
    /** @type {any} */
    _baseRendererProps;
    /** @type {any} */
    multiSelectionButtonsReactive;
    /** @type {any} */
    callbackRecorder;

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.displayDialog = useUniqueDialog();

        /** @type {any} */
        this.model = useState(
            useModelWithSampleData(this.props.Model, this.modelParams),
        );

        useSetupAction({
            getLocalState: () => this.model.exportedState,
        });

        // Both flags are boolean-only, persisted via String(value). Reading back with
        // JSON.parse is brittle (a stray "undefined" string throws), so check
        // whether the stored value is the string "false".
        const storedWeekendVisible = browser.localStorage.getItem(
            "calendar.isWeekendVisible",
        );
        const sessionShowSidebar =
            browser.sessionStorage.getItem("calendar.showSideBar");
        this.state = useState({
            isWeekendVisible:
                storedWeekendVisible !== "false" &&
                /** @type {any} */ (storedWeekendVisible) !== false,
            showSideBar:
                !this.env.isSmall &&
                sessionShowSidebar !== "false" &&
                /** @type {any} */ (sessionShowSidebar) !== false,
        });

        this.searchBarToggler = useSearchBarToggler();

        this._baseRendererProps = {
            createRecord: this.createRecord.bind(this),
            deleteRecord: this.deleteRecord.bind(this),
            editRecord: this.editRecord.bind(this),
            setDate: this.setDate.bind(this),
        };

        this.prepareSelectionFeature();
    }

    get modelParams() {
        return {
            ...this.props.archInfo,
            resModel: this.props.resModel,
            domain: this.props.domain,
            fields: this.props.fields,
            date: this.props.state?.date,
        };
    }

    get date() {
        return this.model.meta.date || DateTime.now();
    }

    get today() {
        return DateTime.now().toFormat("d");
    }

    get currentYear() {
        return this.date.toFormat("y");
    }

    get dayHeader() {
        return `${this.date.toFormat("d")} ${this.date.toFormat("MMMM")} ${this.date.year}`;
    }

    get weekHeader() {
        const { rangeStart, rangeEnd } = this.model;
        if (rangeStart.year !== rangeEnd.year) {
            return `${rangeStart.toFormat("MMMM")} ${rangeStart.year} - ${rangeEnd.toFormat(
                "MMMM",
            )} ${rangeEnd.year}`;
        } else if (rangeStart.month !== rangeEnd.month) {
            return `${rangeStart.toFormat("MMMM")} - ${rangeEnd.toFormat("MMMM")} ${
                rangeStart.year
            }`;
        }
        return `${rangeStart.toFormat("MMMM")} ${rangeStart.year}`;
    }

    get currentMonth() {
        return `${this.date.toFormat("MMMM")} ${this.date.year}`;
    }

    get currentWeek() {
        return getLocalYearAndWeek(this.model.rangeStart).week;
    }

    get rendererProps() {
        return {
            ...this._baseRendererProps,
            model: this.model,
            isWeekendVisible: this.model.scale === "day" || this.state.isWeekendVisible,
        };
    }

    get mobileFilterPanelProps() {
        return {
            model: this.model,
            sideBarShown: this.state.showSideBar,
            toggleSideBar: () => {
                this.state.showSideBar = !this.state.showSideBar;
            },
        };
    }

    get sidePanelProps() {
        return { model: this.model };
    }

    toggleSideBar() {
        this.state.showSideBar = !this.state.showSideBar;
        browser.sessionStorage.setItem(
            "calendar.showSideBar",
            String(this.state.showSideBar),
        );
    }

    get showCalendar() {
        return !this.env.isSmall || !this.state.showSideBar;
    }

    get hasSideBar() {
        return this.model.showDatePicker || this.model.filterSections.length > 0;
    }

    get showSideBar() {
        return this.state.showSideBar;
    }

    get className() {
        return this.props.className;
    }

    get editRecordDefaultDisplayText() {
        return _t("New Event");
    }

    prepareMultiSelectionButtonsReactive() {
        return reactive({
            onCancel: this.cleanSquareSelection.bind(this),
            onAdd: (multiCreateData) => {
                this.onMultiCreate(multiCreateData, this.selectedCells);
                this.cleanSquareSelection();
            },
            onDelete: () => {
                this.onMultiDelete(this.selectedCells);
                this.cleanSquareSelection();
            },
            nbSelected: 0,
            multiCreateView: this.model.meta.multiCreateView || "",
            resModel: this.model.meta.resModel,
            multiCreateValues: this.props.state?.multiCreateValues,
            showMultiCreateTimeRange: this.model.showMultiCreateTimeRange,
            visible: false,
            context: this.props.context,
        });
    }

    prepareSelectionFeature() {
        this.selectedCells = null;
        this.multiSelectionButtonsReactive =
            this.prepareMultiSelectionButtonsReactive();
        this.callbackRecorder = new CallbackRecorder();
        this._baseRendererProps.callbackRecorder = this.callbackRecorder;
        this._baseRendererProps.onSquareSelection =
            this.updateMultiSelection.bind(this);
        this._baseRendererProps.cleanSquareSelection =
            this.cleanSquareSelection.bind(this);

        useBus(this.model.bus, ModelEvent.UPDATE, this.cleanSquareSelection.bind(this));
    }

    updateMultiSelection(selectedCells) {
        if (selectedCells.length) {
            this.selectedCells = selectedCells;
            this.multiSelectionButtonsReactive.visible = true;
            this.multiSelectionButtonsReactive.nbSelected = this.getSelectedRecordIds(
                this.selectedCells,
            ).length;
        } else {
            this.selectedCells = null;
            this.multiSelectionButtonsReactive.visible = false;
            this.multiSelectionButtonsReactive.nbSelected = 0;
        }
    }

    cleanSquareSelection() {
        this.selectedCells = null;
        this.multiSelectionButtonsReactive.visible = false;
        this.callbackRecorder.callbacks.forEach((fn) => fn());
    }

    getQuickCreateProps(record) {
        return {
            record,
            model: this.model,
            editRecord: this.editRecordInCreation.bind(this),
            title: this.props.context.default_name,
        };
    }

    getQuickCreateFormViewProps(record) {
        const rawRecord = this.model.buildRawRecord(record);
        const context = this.model.makeContextDefaults(rawRecord);
        return {
            resModel: this.model.resModel,
            viewId: this.model.quickCreateFormViewId,
            title: _t("New Event"),
            context,
        };
    }

    /**
     * Create a new record via quick-create dialog, form dialog, or full form view.
     *
     * @param {Object} record - partial record with start, end, isAllDay
     * @returns {Promise|undefined}
     */
    createRecord(record) {
        if (!this.model.canCreate) {
            return;
        }
        if (this.model.hasQuickCreate) {
            if (this.model.quickCreateFormViewId) {
                return new Promise((resolve) => {
                    this.displayDialog(
                        /** @type {any} */ (this.constructor).components
                            .QuickCreateFormView,
                        this.getQuickCreateFormViewProps(record),
                        {
                            onClose: () => resolve(undefined),
                        },
                    );
                });
            }

            return new Promise((resolve) => {
                this.displayDialog(
                    /** @type {any} */ (this.constructor).components.QuickCreate,
                    this.getQuickCreateProps(record),
                    {
                        onClose: () => resolve(undefined),
                    },
                );
            });
        } else {
            return this.editRecordInCreation(record);
        }
    }
    /**
     * Open a record for editing in a dialog or navigate to the form view.
     *
     * @param {Object} record - record to edit (must have id for existing records)
     * @param {Object} [context={}] - additional context for the form view
     */
    async editRecord(record, context = {}) {
        if (this.model.hasEditDialog) {
            return new Promise((resolve) => {
                this.displayDialog(
                    FormViewDialog,
                    {
                        resModel: this.model.resModel,
                        resId: record.id || false,
                        context,
                        title: record.id
                            ? _t("Open: %s", record.title)
                            : this.editRecordDefaultDisplayText,
                        viewId: this.model.formViewId,
                        onRecordSaved: () => this.model.load(),
                    },
                    { onClose: () => resolve(undefined) },
                );
            });
        } else {
            const action = {
                type: "ir.actions.act_window",
                res_model: this.model.resModel,
                views: [[this.model.formViewId || false, "form"]],
                target: "current",
                context,
            };
            if (record.id) {
                action.res_id = record.id;
            }
            this.action.doAction(action);
        }
    }
    editRecordInCreation(record) {
        const rawRecord = this.model.buildRawRecord(record);
        const context = this.model.makeContextDefaults(rawRecord);
        return this.editRecord(record, context);
    }

    deleteConfirmationDialogProps(record) {
        return {
            title: _t("Bye-bye, record!"),
            body: deleteConfirmationMessage,
            confirm: () => {
                this.model.unlinkRecord(record.id);
            },
            confirmLabel: _t("Delete"),
            cancel: () => {
                // `ConfirmationDialog` needs this prop to show the cancel button.
            },
            cancelLabel: _t("No, keep it"),
        };
    }

    deleteRecord(record) {
        this.displayDialog(
            ConfirmationDialog,
            this.deleteConfirmationDialogProps(record),
        );
    }

    getDates(selectedCells) {
        const dates = [];
        for (const element of selectedCells) {
            const date = DateTime.fromISO(element.dataset.date);
            if (!(/** @type {any} */ (date).invalid)) {
                dates.push(date);
            }
        }
        return dates;
    }

    onMultiCreate(multiCreateData, selectedCells) {
        const dates = this.getDates(selectedCells);
        return this.model.multiCreateRecords(multiCreateData, dates);
    }

    getSelectedRecordIds(selectedCells) {
        const ids = new Set();
        for (const element of selectedCells) {
            for (const event of [...element.querySelectorAll(".fc-event")]) {
                // A multi-day event renders one .fc-event segment per day cell it
                // spans, so the same record id appears in several selected cells —
                // dedupe so the count (nbSelected) and unlink are per-record.
                ids.add(Number.parseInt(event.dataset.eventId, 10));
            }
        }
        return [...ids];
    }

    onMultiDelete(selectedCells) {
        const ids = this.getSelectedRecordIds(selectedCells);
        return this.model.unlinkRecords(ids);
    }

    /**
     * Navigate the calendar to a different date.
     *
     * @param {"next"|"previous"|"today"} move - navigation direction
     */
    async setDate(move) {
        let date = null;
        let scrollToCurrentHour = false;
        switch (move) {
            case "next":
                date = this.model.date.plus({ [`${this.model.scale}s`]: 1 });
                break;
            case "previous":
                date = this.model.date.minus({ [`${this.model.scale}s`]: 1 });
                break;
            case "today":
                date = DateTime.local().startOf("day");
                scrollToCurrentHour =
                    /** @type {any} */ (date).ts === this.date.startOf("day").ts;
                break;
        }
        await this.model.load({ date });
        // ``load`` triggers an OWL patch that calls FullCalendar's ``gotoDate``, which
        // resets the timegrid scroll to ``scrollTime`` — clobbering an event fired before
        // load. Trigger AFTER load so the renderer's listener runs after the reset.
        if (scrollToCurrentHour) {
            this.model.bus.trigger(ModelEvent.SCROLL_TO_CURRENT_HOUR, false);
        }
    }

    get scales() {
        return Object.fromEntries(
            this.model.scales.map((s) => [s, { description: SCALE_LABELS[s] }]),
        );
    }

    async setScale(scale) {
        await this.model.load({ scale });
    }

    toggleWeekendVisibility() {
        this.state.isWeekendVisible = !this.state.isWeekendVisible;
        browser.localStorage.setItem(
            "calendar.isWeekendVisible",
            String(this.state.isWeekendVisible),
        );
    }
}
