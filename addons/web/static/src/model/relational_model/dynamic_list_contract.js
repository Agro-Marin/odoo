// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/dynamic_list_contract */

/**
 * The `DynamicList` operations an owner or a sibling invokes.
 *
 * Third companion to `record_contract.js` and `static_list_contract.js`, and the
 * smallest of the three — which is the point. `StaticList`'s contract had to be
 * carved out of 86 accesses to 25 externally-reached privates, most of them
 * working memory. `DynamicList` is reached **five times, for four members, and
 * every one of them is an operation**:
 *
 *   `relational_model.js`   `root._multiSave(record, changes)`
 *   `dynamic_group_list.js` `targetGroup.list._resequence(...)`   (x2)
 *   `record.js`             `this.model.root._onRecordDeselected?.()`
 *   `record_validator.js`   `record.model.root._isRecordToDiscard?.(record)`
 *
 * Applying `static_list_contract.js`'s distinction, all five are category (1) —
 * a caller asking the list to do something and not caring how — and none is
 * category (2), a satellite sharing the list's internal state. So this file has
 * no `INTERNAL_STATE_REACHED` companion: there is no residue to make countable.
 * If one ever appears, it belongs in a list beside this one rather than quietly
 * inside it.
 *
 * **Why two of the five call sites use `?.`** — and why that is not a sign the
 * contract is optional. `record.js` and `record_validator.js` reach for
 * `model.root`, which is a `DynamicList` only when the view is a list or kanban;
 * for a form it is a `RelationalRecord`, which declares neither member. The
 * optional call guards against the *root being a different class*, not against a
 * `DynamicList` lacking the member. Every entry below is declared unconditionally
 * in `dynamic_list.js`, and `test_record_contract_agreement.py` holds this list
 * and the typedef to the same names.
 *
 * @type {string[]}
 */
export const DYNAMIC_LIST_OWNER_SURFACE = [
    // multi-edit, driven by the model
    "_multiSave",
    // ordering, driven by a sibling group's drag-and-drop
    "_resequence",
    // selection queries a root answers for a record that is deciding about itself
    "_isRecordToDiscard",
    "_onRecordDeselected",
];

/**
 * The owner-facing surface as a type, for modules that drive a dynamic list
 * rather than implement one. Reaching past it is a typecheck failure instead of
 * an invisible entry in the private-access budget.
 *
 * `DYNAMIC_LIST_OWNER_SURFACE` and this typedef must name the same members;
 * `tooling/architecture/test_record_contract_agreement.py` checks that.
 *
 * @typedef {{
 *  _multiSave: (editedRecord: any, changes: any) => Promise<any>,
 *  _resequence: (originalList: any[], resModel: string, movedId: any, targetId: any) => Promise<any>,
 *  _isRecordToDiscard: (record: any) => boolean,
 *  _onRecordDeselected: () => void,
 * }} DynamicListContract
 */
