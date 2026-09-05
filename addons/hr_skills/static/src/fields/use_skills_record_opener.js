/** @odoo-module native */
import { useX2ManyCrud } from "@web/fields/relational/x2many_crud";
import { useOpenX2ManyRecord } from "@web/fields/relational/x2many_dialog";

/**
 * Both skill widgets open their lines in the same dialog and differ only in
 * its title. Call from setup(); it installs the field's _openRecord.
 *
 * @param {import("@web/fields/relational/x2many").X2ManyField} field
 * @param {() => string} getTitle
 */
export function useSkillsRecordOpener(field, getTitle) {
    const { saveAndLink, updateRecord } = useX2ManyCrud(
        () => field.list,
        field.isMany2Many,
    );
    const openRecord = useOpenX2ManyRecord({
        resModel: field.list.resModel,
        activeField: field.activeField,
        activeActions: field.activeActions,
        getList: () => field.list,
        saveRecord: saveAndLink,
        updateRecord,
        withParentId: field.props.widget !== "many2many",
    });
    field._openRecord = (params) => openRecord({ ...params, title: getTitle() });
}
