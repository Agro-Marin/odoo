// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/relational_model_contract */

/**
 * What a datapoint may ask of the model that owns it.
 *
 * Third of the model layer's contracts, after `record_contract.js` and
 * `static_list_contract.js`, and the cleanest of the three. `RelationalModel`
 * leaks **7 privates over 53 accesses**, and unlike `StaticList` every one of
 * them is an OPERATION a datapoint invokes upward — `_patchConfig`,
 * `_askChanges`, `_loadRecords`. None is working memory a helper kept reaching
 * for after being split out of the class, so there is no
 * `INTERNAL_STATE_REACHED` counterpart here. The direction is what makes the
 * difference: `Record` and `StaticList` leak sideways, to helpers extracted
 * from them; `RelationalModel` is reached *upward*, by the datapoints it owns,
 * which is a relationship rather than a decomposition artefact.
 *
 * The public half is large because it is genuinely used: `mutex` alone is read
 * 38 times across `record`, `static_list` and `dynamic_list`, since it is how
 * datapoints serialise work against their model. A contract omitting it would
 * force every consumer to widen back to the class, which is the failure mode
 * that made `static_list_contract` grow its public half too.
 *
 * WHAT THIS DOES NOT BUY. `orm` and `root` are on the list, and through either
 * you can reach most of the graph again. Declaring them is still worth doing —
 * a member absent from this list is a typecheck failure, so the surface can
 * only grow by an explicit edit here — but do not read an annotation against
 * this contract as isolation the way `RecordContract` gives it. It bounds the
 * surface; it does not narrow the reach.
 *
 * @type {string[]}
 */
export const RELATIONAL_MODEL_SURFACE = [
    // public shape a datapoint reads
    "Class",
    "activeIdsLimit",
    "closeUrgentSaveNotification",
    "hooks",
    "initialLimit",
    "load",
    "multiEdit",
    "multiEditDispatch",
    "mutex",
    "orm",
    "root",
    "urgentSave",
    "useSampleModel",
    "useSendBeaconToSaveUrgently",
    // operations a datapoint invokes upward
    "_askChanges",
    "_loadNewRecord",
    "_loadRecords",
    "_onchange",
    "_patchConfig",
    "_reloadWithConfig",
    "_updateSimilarRecords",
];

/**
 * The same surface as a type, for datapoints declaring what they ask of their
 * model. Signatures are read off `relational_model.js`, not inferred: the
 * static-list contract was written from measured accesses with guessed
 * signatures, and the first thing typechecking a real call site did was catch
 * `_commitSave()` actually taking a `serverValue`.
 *
 * `RELATIONAL_MODEL_SURFACE` and this typedef must name the same members;
 * `tooling/architecture/test_record_contract_agreement.py` checks that.
 *
 * @typedef {{
 *  Class: any,
 *  activeIdsLimit: number | undefined,
 *  closeUrgentSaveNotification: (() => void) | undefined,
 *  hooks: { lifecycle: Record<string, any>, ui: Record<string, any> },
 *  initialLimit: number,
 *  load: (params?: any) => Promise<any>,
 *  multiEdit: boolean | undefined,
 *  multiEditDispatch: (record: any, changes: Record<string, any>) => any,
 *  mutex: any,
 *  orm: any,
 *  root: any,
 *  urgentSave: any,
 *  useSampleModel: boolean,
 *  useSendBeaconToSaveUrgently: boolean | undefined,
 *  _askChanges: () => Promise<any>,
 *  _loadNewRecord: (config: any, params?: any) => Promise<any>,
 *  _loadRecords: (config: any, evalContext?: any) => Promise<any>,
 *  _onchange: (config: any, params?: any) => Promise<any>,
 *  _patchConfig: (config: any, patch: any) => any,
 *  _reloadWithConfig: (config: any, patch: any, options?: { commit?: boolean }) => Promise<any>,
 *  _updateSimilarRecords: (reloadedRecord: any, serverValues: any) => void,
 * }} RelationalModelContract
 */
