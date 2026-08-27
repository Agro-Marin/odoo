/** @odoo-module */

import {
    HootError,
    levenshtein,
    normalize,
    stringify,
    stringToNumber,
} from "../hoot_utils.js";

/**
 * @typedef {import("./job").Job} Job
 * @typedef {import("./suite").Suite} Suite
 * @typedef {import("./suite").Test} Test
 * @typedef {{
 *  name: string;
 *  exclude?: string[];
 *  before?: (test: Test) => any;
 *  after?: (test: Test) => any;
 * }} TagDefinition
 */

const {
    Math: { ceil: $ceil, max: $max },
    Object: { create: $create, keys: $keys },
    Set,
} = globalThis;

/**
 * @param {string} tagKey
 * @param {string} tagName
 */
function checkTagSimilarity(tagKey, tagName) {
    if (R_UNIQUE_TAG.test(tagKey)) {
        return;
    }
    for (const key of $keys(existingTags)) {
        if (R_UNIQUE_TAG.test(key)) {
            continue;
        }
        const maxLength = $max(tagKey.length, key.length);
        const threshold = $ceil(SIMILARITY_PERCENTAGE * maxLength);
        const editDistance = levenshtein(key, tagKey);
        if (editDistance <= threshold) {
            similarities.push([existingTags[key], tagName]);
        }
    }
}

const R_UNIQUE_TAG = /\d/;
const SIMILARITY_PERCENTAGE = 0.1;
const TAG_COLORS = [
    ["#f97316", "#ffedd5"],
    ["#eab308", "#fef9c3"],
    ["#84cc16", "#ecfccb"],
    ["#10b981", "#d1fae5"],
    ["#06b6d4", "#cffafe"],
    ["#3b82f6", "#dbeafe"],
    ["#6366f1", "#e0e7ff"],
    ["#d946ef", "#fae8ff"],
    ["#f43f5e", "#ffe4e6"],
];

/** @type {Record<string, Tag>} */
const existingTags = $create(null);
/** @type {[string, string][]} */
const similarities = [];

/**
 * @param {Job} job
 * @param {Iterable<Tag>} [tags]
 */
export function applyTags(job, tags) {
    if (!tags?.length) {
        return;
    }
    const existingKeys = new Set(job.tags.map((t) => t.key));
    for (const tag of tags) {
        if (existingKeys.has(tag.key)) {
            continue;
        }
        const excluded = tag.exclude?.filter((key) => existingKeys.has(key));
        if (excluded?.length) {
            throw new HootError(
                `cannot apply tag ${stringify(tag.name)} on test/suite ${stringify(
                    job.name,
                )} as it explicitly excludes tags ${excluded.map(stringify).join(" & ")}`,
                { level: "global" },
            );
        }
        job.tags.push(tag);
        existingKeys.add(tag.key);
        tag.weight++;
    }
}

/**
 * @param {...TagDefinition} definitions
 */
export function defineTags(...definitions) {
    return definitions.map((def) => {
        const tagKey = def.key || normalize(def.name.toLowerCase());
        if (existingTags[tagKey]) {
            throw new HootError(`duplicate definition for tag "${def.name}"`, {
                level: "global",
            });
        }
        checkTagSimilarity(tagKey, def.name);

        existingTags[tagKey] = new Tag(tagKey, def);

        return existingTags[tagKey];
    });
}

/**
 * @param {string[]} tagNames
 */
export function getTags(tagNames) {
    return tagNames.map((tagKey, i) => {
        const nKey = normalize(tagKey.toLowerCase());
        const tag =
            existingTags[nKey] || defineTags({ key: nKey, name: tagNames[i] })[0];
        return tag;
    });
}

export function getTagSimilarities() {
    return similarities;
}

/**
 * @private
 * @param {Iterable<string>} tagKeys
 */
export function undefineTags(tagKeys) {
    for (const tagKey of tagKeys) {
        delete existingTags[tagKey];
    }
}

export class Tag {
    static DEBUG = "debug";
    static ONLY = "only";
    static SKIP = "skip";
    static TODO = "todo";

    weight = 0;

    get id() {
        return this.key;
    }

    /**
     * @param {string} key
     * @param {TagDefinition} definition
     */
    constructor(key, { name, exclude, before, after }) {
        this.key = key;
        this.name = name;
        this.color = TAG_COLORS[stringToNumber(this.key) % TAG_COLORS.length];
        if (exclude) {
            this.exclude = exclude.map((id) => normalize(id.toLowerCase()));
        }
        if (before) {
            this.before = before;
        }
        if (after) {
            this.after = after;
        }
    }
}
