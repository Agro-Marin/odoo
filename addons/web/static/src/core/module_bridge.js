// @ts-check
/** @odoo-module native */

const VALID_EXPORT_NAME = /^[a-zA-Z_$][\w$]*$/;

/**
 * @param {string} specifier
 * @param {Iterable<string>} exportNames
 * @returns {string}
 */
export function buildBridgeModuleSource(specifier, exportNames) {
    /** @type {string[]} */
    const names = [];
    for (const name of exportNames) {
        if (name !== "default" && VALID_EXPORT_NAME.test(name)) {
            names.push(name);
        }
    }
    const locals = ["_d", ...names.map((_, i) => `_e${i}`)];
    const lines = [
        `let ${locals.join(", ")};`,
        `function _s() {`,
        `  const _m = odoo.loader.modules.get(${JSON.stringify(specifier)});`,
        `  if (_m === undefined) { return; }`,
        `  _d = _m.default ?? _m;`,
        ...names.map((name, i) => `  _e${i} = _m.${name};`),
        `  odoo.loader.bus.removeEventListener("registered", _s);`,
        `}`,
        `_s();`,
        `odoo.loader.bus.addEventListener("registered", _s);`,
        `export { ${["_d as default", ...names.map((n, i) => `_e${i} as ${n}`)].join(", ")} };`,
    ];
    return lines.join("\n");
}

/**
 * @param {() => any} getValue
 * @param {{ constructable?: boolean }} [options]
 * @returns {any}
 */
export function makeLazyFacade(getValue, { constructable = false } = {}) {
    const target = constructable ? function () {} : Object.create(null);
    const current = () => getValue() ?? undefined;
    return new Proxy(target, {
        apply(t, thisArg, args) {
            return Reflect.apply(current(), thisArg, args);
        },
        construct(t, args) {
            return Reflect.construct(current(), args);
        },
        get(t, p) {
            const value = current();
            return value === undefined ? Reflect.get(t, p) : Reflect.get(value, p);
        },
        set(t, p, v) {
            const value = current();
            return Reflect.set(value === undefined ? t : value, p, v);
        },
        has(t, p) {
            const value = current();
            return value === undefined ? Reflect.has(t, p) : Reflect.has(value, p);
        },
        deleteProperty(t, p) {
            const value = current();
            return Reflect.deleteProperty(value === undefined ? t : value, p);
        },
        defineProperty(t, p, desc) {
            const value = current();
            return Reflect.defineProperty(value === undefined ? t : value, p, desc);
        },
        ownKeys(t) {
            const value = current();
            if (value === undefined) {
                return Reflect.ownKeys(t);
            }
            const keys = new Set(Reflect.ownKeys(value));
            for (const key of Reflect.ownKeys(t)) {
                const desc = Reflect.getOwnPropertyDescriptor(t, key);
                if (desc && !desc.configurable) {
                    keys.add(key);
                }
            }
            return [...keys];
        },
        getOwnPropertyDescriptor(t, p) {
            const value = current();
            const desc =
                value === undefined
                    ? Reflect.getOwnPropertyDescriptor(t, p)
                    : (Reflect.getOwnPropertyDescriptor(value, p) ??
                      Reflect.getOwnPropertyDescriptor(t, p));
            if (!desc) {
                return undefined;
            }
            const targetDesc = Reflect.getOwnPropertyDescriptor(t, p);
            if (!targetDesc || targetDesc.configurable) {
                desc.configurable = true;
            } else {
                desc.configurable = false;
                if ("writable" in desc) {
                    desc.writable = true;
                }
            }
            return desc;
        },
    });
}

/**
 * @param {string} source
 * @returns {string}
 */
export function toDataModuleUrl(source) {
    return `data:text/javascript,${encodeURIComponent(source)}`;
}

/**
 * @param {string} specifier
 * @returns {string | null}
 */
export function specToModuleUrl(specifier) {
    if (!specifier.startsWith("@") || specifier.includes("..")) {
        return null;
    }
    const slash = specifier.indexOf("/");
    if (slash <= 1) {
        return null;
    }
    const addon = specifier.slice(1, slash);
    const rest = specifier.slice(slash + 1);
    return `/${addon}/static/src/${rest}.js`;
}

/**
 * @param {unknown} url
 * @returns {boolean}
 */
export function isLoaderBridgeUrl(url) {
    return (
        typeof url === "string" &&
        (url.startsWith("data:") || url.includes("/web/assets/esm/bridges/"))
    );
}
