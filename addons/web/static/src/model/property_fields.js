// @ts-check
/** @odoo-module native */

import { invalidateAggregateSpecs } from "./relational_model/field_values.js";

/** @import { Field } from "@web/model/types" */
/** @import { ServiceFactories as Services } from "services" */

/**
 * A property is addressed as `<properties field>.<property name>` and behaves,
 * everywhere downstream, like a field of the record. Two loaders used to build
 * that synthetic field independently -- one for graph/pivot, one for the
 * relational model's group-by path -- and they disagreed on the shape of
 * `relatedPropertyField`, which is the key `list_column_utils` filters property
 * columns on. The relational one wrote `{ fieldName }` where every consumer and
 * `model/types.js` read `.name`, so grouping a list by a property dropped that
 * property's columns from the list entirely.
 *
 * One builder, one shape. `{ name, id?, displayName? }` is what `types.js`
 * declares; `id`/`displayName` name the parent *record* and are known only where
 * a record is in hand, so they are filled in by `record_properties.js` on the
 * activeField rather than here.
 */

/**
 * @param {string} propertyFullName `"<properties field>.<property name>"`
 * @param {Record<string, any> | undefined | false} definition
 * @returns {Field}
 */
export function describePropertyDefinitionAsField(propertyFullName, definition) {
    const [parentFieldName] = propertyFullName.split(".");
    const described = definition && definition.type ? definition : { type: "char" };
    return {
        ...described,
        type: String(described.type),
        name: propertyFullName,
        propertyName: definition ? definition.name : undefined,
        relation: definition ? definition.comodel : undefined,
        relatedPropertyField: { name: parentFieldName },
    };
}

/**
 * Reads one property definition from the server and installs it in `fields`.
 *
 * A definition that cannot be read degrades to a `char` field rather than
 * failing the load: the usual cause is a property that was removed while a
 * saved group-by still names it, and losing the whole view over that is worse
 * than showing the column as text.
 *
 * @param {Services["orm"]} orm
 * @param {string} resModel
 * @param {Record<string, any>} context
 * @param {Record<string, Field>} fields mutated in place
 * @param {string} propertyFullName
 * @returns {Promise<void>}
 */
export async function addPropertyFieldDef(
    orm,
    resModel,
    context,
    fields,
    propertyFullName,
) {
    let definition;
    try {
        definition = await orm.call(
            resModel,
            "get_property_definition",
            [propertyFullName],
            { context },
        );
    } catch {
        definition = undefined;
    }
    fields[propertyFullName] = describePropertyDefinitionAsField(
        propertyFullName,
        definition,
    );
    invalidateAggregateSpecs(fields);
}

/**
 * @param {Services["orm"]} orm
 * @param {string} resModel
 * @param {Record<string, any>} context
 * @param {Record<string, Field>} fields mutated in place
 * @param {Iterable<string>} groupBy
 * @returns {Promise<void>}
 */
export async function addPropertyFieldDefs(orm, resModel, context, fields, groupBy) {
    const proms = [];
    for (const groupByName of groupBy) {
        if (groupByName in fields) {
            continue;
        }
        const [parentFieldName] = groupByName.split(".");
        if (fields[parentFieldName]?.type !== "properties") {
            continue;
        }
        proms.push(addPropertyFieldDef(orm, resModel, context, fields, groupByName));
    }
    await Promise.all(proms);
}
