// @ts-check
/** @odoo-module native */

/**
 * @overload
 * @param {Function} getList
 * @param {true} isMany2Many
 * @returns {{linkRecords: Function, saveAndLink: Function, updateRecord: Function, removeRecord: Function}}
 */
/**
 * @overload
 * @param {Function} getList
 * @param {boolean} isMany2Many
 * @returns {{linkRecords: Function|undefined, saveAndLink: Function, updateRecord: Function, removeRecord: Function}}
 */
/**
 * @param {Function} getList
 * @param {boolean} isMany2Many
 * @returns {any}
 */
export function useX2ManyCrud(getList, isMany2Many) {
    /** @type {Function|undefined} */
    let linkRecords;
    /** @type {Function} */
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
        updateRecord,
        removeRecord,
    };
}

/**
 * @param {Object} params
 * @param {Function} params.addNew
 * @returns {Function}
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
