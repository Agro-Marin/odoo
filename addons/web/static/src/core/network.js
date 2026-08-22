// @ts-check
/** @odoo-module native */

export { x2ManyCommands } from "./network/commands.js";
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
