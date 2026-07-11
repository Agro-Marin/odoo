// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/x2many_crud - OWL hook providing CRUD operations (save, update, remove) for x2many fields */

/**
 * Hook providing CRUD operations for x2many fields.
 *
 * @param {Function} getList - Returns the current x2many list
 * @param {boolean} isMany2Many - Whether the field is many2many (vs one2many)
 * @returns {{linkRecords: Function|undefined, saveAndLink: Function, saveRecord: Function, updateRecord: Function, removeRecord: Function}}
 */
export function useX2ManyCrud(getList, isMany2Many) {
    /** Links existing records by id (many2many only). @type {Function|undefined} */
    let linkRecords;
    /** Persists a Record datapoint and adds it to the list. @type {Function} */
    let saveAndLink;
    if (isMany2Many) {
        linkRecords = (resIds) => getList().addAndRemove({ add: resIds });
        saveAndLink = async (record) => {
            await record.save({ reload: false });
            return getList().linkTo(record.resId);
        };
    } else {
        saveAndLink = async (record) => getList().validateExtendedRecord(record);
    }

    /**
     * @deprecated Polymorphic on argument shape: use `linkRecords(resIds)` or
     *  `saveAndLink(record)` instead. Kept for downstream compatibility.
     */
    const saveRecord = (object) =>
        isMany2Many && Array.isArray(object)
            ? linkRecords(object)
            : saveAndLink(object);

    const updateRecord = async (record) => {
        if (isMany2Many) {
            await record.save();
        }
        return getList().validateExtendedRecord(record);
    };

    const removeRecord = (record) => {
        const list = getList();
        if (isMany2Many) {
            return list.forget(record);
        }
        return list.delete(record);
    };

    return {
        linkRecords,
        saveAndLink,
        saveRecord,
        updateRecord,
        removeRecord,
    };
}

/**
 * Hook to add an inline record to an x2many list, with debounce protection.
 *
 * @param {Object} params
 * @param {Function} params.addNew - Function to add a new record to the list
 * @returns {Function} addInlineRecord
 */
export function useAddInlineRecord({ addNew }) {
    let creatingRecord = false;

    async function addInlineRecord({ context, editable }) {
        if (!creatingRecord) {
            creatingRecord = true;
            try {
                await addNew({ context, mode: "edit", position: editable });
            } finally {
                creatingRecord = false;
            }
        }
    }
    return addInlineRecord;
}
