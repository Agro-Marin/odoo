/** @odoo-module native */
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { AUTOCLOSE_DELAY } from "@html_editor/main/media/media_dialog/upload_progress_toast/upload_service";

export const unsplashService = {
    dependencies: ["upload"],
    async start(env, { upload }) {
        const _cache = {};
        return {
            async uploadUnsplashRecords(records, { resModel, resId }, onUploaded) {
                upload.incrementId();
                const file = upload.addFile({
                    id: upload.fileId,
                    name:
                        records.length > 1
                            ? _t("Uploading %(count)s '%(query)s' images.", {
                                  count: records.length,
                                  query: records[0].query,
                              })
                            : _t("Uploading '%s' image.", records[0].query),
                });

                try {
                    const urls = {};
                    for (const record of records) {
                        const _1920Url = new URL(record.urls.regular);
                        _1920Url.searchParams.set("w", "1920");
                        urls[record.id] = {
                            url: _1920Url.href,
                            download_url: record.links.download_location,
                            description: record.alt_description,
                        };
                    }

                    // No upload progress to report, and there never really was.
                    // This posts a small JSON of image URLs; the server is what
                    // downloads the images, so the old XMLHttpRequest
                    // `upload.progress` listener was measuring the request body
                    // and reached 100% immediately. That listener was passed to
                    // `rpc()` as an `{ xhr }` setting, which stopped being
                    // honoured when rpc moved to `fetch()` (34d4d0640a6) and
                    // became a hard error once settings were validated
                    // (8e7a2fc2e8e) -- so every Unsplash upload threw
                    // `Invalid RPC setting(s): "xhr"` before sending anything.
                    // fetch() cannot report request-body progress, and there is
                    // nothing meaningful to report here anyway: mark the request
                    // as sent and let `uploaded` signal the real completion.
                    file.progress = 100;
                    const attachments = await rpc("/web_unsplash/attachment/add", {
                        res_id: resId,
                        res_model: resModel,
                        unsplashurls: urls,
                        query: records[0].query,
                    });

                    if (attachments.error) {
                        file.hasError = true;
                        file.errorMessage = attachments.error;
                    } else {
                        file.uploaded = true;
                        await onUploaded(attachments);
                    }
                    setTimeout(() => upload.deleteFile(file.id), AUTOCLOSE_DELAY);
                } catch (error) {
                    file.hasError = true;
                    setTimeout(() => upload.deleteFile(file.id), AUTOCLOSE_DELAY);
                    throw error;
                }
            },

            async getImages(query, offset = 0, pageSize = 30, orientation) {
                const from = offset;
                const to = offset + pageSize;
                // Use orientation in the cache key to not show images in cache
                // when using the same query word but changing the orientation
                let cachedData = orientation ? _cache[query + orientation] : _cache[query];

                if (
                    cachedData &&
                    (cachedData.images.length >= to ||
                        (cachedData.totalImages !== 0 && cachedData.totalImages < to))
                ) {
                    return {
                        images: cachedData.images.slice(from, to),
                        isMaxed: to > cachedData.totalImages,
                    };
                }
                cachedData = await this._fetchImages(query, orientation);
                return {
                    images: cachedData.images.slice(from, to),
                    isMaxed: to > cachedData.totalImages,
                };
            },
            /**
             * Fetches images from unsplash and stores it in cache
             */
            async _fetchImages(query, orientation) {
                const key = orientation ? query + orientation : query;
                if (!_cache[key]) {
                    _cache[key] = {
                        images: [],
                        maxPages: 0,
                        totalImages: 0,
                        pageCached: 0,
                    };
                }
                const cachedData = _cache[key];
                const payload = {
                    query: query,
                    page: cachedData.pageCached + 1,
                    per_page: 30, // max size from unsplash API
                };
                if (orientation) {
                    payload.orientation = orientation;
                }
                const result = await rpc("/web_unsplash/fetch_images", payload);
                if (result.error) {
                    return Promise.reject(result.error);
                }
                cachedData.pageCached++;
                cachedData.images.push(...result.results);
                cachedData.maxPages = result.total_pages;
                cachedData.totalImages = result.total;
                return cachedData;
            },
        };
    },
};

registry.category("services").add("unsplash", unsplashService);
