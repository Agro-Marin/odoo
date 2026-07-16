// @ts-check
/** @odoo-module native */

/** @module @web/services/field_service - Service for loading field definitions, paths, and property definitions from the ORM */

/**
 * @typedef {Object} LoadFieldsOptions
 * @property {string[]|false} [fieldNames]
 * @property {string[]} [attributes]
 */

/**
 * @typedef {Object} LoadPathResult
 * @property {string} [isInvalid]
 * @property {string[]} names
 * @property {{ resModel: string | null, fieldDefs: any }[]} modelsInfo
 */

import { Domain } from "@web/core/domain";
import { registry } from "@web/core/registry";
/**
 * @param {Record<string, any>} fieldDef
 * @param {boolean} [followRelationalProperties=false]
 */
function getRelation(fieldDef, followRelationalProperties = false) {
    if (fieldDef.relation) {
        return fieldDef.relation;
    }
    if (fieldDef.comodel && followRelationalProperties) {
        return fieldDef.comodel;
    }
    return null;
}

export const fieldService = {
    dependencies: ["orm"],
    async: [
        "loadFieldInfo",
        "loadFields",
        "loadPath",
        "loadPropertyDefinitions",
        "loadPathDescription",
    ],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     */
    start(env, { orm }) {
        /**
         * @param {string} resModel
         * @param {LoadFieldsOptions} [options]
         * @returns {Promise<Record<string, any>>}
         */
        async function loadFields(resModel, options = {}) {
            if (typeof resModel !== "string" || !resModel) {
                throw new Error(`Invalid model name: ${resModel}`);
            }
            // A transient fields_get failure breaks every view for the model until
            // reload; fields_get is idempotent, so one retry smooths a cold-fetch
            // failure without masking a persistent outage.
            // ``immutable``: warm hits share the frozen cached payload instead of
            // cloning per hit — consumers must treat field defs as read-only.
            return orm
                .cache({ type: "disk", immutable: true })
                .retry(1)
                .call(resModel, "fields_get", [options.fieldNames, options.attributes]);
        }

        /**
         * @param {string} resModel
         * @param {Record<string, any>} fieldDefs
         * @param {string} name
         * @param {import("@web/core/domain").DomainListRepr} [domain=[]]
         * @returns {Promise<Record<string, any>>}
         */
        async function _loadPropertyDefinitions(
            resModel,
            fieldDefs,
            name,
            domain = [],
        ) {
            const {
                definition_record: definitionRecord,
                definition_record_field: definitionRecordField,
            } = fieldDefs[name];
            const definitionRecordModel = fieldDefs[definitionRecord].relation;

            let result;
            if (definitionRecordModel === "properties.base.definition") {
                // Record without parent (eg `res.partner`)
                result = await orm.call(
                    "properties.base.definition",
                    "get_properties_base_definition",
                    [resModel, name],
                );
            } else {
                // @ts-ignore
                domain = Domain.and([
                    [[definitionRecordField, "!=", false]],
                    domain,
                ]).toList();
                result = await orm.webSearchRead(definitionRecordModel, domain, {
                    specification: {
                        display_name: {},
                        [definitionRecordField]: {},
                    },
                });
            }

            /** @type {Record<string, any>} */
            const definitions = {};
            for (const record of result.records) {
                for (const definition of record[definitionRecordField]) {
                    definitions[definition.name] = {
                        is_property: true,
                        // for now, all properties are searchable but their definitions don't contain that info
                        searchable: true,
                        // differentiate definitions with same name but on different parent
                        record_id: record.id,
                        record_name: record.display_name,
                        ...(definition.comodel ? { relation: definition.comodel } : {}),
                        ...definition,
                    };
                }
            }
            return definitions;
        }

        /**
         * @param {string} resModel
         * @param {string} fieldName
         * @param {import("@web/core/domain").DomainListRepr} [domain]
         * @returns {Promise<Record<string, any>>}
         */
        async function loadPropertyDefinitions(resModel, fieldName, domain) {
            const fieldDefs = await loadFields(resModel);
            return _loadPropertyDefinitions(resModel, fieldDefs, fieldName, domain);
        }

        /**
         * @param {string|null} resModel valid model name or null (case virtual)
         * @param {Record<string, any>|null} fieldDefs
         * @param {string[]} names
         * @param {boolean} [followRelationalProperties=false]
         * @returns {Promise<LoadPathResult>}
         */
        async function _loadPath(
            resModel,
            fieldDefs,
            names,
            followRelationalProperties = false,
        ) {
            if (!fieldDefs) {
                return { isInvalid: "path", names, modelsInfo: [] };
            }

            const [name, ...remainingNames] = names;
            const modelsInfo = [{ resModel, fieldDefs }];
            if (resModel === "*" && remainingNames.length) {
                return { isInvalid: "path", names, modelsInfo };
            }

            const fieldDef = fieldDefs[name];
            if (
                (name !== "*" && !fieldDef) ||
                (name === "*" && remainingNames.length)
            ) {
                return { isInvalid: "path", names, modelsInfo };
            }

            if (!remainingNames.length) {
                return { names, modelsInfo };
            }

            let subResult;
            const relation = getRelation(fieldDef, followRelationalProperties);
            if (relation) {
                subResult = await _loadPath(
                    relation,
                    await loadFields(relation),
                    remainingNames,
                );
            } else if (fieldDef.type === "properties") {
                subResult = await _loadPath(
                    followRelationalProperties ? resModel : "*",
                    // resModel can't be null here: a "properties" fieldDef only
                    // exists on a concrete model (the null/"*" case returned
                    // above).
                    await _loadPropertyDefinitions(
                        /** @type {string} */ (resModel),
                        fieldDefs,
                        name,
                    ),
                    remainingNames,
                );
            }

            if (subResult) {
                /** @type {LoadPathResult} */
                const result = {
                    names,
                    modelsInfo: [...modelsInfo, ...subResult.modelsInfo],
                };
                if (subResult.isInvalid) {
                    result.isInvalid = "path";
                }
                return result;
            }

            return { isInvalid: "path", names, modelsInfo };
        }

        /**
         * Note: the symbol * can be used at the end of path (e.g path="*" or path="user_id.*").
         * It says to load the fields of the appropriate model.
         * @param {string} resModel
         * @param {string} path
         * @returns {Promise<LoadPathResult>}
         */
        async function loadPath(
            resModel,
            path = "*",
            followRelationalProperties = false,
        ) {
            const fieldDefs = await loadFields(resModel);
            if (typeof path !== "string" || !path) {
                throw new Error(`Invalid path: ${path}`);
            }
            return _loadPath(
                resModel,
                fieldDefs,
                path.split("."),
                followRelationalProperties,
            );
        }

        /**
         * @param {string} resModel
         * @param {string} path
         * @returns {Promise<Object>}
         */
        async function loadFieldInfo(resModel, path) {
            if (typeof path !== "string" || !path || path === "*") {
                return { resModel, fieldDef: null };
            }
            const { isInvalid, names, modelsInfo } = await loadPath(resModel, path);
            if (isInvalid) {
                return { resModel, fieldDef: null };
            }
            // Non-empty by construction (loadPath returned a valid result), so
            // index instead of at(-1) to avoid the `undefined` in at()'s type.
            const name = names[names.length - 1];
            const modelInfo = modelsInfo[modelsInfo.length - 1];
            return {
                resModel: modelInfo.resModel,
                // A path ending in "*" (e.g. "user_id.*", legal per loadPath's
                // docstring) resolves to no concrete field def — it's a
                // load-all-fields marker, not a selectable field. Normalise the
                // resulting ``undefined`` to the documented ``null`` sentinel
                // (as the bare "*" branch above already returns).
                fieldDef: modelInfo.fieldDefs[name] ?? null,
            };
        }

        /**
         * @param {any} [value]
         */
        function makeString(value) {
            return String(value ?? "-");
        }

        /**
         * @param {string} resModel
         * @param {string | number} path
         * @param {boolean} [allowEmpty]
         * @returns {Promise<{ isInvalid: boolean, displayNames: string[] }>}
         */
        async function loadPathDescription(resModel, path, allowEmpty) {
            if ([0, 1].includes(/** @type {number} */ (path))) {
                return { isInvalid: false, displayNames: [makeString(path)] };
            }
            if (allowEmpty && !path) {
                return { isInvalid: false, displayNames: [] };
            }
            if (typeof path !== "string" || !path || path === "*") {
                return { isInvalid: true, displayNames: [makeString()] };
            }
            const { isInvalid, modelsInfo, names } = await loadPath(resModel, path);
            const result = {
                isInvalid: !!isInvalid,
                displayNames: /** @type {string[]} */ ([]),
            };
            if (!isInvalid) {
                // Non-empty by construction (loadPath returned a valid result).
                const lastName = names[names.length - 1];
                const lastFieldDef =
                    modelsInfo[modelsInfo.length - 1].fieldDefs[lastName];
                if (
                    !lastFieldDef ||
                    ["properties", "properties_definition"].includes(lastFieldDef.type)
                ) {
                    // A trailing "*" (e.g. "user_id.*") passes _loadPath as valid
                    // but has no concrete field def — it's a load-all-fields
                    // marker, not a selectable field — so treat it as invalid
                    // (as the bare "*" guard above already does), and guard the
                    // undefined lastFieldDef so ``.type`` can't throw. There is
                    // also no known case where we want to select a 'properties'
                    // field directly.
                    result.isInvalid = true;
                }
            }
            for (let index = 0; index < names.length; index++) {
                const name = names[index];
                const fieldDef = modelsInfo[index]?.fieldDefs[name];
                result.displayNames.push(fieldDef?.string || makeString(name));
            }
            return result;
        }

        return {
            loadFieldInfo,
            loadFields,
            loadPath,
            loadPathDescription,
            loadPropertyDefinitions,
        };
    },
};

registry.category("services").add("field", fieldService);
