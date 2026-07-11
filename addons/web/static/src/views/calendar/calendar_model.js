// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_model - Calendar event data loading, date range computation, filter sections, and timezone handling */

import { browser } from "@web/core/browser/browser";
import { makeContext } from "@web/core/context";
import { getFieldCodec } from "@web/core/field_codec";
import {
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";
import { groupBy } from "@web/core/utils/collections/arrays";
import { Cache } from "@web/core/utils/collections/cache";
import { formatFloat } from "@web/core/utils/format/numbers";
import { useDebounced } from "@web/core/utils/timing";
import { Model } from "@web/model/model";
import { extractFieldsFromArchInfo } from "@web/model/relational_model/utils";
import { user } from "@web/services/user";
import { computeAggregatedValue } from "@web/views/view_measurements";

import {
    computeCalendarRange,
    computeFiltersDomain,
    computeRangeDomain,
} from "./calendar_date_range.js";
import { normalizeCalendarRecord } from "./calendar_record.js";

/**
 * Data model for the calendar view.
 *
 * Manages loading, normalization, and CRUD of calendar records. Computes date
 * ranges per scale, handles filter sections (static and dynamic), unusual days,
 * aggregated values, and domain construction. Stores view state (current date,
 * scale) and persists scale preference in localStorage.
 */
export class CalendarModel extends Model {
    static DEBOUNCED_LOAD_DELAY = 600;
    static services = ["notification"];

    /**
     * @param {Object} params - arch info including field mapping, scales, and filter config
     * @param {{ notification: Object }} services
     */
    setup(params, { notification }) {
        // Monotonic load epoch. Every load() captures the current value and
        // only applies its result if it is still the latest when it settles.
        // Superseding a load (a newer load() or an explicit filter mutation)
        // just bumps this counter, so the superseded load resolves normally
        // instead of hanging — unlike KeepLast, whose wrapper for a superseded
        // task never settles and would leave `await this.load()` callers
        // (createRecord/updateRecord/multiCreateRecords/quick-create) stuck.
        /** @protected */
        this.currentLoadId = 0;
        this.notification = notification;

        const formViewFromConfig = (this.env.config.views || []).find(
            (view) => view[1] === "form",
        );
        const formViewIdFromConfig = formViewFromConfig ? formViewFromConfig[0] : false;
        const fieldNodes = params.popoverFieldNodes;
        const { activeFields, fields } = extractFieldsFromArchInfo(
            /** @type {any} */ ({ fieldNodes }),
            params.fields,
        );
        this.meta = {
            ...params,
            activeFields,
            fields,
            firstDayOfWeek: (localization.weekStart || 0) % 7,
            formViewId: params.formViewId || formViewIdFromConfig,
        };
        if (this.meta.aggregate?.split(":").length === 1) {
            const aggregator = this.fields[this.meta.aggregate].aggregator || "sum";
            this.meta.aggregate = `${this.meta.aggregate}:${aggregator}`;
        }
        this.meta.scale = this.getLocalStorageScale();
        this.data = {
            filterSections: {},
            range: null,
            records: {},
            unusualDays: [],
        };

        const debouncedLoadDelay = /** @type {any} */ (this.constructor)
            .DEBOUNCED_LOAD_DELAY;
        this.debouncedLoad = useDebounced(
            (params) => this.load(params),
            debouncedLoadDelay,
        );

        this._unusualDaysCache = new Cache(
            (data) => this.fetchUnusualDays(data),
            // Keyed by range AND a context fingerprint: get_unusual_days
            // results can depend on context that changes without a model
            // rebuild (company switch, employee-dependent overrides), and the
            // cache lives for the model's lifetime.
            (data) =>
                `${serializeDateTime(data.range.start)},${serializeDateTime(data.range.end)},${JSON.stringify(this.meta.context ?? {})}`,
        );
    }
    /**
     * Load or reload calendar data with optional parameter overrides.
     *
     * @param {Object} [params] - overrides for date, scale, context, etc.
     */
    async load(params = {}) {
        // updateData reads this.meta (range, domain, fields...), so the next
        // meta must be committed before the fetch — but keep a snapshot to
        // roll back if the fetch fails while this load is still the latest,
        // so meta (header state) can't point at a position this.data never
        // reached. The localStorage scale write moves after the epoch check
        // for the same reason. The meta object identity never changes:
        // subclasses hold references to it.
        const previousMeta = { ...this.meta };
        Object.assign(this.meta, params);
        if (!this.meta.date) {
            this.meta.date =
                params.context && params.context.initial_date
                    ? deserializeDateTime(params.context.initial_date).startOf("day")
                    : DateTime.local().startOf("day");
        }
        // Prevent picking a scale that is not supported by the view
        if (!this.meta.scales.includes(this.meta.scale)) {
            this.meta.scale = this.meta.scales[0];
        }
        const data = { ...this.data };
        const loadId = ++this.currentLoadId;
        let succeeded = false;
        try {
            await this.updateData(data);
            succeeded = true;
        } finally {
            if (!succeeded && loadId === this.currentLoadId) {
                Object.assign(this.meta, previousMeta);
            }
        }
        if (loadId !== this.currentLoadId) {
            // Superseded by a newer load() or by an explicit filter mutation
            // while updateData was in flight: resolve normally without applying
            // this now-stale data (and without notifying), so awaiting callers
            // are released instead of hanging forever.
            return;
        }
        browser.localStorage.setItem(this.storageKey, this.meta.scale);
        this.data = data;
        this.notify();
    }

    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    get aggregate() {
        return this.meta.aggregate;
    }
    get date() {
        return this.meta.date;
    }
    get canCreate() {
        return this.meta.canCreate;
    }
    get canDelete() {
        return this.meta.canDelete;
    }
    get canEdit() {
        return (
            this.meta.canEdit &&
            !this.meta.fields[this.meta.fieldMapping.date_start].readonly
        );
    }
    get dateStartType() {
        return this.fields[this.fieldMapping.date_start].type;
    }
    get dateStopType() {
        if (this.fieldMapping.date_stop) {
            return this.fields[this.fieldMapping.date_stop].type;
        }
        return null;
    }
    get eventLimit() {
        return this.meta.eventLimit;
    }
    get exportedState() {
        return { date: this.meta.date };
    }
    get fieldMapping() {
        return this.meta.fieldMapping;
    }
    get fields() {
        return this.meta.fields;
    }
    get filterSections() {
        return Object.values(this.data.filterSections);
    }
    get firstDayOfWeek() {
        return this.meta.firstDayOfWeek;
    }
    get formViewId() {
        return this.meta.formViewId;
    }
    get hasAllDaySlot() {
        return (
            this.meta.fieldMapping.all_day ||
            this.meta.fields[this.meta.fieldMapping.date_start].type === "date"
        );
    }
    get hasEditDialog() {
        return this.meta.hasEditDialog;
    }
    get hasMultiCreate() {
        return (
            !!this.meta.multiCreateView &&
            !this.env.isSmall &&
            this.meta.scale === "month"
        );
    }
    get hasQuickCreate() {
        return this.meta.quickCreate;
    }
    get isDateHidden() {
        return this.meta.isDateHidden;
    }
    get isTimeHidden() {
        return this.meta.isTimeHidden;
    }
    get monthOverflow() {
        return this.meta.monthOverflow;
    }
    get popoverFieldNodes() {
        return this.meta.popoverFieldNodes;
    }
    get activeFields() {
        return this.meta.activeFields;
    }
    get rangeEnd() {
        return this.data.range.end;
    }
    get rangeStart() {
        return this.data.range.start;
    }
    get records() {
        return this.data.records;
    }
    get resModel() {
        return this.meta.resModel;
    }
    get scale() {
        return this.meta.scale;
    }
    get scales() {
        return this.meta.scales;
    }
    get showDatePicker() {
        return this.meta.showDatePicker;
    }
    get showMultiCreateTimeRange() {
        return this.dateStartType === "datetime" && this.dateStopType === "datetime";
    }
    get storageKey() {
        return `scaleOf-viewId-${this.env.config.viewId}`;
    }
    get unusualDays() {
        return this.data.unusualDays;
    }
    get quickCreateFormViewId() {
        return this.meta.quickCreateViewId;
    }
    get defaultFilterLabel() {
        return _t("Undefined");
    }

    async createFilter(fieldName, filterValue) {
        const info = this.meta.filtersInfo[fieldName];
        if (!info || !info.writeFieldName || !info.writeResModel) {
            return;
        }

        const normalizedFilterValue = Array.isArray(filterValue)
            ? filterValue
            : [filterValue];
        const dataArray = normalizedFilterValue.map((value) => {
            const data = {
                user_id: user.userId,
                [info.writeFieldName]: value,
            };
            if (info.filterFieldName) {
                data[info.filterFieldName] = true;
            }
            return data;
        });

        await this.orm.create(info.writeResModel, dataArray);
        await this.load();
    }
    async createRecord(record) {
        const rawRecord = this.buildRawRecord(record);
        const context = this.makeContextDefaults(rawRecord);
        await this.orm.create(this.meta.resModel, [rawRecord], { context });
        await this.load();
    }

    /**
     * Create records for the given dates. If there is a filter section, the
     * first filter section's values are added to each record.
     *
     * @param {Object} multiCreateData
     * @param {any[]} dates array of Date
     * @returns {Promise<*>}
     */
    async multiCreateRecords(multiCreateData, dates) {
        const records = [];
        const values = await multiCreateData.record.getChanges();
        const timeRange = multiCreateData.timeRange;

        // we deliberately only use the values of the first filter section, to avoid combinatorial explosion
        const [section] = this.filterSections;
        for (const date of dates) {
            const initialRecordValue = {};
            if (this.showMultiCreateTimeRange) {
                initialRecordValue.start = date.plus(timeRange.start.toObject());
                initialRecordValue.end = date.plus(timeRange.end.toObject());
            } else {
                initialRecordValue.start = date;
            }
            const rawRecord = this.buildRawRecord(initialRecordValue);
            if (!section) {
                records.push({
                    ...rawRecord,
                    ...values,
                });
                continue;
            }
            for (const filter of section.filters) {
                // "user" is the auto-added current-user filter: it carries a
                // real value and is often the ONLY active one — excluding it
                // made multi-create a silent no-op in the common case.
                if (
                    filter.active &&
                    ["record", "user"].includes(filter.type) &&
                    filter.value
                ) {
                    records.push({
                        ...rawRecord,
                        ...values,
                        [section.fieldName]: filter.value,
                    });
                }
            }
        }
        if (!records.length && dates.length) {
            // Nothing matched (e.g. no filter checked): tell the user instead
            // of silently clearing their selection.
            this.notification.add(
                _t(
                    "Activate at least one record in the side panel to assign the new events to.",
                ),
                { type: "warning" },
            );
        }
        if (records.length) {
            const createdRecords = await this.orm.create(this.meta.resModel, records, {
                context: this.meta.context,
            });
            await this.load();
            return createdRecords;
        }
        return [];
    }

    async unlinkFilter(fieldName, recordId) {
        const info = this.meta.filtersInfo[fieldName];
        const section = this.data.filterSections[fieldName];
        if (section) {
            // remove the filter directly, to provide a direct feedback to the user
            // Cancel any in-flight load so it won't overwrite this optimistic
            // update; bumping the epoch releases its awaiting caller cleanly.
            this.currentLoadId++;
            section.filters = section.filters.filter((f) => f.recordId !== recordId);
        }
        if (info?.writeResModel) {
            await this.orm.unlink(info.writeResModel, [recordId]);
            await this.debouncedLoad();
        }
    }
    async unlinkRecord(recordId) {
        await this.orm.unlink(this.meta.resModel, [recordId]);
        await this.load();
    }

    async unlinkRecords(recordsId) {
        if (recordsId.length) {
            await this.orm.unlink(this.meta.resModel, recordsId);
            await this.load();
        }
    }

    async updateFilters(fieldName, filters, active) {
        // update filters directly, to provide a direct feedback to the user
        // Cancel any in-flight load so it won't overwrite this optimistic
        // update; bumping the epoch releases its awaiting caller cleanly.
        this.currentLoadId++;
        for (const filter of filters) {
            filter.active = active;
        }
        const info = this.meta.filtersInfo[fieldName];
        if (info && info.writeFieldName && info.writeResModel && info.filterFieldName) {
            const userFilter = filters.find((f) => f.type === "user");
            if (userFilter) {
                userFilter.active = active;
            }
            const filterIds = filters
                .filter((f) => f.type === "record")
                .map((f) => f.recordId);
            if (filterIds.length) {
                const data = {
                    [info.filterFieldName]: active,
                };
                const context = this.meta.context;
                await this.orm.write(info.writeResModel, filterIds, data, {
                    context,
                });
            }
        }
        await this.debouncedLoad();
    }
    async updateRecord(record, options = {}) {
        const rawRecord = this.buildRawRecord(record, options);
        // The name is immutable here: buildRawRecord maps the title onto
        // create_name_field when the arch defines one, so delete the mapped
        // key — deleting only the literal "name" key would let a title
        // overwrite the record name on such views.
        delete rawRecord[this.meta.fieldMapping.create_name_field || "name"];
        try {
            await this.orm.write(this.meta.resModel, [record.id], rawRecord, {
                context: this.meta.context,
            });
        } finally {
            // Reload even on failure: drag/drop and resize already rendered the
            // event client-side, so only a reload re-syncs with server state.
            // The rejection still propagates for the standard error dialog.
            await this.load();
        }
    }

    getAllDayDates(start, end) {
        return [start.set({ hours: 7 }), end.set({ hours: 19 })];
    }

    /**
     * Convert a UI record (with start/end DateTimes) into raw field values for ORM operations.
     *
     * @param {Object} partialRecord - record with start, end, isAllDay, title
     * @param {Object} [options] - additional options like duration_hour, moved
     * @returns {Object} raw field values keyed by field name
     */
    buildRawRecord(partialRecord, options = {}) {
        const data = {};
        data[this.meta.fieldMapping.create_name_field || "name"] = partialRecord.title;

        let start = partialRecord.start;
        let end = partialRecord.end;

        if (!end || !end.isValid) {
            if (partialRecord.isAllDay) {
                end = start;
            } else {
                // in week mode or day mode, convert allday event to event
                end = start.plus({ hours: options.duration_hour || 1 });
            }
        }

        const isDateEvent = this.dateStartType === "date";
        // An "all day" event without the "all_day" option is not considered
        // as a 24h day. It's just a part of the day (by default: 7h-19h).
        if (partialRecord.isAllDay) {
            if (!this.hasAllDaySlot && !isDateEvent && !partialRecord.id) {
                // default hours in the user's timezone
                [start, end] = this.getAllDayDates(start, end);
            }
        }

        if (this.meta.fieldMapping.all_day) {
            data[this.meta.fieldMapping.all_day] = partialRecord.isAllDay;
        }

        data[this.meta.fieldMapping.date_start] =
            (partialRecord.isAllDay && this.hasAllDaySlot
                ? "date"
                : this.dateStartType) === "date"
                ? serializeDate(start)
                : serializeDateTime(start);

        if (this.meta.fieldMapping.date_stop) {
            data[this.meta.fieldMapping.date_stop] =
                (partialRecord.isAllDay && this.hasAllDaySlot
                    ? "date"
                    : this.dateStopType) === "date"
                    ? serializeDate(end)
                    : serializeDateTime(end);
        }

        if (this.meta.fieldMapping.date_delay) {
            if (this.meta.scale !== "month" || !options.moved) {
                data[this.meta.fieldMapping.date_delay] = end.diff(
                    start,
                    "hours",
                ).hours;
            }
        }
        return data;
    }
    /**
     * Build a context dict with default_* keys from a raw record for form view creation.
     *
     * @param {Object} rawRecord - raw field values from buildRawRecord
     * @returns {Object} context with default values
     */
    makeContextDefaults(rawRecord) {
        const { fieldMapping, scale } = this.meta;

        const context = { ...this.meta.context };
        const fieldNames = [
            fieldMapping.create_name_field || "name",
            fieldMapping.date_start,
            fieldMapping.date_stop,
            fieldMapping.date_delay,
            fieldMapping.all_day || "allday",
        ];
        for (const fieldName of fieldNames) {
            // fieldName could be in rawRecord but not defined
            if (rawRecord[fieldName] !== undefined) {
                context[`default_${fieldName}`] = rawRecord[fieldName];
            }
        }
        if (["month", "year"].includes(scale)) {
            context[`default_${fieldMapping.all_day || "allday"}`] = true;
        }

        return context;
    }

    //--------------------------------------------------------------------------
    // Protected
    //--------------------------------------------------------------------------

    /**
     * @protected
     */
    async updateData(data) {
        data.range = this.computeRange();
        let unusualDaysProm;
        if (this.meta.showUnusualDays) {
            unusualDaysProm = this.loadUnusualDays(data).then((unusualDays) => {
                data.unusualDays = unusualDays;
            });
        }

        const { sections, dynamicFiltersInfo } = await this.loadFilters(data);

        // Load records and dynamic filters only with fresh filters
        data.filterSections = sections;
        data.records = await this.loadRecords(data);
        const dynamicSections = await this.loadDynamicFilters(data, dynamicFiltersInfo);

        // Apply newly computed filter sections
        Object.assign(data.filterSections, dynamicSections);

        // Remove records that don't match dynamic filters
        for (const [fieldName, filterInfo] of Object.entries(dynamicSections)) {
            const field = this.meta.fields[fieldName];
            if (!field) {
                continue;
            }
            const inactiveFilters = filterInfo.filters.filter((f) => !f.active);
            if (!inactiveFilters.length) {
                continue;
            }
            const inactiveFilterVals = new Set(
                inactiveFilters.map((filter) => filter.value),
            );
            for (const [recordId, record] of Object.entries(data.records)) {
                const rawValue = record.rawRecord[fieldName];
                let remove;
                if (["many2many", "one2many"].includes(field.type)) {
                    // An empty x2many belongs to the `false` ("Undefined")
                    // bucket, like an unset many2one — `every` is vacuously
                    // true on [], which used to remove such records as soon
                    // as ANY dynamic filter was unchecked.
                    remove = rawValue.length
                        ? rawValue.every((value) => inactiveFilterVals.has(value))
                        : inactiveFilterVals.has(false);
                } else {
                    const recordValue = Array.isArray(rawValue)
                        ? rawValue[0]
                        : rawValue;
                    remove = inactiveFilterVals.has(recordValue);
                }
                if (remove) {
                    delete data.records[recordId];
                }
            }
        }

        await unusualDaysProm;

        // Compute aggregate values
        if (this.aggregate) {
            for (const [fieldName, { filters }] of Object.entries(
                data.filterSections,
            )) {
                const aggregates = this.computeAggregatedValues(fieldName, data);
                for (const filter of filters) {
                    filter.aggregatedValue = aggregates[filter.value] || 0;
                }
            }
        }
    }

    //--------------------------------------------------------------------------

    /**
     * @protected
     */
    computeRange() {
        const { scale, date, firstDayOfWeek } = this.meta;
        return computeCalendarRange(scale, date, firstDayOfWeek, this.monthOverflow);
    }

    /**
     * @param {string} fieldName
     * @param {Object} [data=this.data]
     * @returns Object
     */
    computeAggregatedValues(fieldName, data = this.data) {
        const records = Object.values(data.records);
        const fieldType = this.meta.fields[fieldName].type;
        const groups = groupBy(records, ({ rawRecord }) => {
            const rawValue = rawRecord[fieldName];
            // FIXME: many2many not supported, but not supported for filters either
            return fieldType === "many2one" ? rawValue?.[0] || false : rawValue;
        });
        const aggregates = {};
        const [aggregateField, aggregator] = this.aggregate.split(":");
        for (const group of Object.keys(groups)) {
            const values = groups[group].map(
                ({ rawRecord }) => rawRecord[aggregateField],
            );
            aggregates[group] = formatFloat(
                computeAggregatedValue(values, aggregator),
                {
                    trailingZeros: false,
                },
            );
        }
        return aggregates;
    }
    /**
     * @protected
     */
    computeDomain(data) {
        return [
            ...this.meta.domain,
            ...this.computeRangeDomain(data),
            ...this.computeFiltersDomain(data),
        ];
    }
    /**
     * @protected
     */
    computeFiltersDomain(data) {
        return computeFiltersDomain(data.filterSections, this.meta.filtersInfo);
    }
    /**
     * @protected
     */
    computeRangeDomain(data) {
        return computeRangeDomain(
            this.meta.fieldMapping,
            this.dateStartType,
            data.range,
        );
    }

    /**
     * @protected
     */
    fetchUnusualDays(data) {
        return this.orm.call(this.meta.resModel, "get_unusual_days", [
            serializeDateTime(data.range.start),
            serializeDateTime(data.range.end),
        ]);
    }
    /**
     * @protected
     */
    async loadUnusualDays(data) {
        const unusualDays = await this._unusualDaysCache.read(data);
        return Object.entries(unusualDays)
            .filter((entry) => entry[1])
            .map((entry) => entry[0]);
    }

    /**
     * @protected
     */
    fetchRecords(data) {
        const { context, fieldNames, resModel } = this.meta;
        return this.orm.searchRead(
            resModel,
            this.computeDomain(data),
            [...new Set([...fieldNames, ...Object.keys(this.meta.activeFields)])],
            { context },
        );
    }
    /**
     * @protected
     */
    async loadRecords(data) {
        const rawRecords = await this.fetchRecords(data);
        const records = {};
        for (const rawRecord of rawRecords) {
            records[rawRecord.id] = this.normalizeRecord(rawRecord);
        }
        return records;
    }
    /**
     * @protected
     * @param {Record<string, any>} rawRecord
     */
    normalizeRecord(rawRecord) {
        return normalizeCalendarRecord(rawRecord, {
            fields: this.meta.fields,
            fieldMapping: this.meta.fieldMapping,
            isTimeHidden: this.meta.isTimeHidden,
            scale: this.meta.scale,
            isSmall: this.env.isSmall,
        });
    }

    /**
     * @protected
     */
    addFilterFields(record, filterInfo) {
        return {
            colorIndex: record.colorIndex,
        };
    }

    /**
     * @protected
     */
    fetchFilters(resModel, fieldNames) {
        return this.orm.searchRead(
            resModel,
            [["user_id", "=", user.userId]],
            fieldNames,
        );
    }

    getLocalStorageScale() {
        const localScaleId = browser.localStorage.getItem(this.storageKey);
        return this.meta.scales.includes(localScaleId) ? localScaleId : this.meta.scale;
    }

    /**
     * @protected
     */
    async loadFilters(data) {
        const previousSections = data.filterSections;
        const sections = {};
        const dynamicFiltersInfo = {};
        const proms = [];
        for (const [fieldName, filterInfo] of Object.entries(this.meta.filtersInfo)) {
            const previousSection = previousSections[fieldName];
            if (filterInfo.writeResModel) {
                const prom = this.loadFilterSection(
                    fieldName,
                    filterInfo,
                    previousSection,
                ).then((result) => {
                    sections[fieldName] = result;
                });
                proms.push(prom);
            } else {
                dynamicFiltersInfo[fieldName] = { filterInfo, previousSection };
            }
        }
        await Promise.all(proms);
        return { sections, dynamicFiltersInfo };
    }
    /**
     * @protected
     */
    async loadFilterSection(fieldName, filterInfo, previousSection) {
        const { filterFieldName, writeFieldName, writeResModel } = filterInfo;
        const fields = [writeFieldName, filterFieldName].filter(Boolean);
        const rawFilters = await this.fetchFilters(writeResModel, fields);
        const previousFilters = previousSection ? previousSection.filters : [];

        // Index previous record filters by id to avoid a find() per raw filter
        const previousRecordFilters = new Map();
        for (const filter of previousFilters) {
            if (filter.type === "record") {
                previousRecordFilters.set(filter.recordId, filter);
            }
        }
        const filters = rawFilters.map((rawFilter) =>
            this.makeFilterRecord(
                filterInfo,
                previousRecordFilters.get(rawFilter.id),
                rawFilter,
            ),
        );

        const field = this.meta.fields[fieldName];
        const isUserOrPartner = ["res.users", "res.partner"].includes(field.relation);
        if (isUserOrPartner) {
            const previousUserFilter = previousFilters.find((f) => f.type === "user");
            filters.push(
                this.makeFilterUser(
                    filterInfo,
                    previousUserFilter,
                    fieldName,
                    rawFilters,
                ),
            );
        }

        return {
            label: filterInfo.label,
            fieldName,
            filters,
            avatar: {
                field: filterInfo.avatarFieldName,
                model: filterInfo.resModel,
            },
            hasAvatar: !!filterInfo.avatarFieldName,
            write: {
                field: writeFieldName,
                model: writeResModel,
            },
            canAddFilter: !!filterInfo.writeResModel,
            context: makeContext([filterInfo.context, this.meta.context]),
        };
    }
    /**
     * @protected
     */
    async loadDynamicFilters(data, filtersInfo) {
        const sections = {};
        const proms = [];
        for (const [fieldName, { filterInfo, previousSection }] of Object.entries(
            filtersInfo,
        )) {
            const prom = this.loadDynamicFilterSection(
                data,
                fieldName,
                filterInfo,
                previousSection,
            ).then((result) => {
                sections[fieldName] = result;
            });
            proms.push(prom);
        }
        await Promise.all(proms);
        return sections;
    }
    /**
     * @protected
     */
    async loadDynamicFilterSection(data, fieldName, filterInfo, previousSection) {
        const { fields, fieldMapping } = this.meta;
        const field = fields[fieldName];
        const previousFilters = previousSection ? previousSection.filters : [];

        // Dedupe by id with a Map: a find() per value would be O(records × values)
        const rawFiltersById = new Map();
        for (const record of Object.values(data.records)) {
            let rawValues = ["many2many", "one2many"].includes(field.type)
                ? record.rawRecord[fieldName]
                : [record.rawRecord[fieldName]];
            if (!rawValues.length) {
                // Empty x2many: emit the same `false` bucket as an unset
                // many2one so these records get an "Undefined" side-panel
                // filter instead of no checkbox at all.
                rawValues = [false];
            }

            for (const rawValue of rawValues) {
                const value = Array.isArray(rawValue) ? rawValue[0] : rawValue;
                if (!rawFiltersById.has(value)) {
                    rawFiltersById.set(value, {
                        id: value,
                        [fieldName]: rawValue,
                        ...this.addFilterFields(record, filterInfo),
                    });
                }
            }
        }
        const rawFilters = [...rawFiltersById.values()];

        const isX2Many = ["many2many", "one2many"].includes(field.type);

        const relatedIds = rawFilters.map((f) => f.id).filter((id) => id);
        let rawColors = [];
        if (relatedIds.length && field.relation) {
            const fieldsToFetch = [];
            const { colorFieldName } = filterInfo;
            const shouldFetchColor =
                colorFieldName &&
                (!fieldMapping.color ||
                    `${fieldName}.${colorFieldName}` !==
                        fields[fieldMapping.color].related);
            if (shouldFetchColor) {
                fieldsToFetch.push(colorFieldName);
            }
            if (isX2Many) {
                fieldsToFetch.push("display_name");
            }
            if (fieldsToFetch.length) {
                const records = await this.orm.searchRead(
                    field.relation,
                    [["id", "in", relatedIds]],
                    fieldsToFetch,
                    { context: { active_test: false } },
                );
                if (isX2Many) {
                    const nameById = Object.fromEntries(
                        records.map((r) => [r.id, r.display_name]),
                    );
                    for (const rawFilter of rawFilters) {
                        const id = rawFilter.id;
                        if (!id || !nameById[id]) {
                            continue;
                        }
                        rawFilter[fieldName] = [id, nameById[id]];
                    }
                }
                if (shouldFetchColor) {
                    rawColors = records;
                }
            }
        }

        // Index previous dynamic filters by value to avoid a find() per raw filter
        const previousDynamicFilters = new Map();
        for (const filter of previousFilters) {
            if (filter.type === "dynamic") {
                previousDynamicFilters.set(filter.value, filter);
            }
        }
        const filters = rawFilters.map((rawFilter) =>
            this.makeFilterDynamic(
                filterInfo,
                previousDynamicFilters.get(rawFilter.id),
                fieldName,
                rawFilter,
                rawColors,
            ),
        );

        return {
            label: filterInfo.label,
            fieldName,
            filters,
            avatar: {
                field: filterInfo.avatarFieldName,
                model: filterInfo.resModel,
            },
            hasAvatar: !!filterInfo.avatarFieldName,
            write: {
                field: filterInfo.writeFieldName,
                model: filterInfo.writeResModel,
            },
            canAddFilter: !!filterInfo.writeResModel,
        };
    }
    /**
     * @protected
     */
    makeFilterDynamic(filterInfo, previousFilter, fieldName, rawFilter, rawColors) {
        const { fieldMapping, fields } = this.meta;
        const rawValue = rawFilter[fieldName];
        const value = Array.isArray(rawValue) ? rawValue[0] : rawValue;
        const field = fields[fieldName];
        const isX2Many = ["many2many", "one2many"].includes(field.type);
        const formatter = getFieldCodec(isX2Many ? "many2one" : field.type).format;

        const { colorFieldName } = filterInfo;
        const colorField = fields[fieldMapping.color];
        const hasFilterColorAttr = !!colorFieldName;
        const sameRelatedModel =
            colorField &&
            (colorField.relation === field.relation ||
                (colorField.related && colorField.related.startsWith(`${fieldName}.`)));
        let colorIndex = null;
        if (hasFilterColorAttr || sameRelatedModel) {
            colorIndex = rawFilter.colorIndex;
        }
        if (rawColors.length) {
            const rawColor = rawColors.find(({ id }) => id === value);
            colorIndex = rawColor ? rawColor[colorFieldName] : 0;
        }

        return {
            type: "dynamic",
            recordId: null,
            value,
            label: formatter(rawValue, { field }) || this.defaultFilterLabel,
            active: previousFilter ? previousFilter.active : true,
            canRemove: false,
            colorIndex,
            hasAvatar: !!value,
        };
    }
    /**
     * @protected
     */
    makeFilterRecord(filterInfo, previousFilter, rawRecord) {
        const { colorFieldName, filterFieldName, writeFieldName } = filterInfo;
        const { fields, fieldMapping } = this.meta;
        const raw = rawRecord[writeFieldName];
        const value = Array.isArray(raw) ? raw[0] : raw;
        const field = fields[writeFieldName];
        const isX2Many = ["many2many", "one2many"].includes(field.type);
        const formatter = getFieldCodec(isX2Many ? "many2one" : field.type).format;

        const colorField = fields[fieldMapping.color];
        const colorValue =
            colorField &&
            (() => {
                const sameRelatedModel = colorField.relation === field.relation;
                const sameRelatedField =
                    colorField.related === `${writeFieldName}.${colorFieldName}`;
                const shouldHaveColor = sameRelatedModel || sameRelatedField;
                const colorToUse = raw ? value : rawRecord[fieldMapping.color];
                return shouldHaveColor ? colorToUse : null;
            })();
        const colorIndex = Array.isArray(colorValue) ? colorValue[0] : colorValue;

        let active = false;
        if (filterFieldName) {
            active = rawRecord[filterFieldName];
        } else if (previousFilter) {
            active = previousFilter.active;
        }
        return {
            type: "record",
            recordId: rawRecord.id,
            value,
            label: formatter(raw),
            active,
            canRemove: true,
            colorIndex,
            hasAvatar: !!value,
        };
    }
    /**
     * @protected
     */
    makeFilterUser(filterInfo, previousFilter, fieldName, rawRecords) {
        const field = this.meta.fields[fieldName];
        const userFieldName = field.relation === "res.partner" ? "partnerId" : "userId";
        const value = user[userFieldName];

        let colorIndex = value;
        const rawRecord = rawRecords.find(
            (r) =>
                Array.isArray(r[filterInfo.writeFieldName]) &&
                r[filterInfo.writeFieldName][0] === value,
        );
        if (filterInfo.colorFieldName && rawRecord) {
            const colorValue = rawRecord[filterInfo.colorFieldName];
            colorIndex = Array.isArray(colorValue) ? colorValue[0] : colorValue;
        }

        return {
            type: "user",
            recordId: null,
            value,
            label: user.name,
            active: previousFilter ? previousFilter.active : true,
            canRemove: false,
            colorIndex,
            hasAvatar: !!value,
        };
    }
}
