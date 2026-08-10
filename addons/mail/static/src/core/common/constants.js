/** @odoo-module native */
/**
 * Timing constants shared by the store, the model layer and the tests.
 *
 * These are deliberately NOT statics on `Store`. A model file that needs one
 * would otherwise have to import `store_service.js`, which imports
 * `_models.js`, which imports the model files back — and that edge was this
 * module's only entry on `js_cycle_check`'s tolerated list. Two files
 * (`res_partner_model`, `mail_guest_model`) pulled in the whole Store class to
 * read a single number.
 *
 * Keep this module a leaf: it must import nothing, or the cycle returns by
 * another route.
 */

/** Debounce before a batch of queued fetch params is sent as one RPC. */
export const FETCH_DATA_DEBOUNCE_DELAY = 1;

/**
 * How long the *receiving* side keeps showing "is typing" without a refresh.
 * The sending side must re-notify well below this — see
 * `discuss/typing/common/composer_patch.js`.
 */
export const OTHER_LONG_TYPING = 60000;

/** Debounce before queued `im_status` presence requests are sent. */
export const IM_STATUS_DEBOUNCE_DELAY = 1000;
