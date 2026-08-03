// @ts-check
/** @odoo-module native */

/** @module @web/core/network */

/**
 * The network module's published interface.
 *
 * Everything under `core/network/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 5 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `network/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/core/network` to
 * `/web/static/src/core/network.js` by appending `.js`, with no directory-index step.
 */

export { download, downloadFile } from "./network/download.js";
export { get, post } from "./network/http_service.js";
export { onModelMutation } from "./network/model_mutation.js";
export { ORM } from "./network/orm_service.js";
export {
    ConnectionAbortedError,
    ConnectionLostError,
    InvalidResponseError,
    rpc,
    rpcBus,
    RPCError,
} from "./network/rpc.js";
