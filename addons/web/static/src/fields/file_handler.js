/** @odoo-module native */

/**
 * Compatibility re-export: FileUploader moved to
 * @web/core/file_upload/file_handler so that frontend/public bundles get it
 * from web core instead of cherry-picking backend fields code. Keep this shim
 * until downstream repositories (enterprise) migrate their imports, then
 * delete it.
 */
export { FileUploader } from "@web/core/file_upload/file_handler";
