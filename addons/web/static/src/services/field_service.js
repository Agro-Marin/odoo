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
            const fields = await orm
                .cache({ type: "disk", immutable: true })
                .retry(1)
                .call(resModel, "fields_get", [options.fieldNames, options.attributes]);
            return { ...fields };
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
                // `domain` is deliberately NOT forwarded, and that is correct
                // rather than an oversight. It exists for the branch below,
                // where definitions hang off a real parent record and the only
                // caller (`search_properties_mixin`) narrows to
                // `["id", "=", active_id]`. Base definitions have no such
                // parent: the server resolves them by (model, field) alone
                // (web/models/properties_base_definition.py), and `active_id`
                // is an id of the ACTION's model, so applying it here would
                // filter `properties.base.definition` by an unrelated id and
                // return nothing.
                //
                // No `.cache()` on purpose either: property definitions are
                // edited in-app and this call has no invalidation hook the way
                // `fields_get` (immutable per registry hash) does.
                result = await orm
                    .retry(1)
                    .call(
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
                        searchable: true,
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
                    followRelationalProperties,
                );
            } else if (fieldDef.type === "properties") {
                subResult = await _loadPath(
                    followRelationalProperties ? resModel : "*",
                    await _loadPropertyDefinitions(
                        /** @type {string} */ (resModel),
                        fieldDefs,
                        name,
                    ),
                    remainingNames,
                    followRelationalProperties,
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
            if (typeof path !== "string" || !path) {
                throw new Error(`Invalid path: ${path}`);
            }
            const fieldDefs = await loadFields(resModel);
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
            const name = names[names.length - 1];
            const modelInfo = modelsInfo[modelsInfo.length - 1];
            return {
                resModel: modelInfo.resModel,
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
                const lastName = names[names.length - 1];
                const lastFieldDef =
                    modelsInfo[modelsInfo.length - 1].fieldDefs[lastName];
                if (
                    !lastFieldDef ||
                    ["properties", "properties_definition"].includes(lastFieldDef.type)
                ) {
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
