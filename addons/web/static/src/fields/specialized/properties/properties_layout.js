// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/properties_layout */

/**
 * @typedef {{ name: string, type: string, string?: string, value?: any,
 *             fold_by_default?: boolean, definition_changed?: boolean,
 *             [key: string]: any }} PropertyDefinition
 * @typedef {{ title: string | null, name: string | null,
 *             elements: PropertyDefinition[], isFolded?: boolean,
 *             invisibleLabel?: boolean, columnSeparator?: boolean }} PropertyGroup
 */

/** @param {PropertyDefinition} property */
const isSeparator = (property) => property.type === "separator";

/**
 * @param {PropertyDefinition} separator
 * @returns {boolean}
 */
function isSeparatorFolded(separator) {
    return separator.value ?? separator.fold_by_default;
}

/**
 * @param {PropertyDefinition[]} propertiesList
 * @param {number} columnsCount
 * @returns {PropertyGroup[]}
 */
export function groupProperties(propertiesList, columnsCount) {
    /** @type {PropertyGroup[]} */
    const groupedProperties =
        !propertiesList.length || !isSeparator(propertiesList[0])
            ? [{ title: null, name: null, elements: [], invisibleLabel: true }]
            : [];

    for (const property of propertiesList) {
        if (isSeparator(property)) {
            groupedProperties.push({
                title: property.string ?? null,
                name: property.name,
                elements: [],
                isFolded: isSeparatorFolded(property),
            });
        } else {
            /** @type {PropertyGroup} */ (groupedProperties.at(-1)).elements.push(
                property,
            );
        }
    }

    if (groupedProperties.length !== 1 || groupedProperties[0].isFolded) {
        return groupedProperties;
    }

    groupedProperties[0].elements = [];
    groupedProperties[0].invisibleLabel =
        !propertiesList.length || !isSeparator(propertiesList[0]);
    for (let col = 1; col < columnsCount; ++col) {
        groupedProperties.push({
            title: null,
            name: null,
            columnSeparator: true,
            elements: [],
            invisibleLabel: true,
        });
    }
    const properties = propertiesList.filter((property) => !isSeparator(property));
    properties.forEach((property, index) => {
        const columnIndex = Math.floor((index * columnsCount) / properties.length);
        groupedProperties[columnIndex].elements.push(property);
    });
    return groupedProperties;
}

/**
 * @param {PropertyDefinition[]} propertiesValues
 * @param {number} targetIndex
 * @returns {PropertyDefinition | undefined}
 */
export function findEnclosingSeparator(propertiesValues, targetIndex) {
    return propertiesValues.findLast(
        (property, index) => isSeparator(property) && index <= targetIndex,
    );
}

/**
 * @param {PropertyDefinition[]} propertiesValues
 * @param {string} propertyName
 * @param {"up" | "down"} direction
 * @returns {{ status: "moved", targetIndex: number }
 *          | { status: "at-edge", direction: "up" | "down" }
 *          | { status: "not-found" }}
 */
export function movePropertyByOffset(propertiesValues, propertyName, direction) {
    const propertyIndex = propertiesValues.findIndex(
        (property) => property.name === propertyName,
    );
    if (propertyIndex < 0) {
        return { status: "not-found" };
    }
    const targetIndex = propertyIndex + (direction === "down" ? 1 : -1);
    if (targetIndex < 0 || targetIndex >= propertiesValues.length) {
        return { status: "at-edge", direction };
    }
    const property = propertiesValues[targetIndex];
    propertiesValues[targetIndex] = propertiesValues[propertyIndex];
    propertiesValues[propertyIndex] = property;
    propertiesValues[propertyIndex].definition_changed = true;
    return { status: "moved", targetIndex };
}

/**
 * @param {PropertyDefinition[]} propertiesValues
 * @param {Object} params
 * @param {string} params.propertyName
 * @param {string | null} params.toPropertyName
 * @param {boolean} [params.moveBefore]
 * @param {number} params.columnsCount
 * @param {(type: string) => string} params.generateName
 * @param {(index: number) => string} params.separatorTitle
 * @returns {PropertyDefinition[] | null}
 */
export function movePropertyTo(
    propertiesValues,
    {
        propertyName,
        toPropertyName,
        moveBefore,
        columnsCount,
        generateName,
        separatorTitle,
    },
) {
    let fromIndex = propertiesValues.findIndex(
        (property) => property.name === propertyName,
    );
    let toIndex = propertiesValues.findIndex(
        (property) => property.name === toPropertyName,
    );
    if (fromIndex < 0) {
        return null;
    }
    const columnSize = Math.ceil(propertiesValues.length / columnsCount);

    if (
        columnsCount > 1 &&
        !propertiesValues.some((p, index) => index !== 0 && isSeparator(p)) &&
        Math.floor(fromIndex / columnSize) !== Math.floor(toIndex / columnSize)
    ) {
        /** @type {string[]} */
        const newSeparators = [];
        for (let col = 0; col < columnsCount; ++col) {
            const separatorIndex = columnSize * col + newSeparators.length;

            if (propertiesValues[separatorIndex]?.type === "separator") {
                propertiesValues[separatorIndex].value = false;
                newSeparators.push(propertiesValues[separatorIndex].name);
                continue;
            }
            const newSeparator = {
                type: "separator",
                string: separatorTitle(col + 1),
                name: generateName("separator"),
                value: false,
            };
            newSeparators.push(newSeparator.name);
            propertiesValues.splice(separatorIndex, 0, newSeparator);
        }
        toPropertyName =
            toPropertyName || /** @type {any} */ (propertiesValues.at(-1)).name;

        fromIndex = propertiesValues.findIndex(
            (property) => property.name === propertyName,
        );
        toIndex = propertiesValues.findIndex(
            (property) => property.name === toPropertyName,
        );
    }

    if (moveBefore) {
        toIndex--;
    }
    if (toIndex < fromIndex) {
        toIndex++;
    }
    propertiesValues.splice(toIndex, 0, propertiesValues.splice(fromIndex, 1)[0]);
    propertiesValues[0].definition_changed = true;
    return propertiesValues;
}

/**
 * @param {PropertyDefinition[]} propertiesValues
 * @param {string} propertyName
 * @param {string | null} toPropertyName
 * @returns {PropertyDefinition[] | null}
 * @throws {Error}
 */
export function moveGroupTo(propertiesValues, propertyName, toPropertyName) {
    const fromIndex = propertiesValues.findIndex(
        (property) => property.name === propertyName,
    );
    const toIndex = propertiesValues.findIndex(
        (property) => property.name === toPropertyName,
    );
    if (fromIndex < 0) {
        return null;
    }
    if (
        !isSeparator(propertiesValues[fromIndex]) ||
        (toIndex >= 0 && !isSeparator(propertiesValues[toIndex]))
    ) {
        throw new Error("Something went wrong");
    }

    const getNextSeparatorIndex = (/** @type {number} */ startIndex) => {
        const nextSeparatorIndex = propertiesValues.findIndex(
            (property, index) => isSeparator(property) && index > startIndex,
        );
        return nextSeparatorIndex < 0 ? propertiesValues.length : nextSeparatorIndex;
    };
    const groupSize = getNextSeparatorIndex(fromIndex) - fromIndex;
    let targetIndex = getNextSeparatorIndex(toIndex);
    if (targetIndex > fromIndex) {
        targetIndex -= groupSize;
    }
    propertiesValues.splice(
        targetIndex,
        0,
        ...propertiesValues.splice(fromIndex, groupSize),
    );
    propertiesValues[0].definition_changed = true;
    return propertiesValues;
}
