// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { humanNumber } from "@web/core/utils/format/numbers";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

/** @import { Services } from "services" */

export const DEFAULT_MAX_FILE_SIZE = 128 * 1024 * 1024;

/**
 * @param {number} fileSize
 * @param {{ add: (message: string, options?: any) => () => void }} notificationService
 * @returns {boolean}
 */
export function checkFileSize(fileSize, notificationService) {
    const maxUploadSize = session.max_file_upload_size || DEFAULT_MAX_FILE_SIZE;
    if (fileSize > maxUploadSize) {
        notificationService.add(
            _t(
                "The selected file (%(size)sB) is larger than the maximum allowed file size (%(maxSize)sB).",
                {
                    size: humanNumber(fileSize),
                    maxSize: humanNumber(maxUploadSize),
                },
            ),
            {
                type: "danger",
            },
        );
        return false;
    }
    return true;
}

/**
 * @param {File} file
 * @param {string | undefined} allowedMIMETypes
 * @param {{ add: (message: string, options?: any) => () => void }} notificationService
 * @returns {boolean}
 */
export function checkFileType(file, allowedMIMETypes, notificationService) {
    if (!allowedMIMETypes) {
        return true;
    }
    const allowed = allowedMIMETypes
        .split(",")
        .map((type) => type.trim())
        .filter(Boolean);
    const type = file.type;
    const isAllowed =
        Boolean(type) &&
        allowed.some(
            (allowedType) =>
                allowedType === type ||
                (allowedType.endsWith("/*") &&
                    type.startsWith(allowedType.slice(0, -1))),
        );
    if (!isAllowed) {
        notificationService.add(
            _t(`Oops! '%(fileName)s' didn’t upload since its format isn’t allowed.`, {
                fileName: file.name,
            }),
            {
                type: "danger",
            },
        );
        return false;
    }
    return true;
}

/**
 * @returns {function}
 */
export function useFileUploader() {
    const http = useService("http");
    const notification = useService("notification");
    /**
     * @param {string} route
     * @param {Record<string, any>} params
     */
    return async (route, params) => {
        if (params.ufile && params.ufile.length) {
            for (const file of params.ufile) {
                if (!checkFileSize(file.size, notification)) {
                    return null;
                }
            }
        } else if (params.file) {
            if (!checkFileSize(params.file.size, notification)) {
                return null;
            }
        }
        const fileData = await http.post(route, params, "text", { rejectHtml: true });
        const parsedFileData = JSON.parse(fileData);
        if (parsedFileData.error) {
            throw new Error(parsedFileData.error);
        }
        return parsedFileData;
    };
}

/**
 * @param {Blob} blob
 * @param {Record<string, any>} [params]
 */
export function resizeBlobImg(blob, params = {}) {
    if (!blob.type || !blob.type.startsWith("image/")) {
        return Promise.reject(
            new Error(_t("The file is not an image, resizing is not possible")),
        );
    }
    const { width, height, offsetX, offsetY } = {
        width: 256,
        height: 256,
        offsetX: 0.5,
        offsetY: 0.5,
        ...params,
    };
    return new Promise((resolve, reject) => {
        const img = new Image();
        const objectUrl = URL.createObjectURL(blob);
        img.onload = () => {
            URL.revokeObjectURL(objectUrl);
            if (width < img.width || height < img.height) {
                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                const ctx = /** @type {CanvasRenderingContext2D} */ (
                    canvas.getContext("2d")
                );
                ctx.imageSmoothingQuality = "high";
                ctx.imageSmoothingEnabled = true;

                const srcRatio = img.width / img.height;
                const dWidth = Math.min(Math.floor(height * srcRatio), width);
                const dHeight = Math.min(Math.floor(width / srcRatio), height);

                const dx = Math.round((width - dWidth) * offsetX);
                const dy = Math.round((height - dHeight) * offsetY);

                ctx.drawImage(
                    img,
                    0,
                    0,
                    img.width,
                    img.height,
                    dx,
                    dy,
                    dWidth,
                    dHeight,
                );
                canvas.toBlob(resolve);
            } else {
                resolve(blob);
            }
        };
        img.onerror = () => {
            URL.revokeObjectURL(objectUrl);
            reject(new Error(_t("The resizing of the image failed")));
        };
        img.src = objectUrl;
    });
}
