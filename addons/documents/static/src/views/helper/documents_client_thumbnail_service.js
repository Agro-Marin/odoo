/** @odoo-module native */
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { Deferred, Mutex } from "@web/core/utils/concurrency";

import { getPdfThumbnail, getWebpThumbnail } from "./documents_client_thumbnail_service_utils.js";

const THUMBNAIL_WIDTH = 200;
const THUMBNAIL_HEIGHT = 140;

/**
 * - If  an error occurs during thumbnail generation, the thumbnail will no longer be processed
 *   by any client until the file is modified.
 * - If the content is not accessible, the process is ignored
 *   and the thumbnail will be reprocessed the next time.
 * - Otherwise, the thumbnail is set.
 */
export const documentsClientThumbnailService = {
    start(env) {
        let pdfEnabled = true;
        const mutex = new Mutex();
        /** res ids whose thumbnail generation is currently queued or running. */
        const queued = new Set();

        const makeThumbnail = async (record) => {
            if (record.data.thumbnail_status !== "client_generated") {
                return;
            }
            let thumbnail = undefined;
            if (record.isPdf()) {
                if (!pdfEnabled) {
                    return;
                }
                let isPdfValid;
                ({ thumbnail, isPdfValid, pdfEnabled } = await this._getPdfThumbnail(
                    record,
                    THUMBNAIL_WIDTH,
                    THUMBNAIL_HEIGHT
                ));
                if (isPdfValid === false) {
                    // The route answered 415: whatever the document carries, the
                    // server will not render a first page from it, now or ever.
                    // `false` marks it failed below -- the same policy the webp
                    // branch applies to its definitive failures. Leaving the
                    // status at `client_generated` had every later page load
                    // re-request it, for a thumbnail that can never arrive.
                    thumbnail = false;
                }
            } else if (record.data.mimetype === "image/webp") {
                try {
                    const img = await this._getLoadedImage(record);
                    ({ thumbnail } = await getWebpThumbnail(
                        img,
                        THUMBNAIL_WIDTH,
                        THUMBNAIL_HEIGHT
                    ));
                } catch (error) {
                    // 403 means the content is not (yet) accessible: leave the
                    // status as client_generated to retry later. Any other
                    // failure (fetch/network error, corrupt or undecodable image)
                    // is definitive — mark it failed so it is not re-fetched on
                    // every card remount.
                    if (error.status === 403) {
                        return;
                    }
                    thumbnail = false;
                }
            }
            if (thumbnail !== undefined) {
                await rpc(`/documents/document/${record.resId}/update_thumbnail`, {
                    thumbnail,
                });
                record.data.thumbnail_status = thumbnail ? "present" : "error";
            }
        };

        return {
            enqueueRecords(records) {
                if (env.isSmall) {
                    return;
                }
                for (const record of records) {
                    if (
                        record.data.thumbnail_status === "client_generated" &&
                        !queued.has(record.resId)
                    ) {
                        // One generation per record at a time. Every card enqueues
                        // itself on mount and the same record mounts more than once
                        // per load, so without this each thumbnail was fetched and
                        // rendered twice. Released in the `finally` below, so a
                        // record whose file changes later is generated again.
                        queued.add(record.resId);
                        mutex.exec(async () => {
                            try {
                                await makeThumbnail(record);
                            } catch {
                                // Thumbnails are cosmetic and generated in the
                                // background, and `mutex.exec` hands back a promise
                                // nobody holds -- an escaping rejection would reach
                                // the webclient's global error dialog. The status is
                                // left untouched so the next load retries.
                            } finally {
                                queued.delete(record.resId);
                            }
                        });
                    }
                }
                return mutex.getUnlockedDef();
            },
        };
    },
    /**
     * Seam over the shared pdf.js helper, mirroring `_getLoadedImage`: both
     * fetch-and-decode steps are reachable from a test without a real document.
     */
    _getPdfThumbnail(record, width, height) {
        return getPdfThumbnail(record, width, height);
    },
    async _getLoadedImage(record) {
        // Fetch first (rather than assigning the URL straight to img.src) so the
        // HTTP status is observable: a 403 must be retried later, other failures
        // are permanent. img.onerror only yields an Event with no status.
        const response = await fetch(
            `/documents/content/${encodeURIComponent(record.data.access_token)}`
        );
        if (!response.ok) {
            const error = new Error(`Thumbnail fetch failed (${response.status})`);
            error.status = response.status;
            throw error;
        }
        const objectUrl = URL.createObjectURL(await response.blob());
        try {
            const imagePromise = new Deferred();
            const img = new Image();
            img.onerror = (e) => imagePromise.reject(e);
            img.onload = () => imagePromise.resolve(img);
            img.src = objectUrl;
            return await imagePromise;
        } finally {
            URL.revokeObjectURL(objectUrl);
        }
    },
};

registry.category("services").add("documents_client_thumbnail", documentsClientThumbnailService);
