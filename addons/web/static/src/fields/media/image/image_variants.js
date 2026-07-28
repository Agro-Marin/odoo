// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/image/image_variants - Webp re-encoding and resized-variant attachments for uploaded images */

/** Longest-edge sizes a smaller variant is generated for, when the source exceeds them. */
const VARIANT_SIZES = [1920, 1024, 512, 256, 128];

/**
 * Uploaded types that are never re-encoded: gif would lose its animation,
 * svg is not raster, and webp is already the target format.
 */
const NON_CONVERTIBLE_TYPES = ["image/gif", "image/svg+xml", "image/webp"];

/**
 * The browser could not decode the uploaded bytes.
 *
 * Raised rather than notifying from here, so this module stays free of UI
 * concerns and the caller decides how to surface it. Anything else escaping
 * these functions (an ORM failure, say) is a genuine error and must keep
 * propagating.
 */
export class ImageDecodeError extends Error {}

/**
 * @param {string} src a `data:` URL
 * @returns {Promise<HTMLImageElement>}
 */
async function decodeImage(src) {
    const image = document.createElement("img");
    image.src = src;
    try {
        await image.decode();
    } catch (error) {
        throw new ImageDecodeError("the uploaded image could not be decoded", {
            cause: error,
        });
    }
    return image;
}

/** @returns {boolean} whether this browser can encode a canvas as webp. */
function canEncodeWebp() {
    return document
        .createElement("canvas")
        .toDataURL("image/webp")
        .startsWith("data:image/webp");
}

/**
 * Full-size copy, drawn without scaling or resampling — used purely to
 * re-encode the same pixels into another container format.
 *
 * @param {HTMLImageElement} image
 * @returns {HTMLCanvasElement}
 */
function drawFullSize(image) {
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    /** @type {any} */ (canvas.getContext("2d")).drawImage(image, 0, 0);
    return canvas;
}

/**
 * Scaled copy. Unlike {@link drawFullSize} this resamples, so it asks for
 * high-quality smoothing and pre-fills transparent to keep the alpha channel
 * of formats that have one.
 *
 * @param {HTMLImageElement} image
 * @param {number} ratio
 * @returns {HTMLCanvasElement}
 */
function drawScaled(image, ratio) {
    const canvas = document.createElement("canvas");
    canvas.width = image.width * ratio;
    canvas.height = image.height * ratio;
    const ctx = /** @type {any} */ (canvas.getContext("2d"));
    ctx.fillStyle = "transparent";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(
        image,
        0,
        0,
        image.width,
        image.height,
        0,
        0,
        canvas.width,
        canvas.height,
    );
    return canvas;
}

/**
 * Re-encode an uploaded file as webp.
 *
 * Returns the upload unchanged when the type is not convertible or the
 * browser cannot encode webp — callers detect that by checking ``type``,
 * which is the same signal that gates variant generation.
 *
 * @param {{ data: string, type: string, name: string }} info
 * @returns {Promise<{ data: string, type: string, name: string }>}
 * @throws {ImageDecodeError}
 */
export async function convertUploadToWebp(info) {
    if (NON_CONVERTIBLE_TYPES.includes(info.type)) {
        return info;
    }
    const image = await decodeImage(`data:${info.type};base64,${info.data}`);
    const dataURL = drawFullSize(image).toDataURL("image/webp");
    if (!dataURL.startsWith("data:image/webp")) {
        return info;
    }
    return {
        ...info,
        data: dataURL.split(",")[1],
        type: "image/webp",
        name: info.name.replace(/\.[^/.]+$/, ".webp"),
    };
}

/**
 * Persist a webp upload as an ``ir.attachment`` set: the original, a smaller
 * webp variant per size below it, and a jpeg fallback for each of those.
 *
 * The resized variants and the jpeg fallbacks are each created in one
 * ``create_unique`` call rather than one per size, so the whole set costs
 * three round trips whatever the source resolution.
 *
 * @param {{ call: (model: string, method: string, args: any[]) => Promise<any> }} orm
 * @param {{ data: string, name: string }} info
 * @throws {ImageDecodeError}
 */
export async function createWebpVariantAttachments(orm, info) {
    const image = await decodeImage(`data:image/webp;base64,${info.data}`);
    const originalSize = Math.max(image.width, image.height);
    const smallerSizes = canEncodeWebp()
        ? VARIANT_SIZES.filter((size) => size < originalSize)
        : [];
    const variants = [originalSize, ...smallerSizes].map((size) => ({
        size,
        canvas: drawScaled(image, size / originalSize),
    }));

    // The original keeps the bytes as uploaded; only the smaller ones are
    // re-drawn, so the source image never loses a generation to resampling.
    const [originalId] = await orm.call("ir.attachment", "create_unique", [
        [
            {
                name: info.name,
                description: "",
                datas: info.data,
                res_model: "ir.attachment",
                mimetype: "image/webp",
            },
        ],
    ]);

    const resizedVariants = variants.filter(({ size }) => size !== originalSize);
    const resizedIds = resizedVariants.length
        ? await orm.call("ir.attachment", "create_unique", [
              resizedVariants.map(({ size, canvas }) => ({
                  name: info.name,
                  description: `resize: ${size}`,
                  datas: canvas.toDataURL("image/webp").split(",")[1],
                  res_id: originalId,
                  res_model: "ir.attachment",
                  mimetype: "image/webp",
              })),
          ])
        : [];

    // Each jpeg hangs off the webp of its own size, so a client that cannot
    // read webp resolves to a fallback of matching resolution.
    const idBySize = new Map([
        [originalSize, originalId],
        ...resizedVariants.map(({ size }, index) => [size, resizedIds[index]]),
    ]);
    await orm.call("ir.attachment", "create_unique", [
        variants.map(({ size, canvas }) => ({
            name: info.name.replace(/\.webp$/, ".jpg"),
            description: "format: jpeg",
            datas: canvas.toDataURL("image/jpeg").split(",")[1],
            res_id: idBySize.get(size),
            res_model: "ir.attachment",
            mimetype: "image/jpeg",
        })),
    ]);
}
