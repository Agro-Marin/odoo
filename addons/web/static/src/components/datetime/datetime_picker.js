// @ts-check
/** @odoo-module native */

import { Component, onWillRender, onWillUpdateProps, useState } from "@odoo/owl";
import { TimePicker } from "@web/components/time_picker/time_picker";
import {
    clampDate,
    getMaxValidDate,
    getMinValidDate,
    isInRange,
    today,
} from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime, Info } from "@web/core/l10n/luxon";
import { Time } from "@web/core/l10n/time";
import { _t } from "@web/core/translation";
import { ensureArray } from "@web/core/utils/collections/arrays";

/**
 * @typedef DateItem
 * @property {string} id
 * @property {boolean} includesToday
 * @property {boolean} isOutOfRange
 * @property {boolean} isValid
 * @property {string} label
 * @property {DateRange} range
 * @property {string} extraClass
 * @typedef {"today" | NullableDateTime} DateLimit
 * @typedef {[DateTime, DateTime]} DateRange
 * @typedef DateTimePickerProps
 * @property {number} [focusedDateIndex=0]
 * @property {boolean} [showWeekNumbers=true]
 * @property {DaysOfWeekFormat} [daysOfWeekFormat="narrow"]
 * @property {DateLimit} [maxDate]
 * @property {PrecisionLevel} [maxPrecision="decades"]
 * @property {DateLimit} [minDate]
 * @property {PrecisionLevel} [minPrecision="days"]
 * @property {() => any} [onReset]
 * @property {(value: DateTime | DateRange, unit: "date" | "time") => any} [onSelect]
 * @property {() => any} [onToggleRange]
 * @property {boolean} [range]
 * @property {number} [rounding=5]
 * @property {boolean} [showRangeToggler]
 * @property {{ buttons?: any }} [slots]
 * @property {"date" | "datetime"} [type]
 * @property {NullableDateTime | NullableDateRange} [value]
 * @property {(date: DateTime) => boolean} [isDateValid]
 * @property {(date: DateTime) => string} [dayCellClass]
 * @typedef {DateItem | MonthItem} Item
 * @typedef MonthItem
 * @property {[string, string][]} daysOfWeek
 * @property {string} id
 * @property {number} number
 * @property {WeekItem[]} weeks
 * @typedef {import("@web/core/l10n/dates").NullableDateTime} NullableDateTime
 * @typedef {import("@web/core/l10n/dates").NullableDateRange} NullableDateRange
 * @typedef PrecisionInfo
 * @property {(date: DateTime, params?: Partial<DateTimePickerProps>) => string} getTitle
 * @property {(date: DateTime, params: Partial<DateTimePickerProps>) => Item[]} getItems
 * @property {string} mainTitle
 * @property {string} nextTitle
 * @property {string} prevTitle
 * @property {Record<string, number>} step
 * @typedef {"days" | "months" | "years" | "decades"} PrecisionLevel
 * @typedef {"short" | "narrow"} DaysOfWeekFormat
 * @typedef WeekItem
 * @property {DateItem[]} days
 * @property {number} number
 */

/**
 * @param {DateTime} date
 */
const getStartOfDecade = (date) => Math.floor(date.year / 10) * 10;

/**
 * @param {DateTime} date
 */
const getStartOfCentury = (date) => Math.floor(date.year / 100) * 100;

/**
 * @param {DateTime} date
 */
const getStartOfWeek = (date) => {
    const { weekStart } = localization;
    return date.set({
        weekday: /** @type {any} */ (
            date.weekday < weekStart ? weekStart - 7 : weekStart
        ),
    });
};

/**
 * @param {number} min
 * @param {number} max
 */
const numberRange = (min, max) => [...Array(max - min)].map((_, i) => i + min);

/**
 * @param {NullableDateTime | "today"} value
 * @param {NullableDateTime | "today"} defaultValue
 */
const parseLimitDate = (value, defaultValue) =>
    clampDate(
        value === "today" ? today() : value || defaultValue,
        getMinValidDate(),
        getMaxValidDate(),
    );

/**
 * `now` is passed in rather than read from `today()` here: a day grid is 42
 * cells, and `today()` is `DateTime.local().startOf("day")` — two luxon
 * objects per call, so reading it per cell allocated 84 of them to answer a
 * question that has one answer for the whole grid.
 *
 * @param {Object} params
 * @param {boolean} [params.isOutOfRange=false]
 * @param {boolean} [params.isValid=true]
 * @param {keyof DateTime} params.label
 * @param {string} [params.extraClass]
 * @param {[DateTime, DateTime]} params.range
 * @param {DateTime} params.now
 * @returns {DateItem}
 */
const toDateItem = ({
    isOutOfRange = false,
    isValid = true,
    label,
    range,
    now,
    extraClass = "",
}) => ({
    id: /** @type {string} */ (range[0].toISODate()),
    includesToday: isInRange(now, range),
    isOutOfRange,
    isValid,
    label: String(range[0][label]),
    range,
    extraClass,
});

/**
 * @param {DateItem[]} weekDayItems
 * @returns {WeekItem}
 */
const toWeekItem = (weekDayItems) => ({
    number: weekDayItems[3].range[0].weekNumber,
    days: weekDayItems,
});

/**
 * @type {Map<PrecisionLevel, PrecisionInfo>}
 */
const PRECISION_LEVELS = new Map()
    .set("days", {
        mainTitle: _t("Select month"),
        nextTitle: _t("Next month"),
        prevTitle: _t("Previous month"),
        step: { month: 1 },
        getTitle: (date) => `${date.monthLong} ${date.year}`,
        getItems: (date, { maxDate, minDate, showWeekNumbers }) => {
            const now = today();
            /** @type {DateRange} */
            const monthRange = [date.startOf("month"), date.endOf("month")];
            /** @type {WeekItem[]} */
            const weeks = [];

            let startOfNextWeek = getStartOfWeek(monthRange[0]);
            for (let w = 0; w < WEEKS_PER_MONTH; w++) {
                const weekDayItems = [];
                for (let d = 0; d < DAYS_PER_WEEK; d++) {
                    const day = startOfNextWeek.plus({ day: d });
                    /** @type {DateRange} */
                    const range = [day, day.endOf("day")];
                    const dayItem = toDateItem({
                        isOutOfRange: !isInRange(day, monthRange),
                        isValid: isInRange(range, [minDate, maxDate]),
                        label: "day",
                        range,
                        now,
                    });
                    weekDayItems.push(dayItem);
                    if (d === DAYS_PER_WEEK - 1) {
                        startOfNextWeek = day.plus({ day: 1 });
                    }
                }

                weeks.push(toWeekItem(weekDayItems));
            }

            const daysOfWeek = weeks[0].days.map((d) => [
                d.range[0].weekdayShort,
                d.range[0].weekdayLong,
                Info.weekdays("narrow", { locale: d.range[0].locale })[
                    d.range[0].weekday - 1
                ],
            ]);
            if (showWeekNumbers) {
                daysOfWeek.unshift(["", _t("Week numbers"), ""]);
            }

            return [
                {
                    id: "__month__0",
                    number: monthRange[0].month,
                    daysOfWeek,
                    weeks,
                },
            ];
        },
    })
    .set("months", {
        mainTitle: _t("Select year"),
        nextTitle: _t("Next year"),
        prevTitle: _t("Previous year"),
        step: { year: 1 },
        getTitle: (date) => String(date.year),
        getItems: (date, { maxDate, minDate }) => {
            const now = today();
            const startOfYear = date.startOf("year");
            return numberRange(0, 12).map((i) => {
                const startOfMonth = startOfYear.plus({ month: i });
                /** @type {DateRange} */
                const range = [startOfMonth, startOfMonth.endOf("month")];
                return toDateItem({
                    isValid: isInRange(range, [minDate, maxDate]),
                    label: "monthShort",
                    range,
                    now,
                });
            });
        },
    })
    .set("years", {
        mainTitle: _t("Select decade"),
        nextTitle: _t("Next decade"),
        prevTitle: _t("Previous decade"),
        step: { year: 10 },
        getTitle: (date) =>
            `${getStartOfDecade(date) - 1} - ${getStartOfDecade(date) + 10}`,
        getItems: (date, { maxDate, minDate }) => {
            const now = today();
            const startOfDecade = date
                .startOf("year")
                .set({ year: getStartOfDecade(date) });
            return numberRange(-GRID_MARGIN, GRID_COUNT + GRID_MARGIN).map((i) => {
                const startOfYear = startOfDecade.plus({ year: i });
                /** @type {DateRange} */
                const range = [startOfYear, startOfYear.endOf("year")];
                return toDateItem({
                    isOutOfRange: i < 0 || i >= GRID_COUNT,
                    isValid: isInRange(range, [minDate, maxDate]),
                    label: "year",
                    range,
                    now,
                });
            });
        },
    })
    .set("decades", {
        mainTitle: _t("Select century"),
        nextTitle: _t("Next century"),
        prevTitle: _t("Previous century"),
        step: { year: 100 },
        getTitle: (date) =>
            `${getStartOfCentury(date) - 10} - ${getStartOfCentury(date) + 100}`,
        getItems: (date, { maxDate, minDate }) => {
            const now = today();
            const startOfCentury = date
                .startOf("year")
                .set({ year: getStartOfCentury(date) });
            return numberRange(-GRID_MARGIN, GRID_COUNT + GRID_MARGIN).map((i) => {
                const startOfDecade = startOfCentury.plus({ year: i * 10 });
                /** @type {DateRange} */
                const range = [
                    startOfDecade,
                    startOfDecade.plus({ year: 10, millisecond: -1 }),
                ];
                return toDateItem({
                    label: "year",
                    isOutOfRange: i < 0 || i >= GRID_COUNT,
                    isValid: isInRange(range, [minDate, maxDate]),
                    range,
                    now,
                });
            });
        },
    });

const GRID_COUNT = 10;
const GRID_MARGIN = 1;
const NULLABLE_DATETIME_PROPERTY = [DateTime, { value: false }, { value: null }];

const DAYS_PER_WEEK = 7;
const WEEKS_PER_MONTH = 6;

/** @extends {Component<DateTimePickerProps>} */
export class DateTimePicker extends Component {
    static props = {
        focusedDateIndex: { type: Number, optional: true },
        showWeekNumbers: { type: Boolean, optional: true },
        daysOfWeekFormat: { type: String, optional: true },
        maxDate: {
            type: [NULLABLE_DATETIME_PROPERTY, { value: "today" }],
            optional: true,
        },
        maxPrecision: {
            type: [...PRECISION_LEVELS.keys()].map((value) => ({ value })),
            optional: true,
        },
        minDate: {
            type: [NULLABLE_DATETIME_PROPERTY, { value: "today" }],
            optional: true,
        },
        minPrecision: {
            type: [...PRECISION_LEVELS.keys()].map((value) => ({ value })),
            optional: true,
        },
        onReset: { type: Function, optional: true },
        onSelect: { type: Function, optional: true },
        onToggleRange: { type: Function, optional: true },
        range: { type: Boolean, optional: true },
        rounding: { type: Number, optional: true },
        showRangeToggler: { type: Boolean, optional: true },
        slots: {
            type: Object,
            shape: { buttons: { type: Object, optional: true } },
            optional: true,
        },
        type: {
            type: [{ value: "date" }, { value: "datetime" }],
            optional: true,
        },
        value: {
            type: [
                NULLABLE_DATETIME_PROPERTY,
                { type: Array, element: NULLABLE_DATETIME_PROPERTY },
            ],
            optional: true,
        },
        isDateValid: { type: Function, optional: true },
        dayCellClass: { type: Function, optional: true },
    };

    static defaultProps = {
        focusedDateIndex: 0,
        daysOfWeekFormat: "narrow",
        maxPrecision: "decades",
        minPrecision: "days",
        rounding: 5,
        showWeekNumbers: true,
        type: "datetime",
    };

    static template = "web.DateTimePicker";
    static components = { TimePicker };

    get activePrecisionLevel() {
        return PRECISION_LEVELS.get(this.state.precision);
    }

    get isLastPrecisionLevel() {
        return this.allowedPrecisionLevels.at(-1) === this.state.precision;
    }

    get titles() {
        return ensureArray(this.title);
    }

    setup() {
        /** @type {PrecisionLevel[]} */
        this.allowedPrecisionLevels = [];
        /** @type {Item[]} */
        this.items = [];
        /**
         * The undecorated grid `decorateGrid` reads from — memoised by
         * `_gridKey`, and never handed to the template directly.
         * @type {Item[]}
         */
        this._grid = [];
        this.title = "";
        this.shouldAdjustFocusDate = false;

        this.state = useState({
            /** @type {DateTime | null} */
            focusDate: null,
            /** @type {DateTime | null} */
            hoveredDate: null,
            /** @type {Time[]} */
            timeValues: [],
            /** @type {PrecisionLevel} */
            precision: this.props.minPrecision,
        });

        this.onPropsUpdated(this.props);
        onWillUpdateProps((nextProps) => this.onPropsUpdated(nextProps));

        onWillRender(() => this.onWillRender());
    }

    /**
     * @param {DateTimePickerProps} props
     */
    onPropsUpdated(props) {
        const previousValues = this.values;
        this.values = /** @type {[NullableDateTime] | NullableDateRange} */ (
            ensureArray(props.value).map((value) =>
                value && !value.isValid ? null : value,
            )
        );
        this.allowedPrecisionLevels = this.filterPrecisionLevels(
            props.minPrecision,
            props.maxPrecision,
        );

        this.maxDate = parseLimitDate(props.maxDate, getMaxValidDate());
        this.minDate = parseLimitDate(props.minDate, getMinValidDate());
        if (props.type === "date") {
            this.maxDate = this.maxDate.endOf("day");
            this.minDate = this.minDate.startOf("day");
        }

        if (this.maxDate < this.minDate) {
            console.error(
                `DateTimePicker: given "maxDate" (${this.maxDate.toISO()}) comes before ` +
                    `"minDate" (${this.minDate.toISO()}); no date can be selected.`,
            );
        }

        this.state.timeValues = this.getTimeValues(props);
        this.shouldAdjustFocusDate = !props.range && this.hasValueMoved(previousValues);
        this.adjustFocus(this.values, props.focusedDateIndex);
    }

    /**
     * @param {NullableDateTime[]} [previousValues]
     * @returns {boolean}
     */
    hasValueMoved(previousValues) {
        if (!previousValues || previousValues.length !== this.values.length) {
            return true;
        }
        return this.values.some((value, index) => {
            const previous = previousValues[index];
            if (!value || !previous) {
                return Boolean(value) !== Boolean(previous);
            }
            return !value.equals(previous);
        });
    }

    onWillRender() {
        const { focusedDateIndex, range, showWeekNumbers } = this.props;
        const { focusDate, hoveredDate } = this.state;
        const precision = this.activePrecisionLevel;
        const effShowWeekNumbers = showWeekNumbers ?? !range;

        const gridKey = [
            focusDate?.ts,
            precision,
            this.minDate?.ts,
            this.maxDate?.ts,
            effShowWeekNumbers,
            today().ts,
        ];
        if (
            !this._gridKey ||
            gridKey.some((value, index) => value !== this._gridKey[index])
        ) {
            this._gridKey = gridKey;
            this.title = precision.getTitle(focusDate);
            this._grid = precision.getItems(focusDate, {
                maxDate: this.maxDate,
                minDate: this.minDate,
                showWeekNumbers: effShowWeekNumbers,
            });
        }
        this.items = this.decorateGrid(this._grid);

        this.selectedRange = [...this.values];
        if (
            range &&
            focusedDateIndex > 0 &&
            (!this.values[1] || hoveredDate > this.values[0])
        ) {
            this.selectedRange[1] = hoveredDate;
        }
    }

    /**
     * `isDateValid` and `dayCellClass` are answers, not identities: a consumer
     * passes a closure over state the picker cannot see, so the same function
     * can answer differently on two consecutive renders and no key over the
     * props can tell. That is why they used to defeat the grid memo outright —
     * and a range picker sets `hoveredDate` on every `pointerenter`, so moving
     * the mouse across a month rebuilt 42 cells, each allocating a luxon
     * `endOf("day")`, a `today()` and a `toISODate()` string, 0.33ms a cell
     * sweep against 0.002ms for the decoration alone (measured on this repo's
     * luxon under node 26, 2000 iterations).
     *
     * The split keeps both properties: the *skeleton* — ranges, labels,
     * in-month and in-limits — depends only on what `_gridKey` covers and is
     * built once; the two answers are re-asked every render, on a copy, so the
     * cached skeleton is never poisoned by a decoration.
     *
     * Only the day grid is decorated. `months`, `years` and `decades` never
     * consumed either callback, and passing them through here would newly
     * disable month cells that used to stay clickable.
     *
     * @param {Item[]} grid
     * @returns {Item[]}
     */
    decorateGrid(grid) {
        const { dayCellClass, isDateValid } = this.props;
        if (!isDateValid && !dayCellClass) {
            return grid;
        }
        return grid.map((item) => {
            const weeks = /** @type {MonthItem} */ (item).weeks;
            if (!weeks) {
                return item;
            }
            return {
                .../** @type {MonthItem} */ (item),
                weeks: weeks.map((week) => ({
                    ...week,
                    days: week.days.map((day) => {
                        const date = day.range[0];
                        return {
                            ...day,
                            isValid: day.isValid && (isDateValid?.(date) ?? true),
                            extraClass: dayCellClass?.(date) || "",
                        };
                    }),
                })),
            };
        });
    }

    /**
     * @param {NullableDateTime[]} values
     * @param {number} focusedDateIndex
     */
    adjustFocus(values, focusedDateIndex) {
        if (!this.shouldAdjustFocusDate && this.state.focusDate) {
            return;
        }

        const dateToFocus =
            values[focusedDateIndex] ||
            values[focusedDateIndex === 1 ? 0 : 1] ||
            today();

        this.shouldAdjustFocusDate = false;
        this.state.focusDate = this.clamp(dateToFocus.startOf("month"));
    }

    /**
     * @param {DateTime} value
     */
    clamp(value) {
        return clampDate(value, this.minDate, this.maxDate);
    }

    /**
     * @param {PrecisionLevel} minPrecision
     * @param {PrecisionLevel} maxPrecision
     */
    filterPrecisionLevels(minPrecision, maxPrecision) {
        const levels = [...PRECISION_LEVELS.keys()];
        return levels.slice(
            levels.indexOf(minPrecision),
            levels.indexOf(maxPrecision) + 1,
        );
    }

    /**
     * @param {DateItem} item
     */
    getActiveRangeInfo({ range }) {
        const result = {
            isSelected: isInRange(this.selectedRange, range),
            isSelectStart: false,
            isSelectEnd: false,
            isHighlighted: isInRange(this.state.hoveredDate, range),
        };

        if (this.props.range) {
            if (result.isSelected) {
                const [selectStart, selectEnd] = this.selectedRange.toSorted(
                    (a, b) => (a ? a.ts : -Infinity) - (b ? b.ts : -Infinity),
                );
                result.isSelectStart = !selectStart || isInRange(selectStart, range);
                result.isSelectEnd = !selectEnd || isInRange(selectEnd, range);
            }
        } else {
            result.isSelectStart = result.isSelectEnd = result.isSelected;
        }

        return result;
    }

    /**
     * @param {DateTimePickerProps} props
     */
    getTimeValues(props) {
        const timeValues = this.values.map((val, index) => {
            const isImplicitEnd = index === 1 && !this.values[1];
            const reference =
                val || (isImplicitEnd && this.values[0]) || DateTime.local();
            return new Time({
                hour: isImplicitEnd ? Math.min(reference.hour + 1, 23) : reference.hour,
                minute: val ? val.minute : 0,
                second: val ? val.second : 0,
            });
        });

        if (props.range) {
            return timeValues;
        } else {
            const values = [];
            values[props.focusedDateIndex] = timeValues[props.focusedDateIndex];
            return values;
        }
    }

    /**
     * @param {DateItem} item
     */
    isSelectedDate({ range }) {
        return this.values.some((value) => isInRange(value, range));
    }

    /**
     * @param {PointerEvent} ev
     */
    next(ev) {
        ev.preventDefault();
        const { step } = this.activePrecisionLevel;
        this.state.focusDate = this.clamp(this.state.focusDate.plus(step));
    }

    /**
     * @param {PointerEvent} ev
     */
    previous(ev) {
        ev.preventDefault();
        const { step } = this.activePrecisionLevel;
        this.state.focusDate = this.clamp(this.state.focusDate.minus(step));
    }

    /**
     * @param {number} valueIndex
     * @param {Time} newTime
     */
    onTimeChange(valueIndex, newTime) {
        this.state.timeValues[valueIndex] = newTime;
        const value = this.values[valueIndex] || today();
        this.validateAndSelect(value, valueIndex, "time");
    }

    /**
     * @param {DateTime} value
     * @param {number} valueIndex
     * @param {"date" | "time"} unit
     */
    validateAndSelect(value, valueIndex, unit) {
        if (!this.props.onSelect) {
            return false;
        }

        const result = [...this.values];
        result[valueIndex] = value;

        if (this.props.type === "datetime") {
            const { hour, minute, second } = this.state.timeValues[valueIndex];
            result[valueIndex] = result[valueIndex].set({
                hour,
                minute,
                second,
            });
        }
        if (!isInRange(result[valueIndex], [this.minDate, this.maxDate])) {
            return false;
        }
        this.props.onSelect(result.length === 2 ? result : result[0], unit);
        return true;
    }

    /**
     * @param {DateTime} date
     */
    zoomIn(date) {
        const index = this.allowedPrecisionLevels.indexOf(this.state.precision) - 1;
        if (index in this.allowedPrecisionLevels) {
            this.state.focusDate = this.clamp(date);
            this.state.precision = this.allowedPrecisionLevels[index];
            return true;
        }
        return false;
    }

    zoomOut() {
        const index = this.allowedPrecisionLevels.indexOf(this.state.precision) + 1;
        if (index in this.allowedPrecisionLevels) {
            this.state.precision = this.allowedPrecisionLevels[index];
            return true;
        }
        return false;
    }

    /**
     * @param {DateItem} dateItem
     */
    zoomOrSelect(dateItem) {
        if (!dateItem.isValid) {
            return;
        }
        if (this.zoomIn(dateItem.range[0])) {
            return;
        }
        const [value] = dateItem.range;
        const valueIndex = this.props.focusedDateIndex;
        this.validateAndSelect(value, valueIndex, "date");
    }
}
