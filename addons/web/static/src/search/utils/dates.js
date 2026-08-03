// @ts-check
/** @odoo-module native */

/** @module @web/search/utils/dates */

import { Domain } from "@web/core/domain";
import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/translation";
import { pick } from "@web/core/utils/collections/objects";
import { clamp } from "@web/core/utils/format/numbers";
const QUARTERS = {
    1: { description: _t("Q1"), coveredMonths: [1, 2, 3] },
    2: { description: _t("Q2"), coveredMonths: [4, 5, 6] },
    3: { description: _t("Q3"), coveredMonths: [7, 8, 9] },
    4: { description: _t("Q4"), coveredMonths: [10, 11, 12] },
};

const QUARTER_OPTIONS = {
    fourth_quarter: {
        id: "fourth_quarter",
        groupNumber: 1,
        description: QUARTERS[4].description,
        setParam: { quarter: 4 },
        granularity: "quarter",
    },
    third_quarter: {
        id: "third_quarter",
        groupNumber: 1,
        description: QUARTERS[3].description,
        setParam: { quarter: 3 },
        granularity: "quarter",
    },
    second_quarter: {
        id: "second_quarter",
        groupNumber: 1,
        description: QUARTERS[2].description,
        setParam: { quarter: 2 },
        granularity: "quarter",
    },
    first_quarter: {
        id: "first_quarter",
        groupNumber: 1,
        description: QUARTERS[1].description,
        setParam: { quarter: 1 },
        granularity: "quarter",
    },
};

export const DEFAULT_INTERVAL = "month";

export const INTERVAL_OPTIONS = {
    year: { description: _t("Year"), id: "year", groupNumber: 1 },
    quarter: { description: _t("Quarter"), id: "quarter", groupNumber: 1 },
    month: { description: _t("Month"), id: "month", groupNumber: 1 },
    week: { description: _t("Week"), id: "week", groupNumber: 1 },
    day: { description: _t("Day"), id: "day", groupNumber: 1 },
};

export const BACKEND_INTERVAL_OPTIONS = {
    ...INTERVAL_OPTIONS,
    hour: { description: _t("Hour"), id: "hour" },
};

export function constructDateDomain(referenceMoment, searchItem, selectedOptionIds) {
    const selectedOptions = getSelectedOptions(
        referenceMoment,
        searchItem,
        selectedOptionIds,
    );
    if ("withDomain" in selectedOptions) {
        const customOptions = /** @type {any[]} */ (selectedOptions.withDomain);
        return {
            description: customOptions.map((o) => o.description).join("/"),
            domain: Domain.and([
                Domain.or(customOptions.map((o) => o.domain)),
                searchItem.domain,
            ]),
        };
    }
    const yearOptions = selectedOptions.year;
    const otherOptions = [
        ...(selectedOptions.quarter || []),
        ...(selectedOptions.month || []),
    ];
    if (!yearOptions.length && otherOptions.length) {
        console.warn(
            `[search] date filter "${
                searchItem.description || searchItem.fieldName
            }": period options selected without a year; the resulting domain matches all records.`,
        );
    }
    sortPeriodOptions(yearOptions);
    sortPeriodOptions(otherOptions);
    const ranges = [];
    const { fieldName, fieldType } = searchItem;
    for (const yearOption of yearOptions) {
        const constructRangeParams = {
            referenceMoment,
            fieldName,
            fieldType,
        };
        if (otherOptions.length) {
            for (const option of otherOptions) {
                const setParam = Object.assign(
                    {},
                    yearOption.setParam,
                    option ? option.setParam : {},
                );
                const { granularity } = option;
                const range = constructDateRange(
                    Object.assign({ granularity, setParam }, constructRangeParams),
                );
                ranges.push(range);
            }
        } else {
            const { granularity, setParam } = yearOption;
            const range = constructDateRange(
                Object.assign({ granularity, setParam }, constructRangeParams),
            );
            ranges.push(range);
        }
    }
    let domain = Domain.combine(
        ranges.map((range) => range.domain),
        "OR",
    );
    domain = Domain.and([domain, searchItem.domain]);
    const description = ranges.map((range) => range.description).join("/");
    return { domain, description };
}

export function constructDateRange(params) {
    const { referenceMoment, fieldName, fieldType, granularity, plusParam } = params;
    const setParam = { ...params.setParam };
    if ("quarter" in setParam) {
        setParam.month = QUARTERS[setParam.quarter].coveredMonths[0];
        delete setParam.quarter;
    }
    const date = referenceMoment.set(setParam).plus(plusParam || {});
    const leftDate = date.startOf(granularity);
    const rightDate = date.endOf(granularity);
    let leftBound;
    let rightBound;
    if (fieldType === "date") {
        leftBound = serializeDate(leftDate);
        rightBound = serializeDate(rightDate);
    } else {
        leftBound = serializeDateTime(leftDate);
        rightBound = serializeDateTime(rightDate);
    }
    const domain = new Domain([
        "&",
        [fieldName, ">=", leftBound],
        [fieldName, "<=", rightBound],
    ]);
    const descriptions = [date.toFormat("yyyy")];
    const method = localization.direction === "rtl" ? "push" : "unshift";
    if (granularity === "month") {
        descriptions[method](date.toFormat("MMMM"));
    } else if (granularity === "quarter") {
        const quarter = date.quarter;
        descriptions[method](QUARTERS[quarter].description.toString());
    }
    const description = descriptions.join(" ");
    return { domain, description };
}

/**
 * @see getOptionsWithDescriptions
 */
export function getIntervalOptions() {
    return getOptionsWithDescriptions(INTERVAL_OPTIONS);
}

/**
 * @param {object} OPTIONS
 * @returns {object[]}
 */
export function getOptionsWithDescriptions(OPTIONS) {
    const options = [];
    for (const option of Object.values(OPTIONS)) {
        options.push({
            ...option,
            description: option.description.toString(),
        });
    }
    return options;
}

export function getPeriodOptions(referenceMoment, optionsParams) {
    return [
        ...getMonthPeriodOptions(referenceMoment, optionsParams),
        ...getQuarterPeriodOptions(optionsParams),
        ...getYearPeriodOptions(referenceMoment, optionsParams),
        ...getCustomPeriodOptions(optionsParams),
    ];
}

/**
 * @param {string} unit
 * @param {number} [offset=0]
 * @returns {string}
 */
export function toGeneratorId(unit, offset) {
    if (!offset) {
        return unit;
    }
    const sep = offset > 0 ? "+" : "-";
    const val = Math.abs(offset);
    return `${unit}${sep}${val}`;
}

/**
 * @param {any} referenceMoment
 * @param {{ startYear: number, endYear: number, startMonth: number, endMonth: number }} optionsParams
 * @returns {Array<Object>}
 */
export function getMonthPeriodOptions(referenceMoment, optionsParams) {
    const { startYear, endYear, startMonth, endMonth } = optionsParams;
    return [...Array(endMonth - startMonth + 1).keys()]
        .map((i) => {
            const monthOffset = startMonth + i;
            const date = referenceMoment.plus({
                months: monthOffset,
                years: clamp(0, startYear, endYear),
            });
            const yearOffset = date.year - referenceMoment.year;
            return {
                id: toGeneratorId("month", monthOffset),
                defaultYearId: toGeneratorId(
                    "year",
                    clamp(yearOffset, startYear, endYear),
                ),
                description: date.toFormat("MMMM"),
                granularity: "month",
                groupNumber: 1,
                plusParam: { months: monthOffset },
            };
        })
        .reverse();
}

/**
 * @param {{ startYear: number, endYear: number }} optionsParams
 * @returns {Array<Object>}
 */
function getQuarterPeriodOptions(optionsParams) {
    const { startYear, endYear } = optionsParams;
    const defaultYearId = toGeneratorId("year", clamp(0, startYear, endYear));
    return Object.values(QUARTER_OPTIONS).map((quarter) => ({
        ...quarter,
        defaultYearId,
    }));
}

/**
 * @param {any} referenceMoment
 * @param {{ startYear: number, endYear: number }} optionsParams
 * @returns {Array<Object>}
 */
function getYearPeriodOptions(referenceMoment, optionsParams) {
    const { startYear, endYear } = optionsParams;
    return [...Array(endYear - startYear + 1).keys()]
        .map((i) => {
            const offset = startYear + i;
            const date = referenceMoment.plus({ years: offset });
            return {
                id: toGeneratorId("year", offset),
                description: date.toFormat("yyyy"),
                granularity: "year",
                groupNumber: 2,
                plusParam: { years: offset },
            };
        })
        .reverse();
}

/**
 * @param {{ customOptions: Array<{id: string, description: string, domain: string}> }} optionsParams
 * @returns {Array<Object>}
 */
function getCustomPeriodOptions(optionsParams) {
    const { customOptions } = optionsParams;
    return customOptions.map((option) => ({
        id: option.id,
        description: option.description,
        granularity: "withDomain",
        groupNumber: 3,
        domain: option.domain,
    }));
}

export function getSelectedOptions(referenceMoment, searchItem, selectedOptionIds) {
    const selectedOptions = { year: [] };
    const periodOptions = getPeriodOptions(referenceMoment, searchItem.optionsParams);
    for (const optionId of selectedOptionIds) {
        const option = periodOptions.find((option) => option.id === optionId);
        if (!option) {
            continue;
        }
        const granularity = option.granularity;
        if (!selectedOptions[granularity]) {
            selectedOptions[granularity] = [];
        }
        if (option.domain) {
            selectedOptions[granularity].push(pick(option, "domain", "description"));
        } else {
            const setParam = getSetParam(option, referenceMoment);
            selectedOptions[granularity].push({ granularity, setParam });
        }
    }
    return selectedOptions;
}

export function getSetParam(periodOption, referenceMoment) {
    if (periodOption.granularity === "quarter") {
        return periodOption.setParam;
    }
    const date = referenceMoment.plus(periodOption.plusParam);
    const granularity = periodOption.granularity;
    const setParam = { [granularity]: date[granularity] };
    return setParam;
}

/**
 * @param {string} intervalOptionId
 * @returns {number}
 */
export function rankInterval(intervalOptionId) {
    return Object.keys(BACKEND_INTERVAL_OPTIONS).indexOf(intervalOptionId);
}

export function sortPeriodOptions(options) {
    options.sort((o1, o2) => {
        const granularity1 = o1.granularity;
        const granularity2 = o2.granularity;
        if (granularity1 === granularity2) {
            return (o1.setParam[granularity1] ?? 0) - (o2.setParam[granularity1] ?? 0);
        }
        return granularity1 < granularity2 ? -1 : 1;
    });
}

export function yearSelected(selectedOptionIds) {
    return selectedOptionIds.some((optionId) => optionId.startsWith("year"));
}
