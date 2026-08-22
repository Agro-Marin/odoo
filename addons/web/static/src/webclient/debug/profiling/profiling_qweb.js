// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { renderToString } from "@web/core/utils/render";
import { useDebounced } from "@web/core/utils/timing";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

class MenuItem extends Component {
    static template = "web.ProfilingQwebView.menuitem";
    static props = {
        view: Object,
    };
}

function processValue(value) {
    let data;
    try {
        data = JSON.parse(value);
    } catch {
        return null;
    }
    const lines = data?.[0]?.results?.data;
    if (!Array.isArray(lines)) {
        return null;
    }
    for (const line of lines) {
        line.xpath = line.xpath
            .replace(/([^\]])\//g, "$1[1]/")
            .replace(/([^\]])$/g, "$1[1]");
    }
    return data;
}

export class ProfilingQwebView extends Component {
    static template = "web.ProfilingQwebView";
    static components = { Dropdown, DropdownItem, MenuItem };
    static props = { ...standardFieldProps };

    setup() {
        super.setup();

        this.orm = useService("orm");
        this.ace = useRef("ace");

        this.value = processValue(this.props.record.data[this.props.name]);
        this.state = useState({
            viewID: this.profile.data.length ? this.profile.data[0].view_id : 0,
            view: null,
        });

        this.renderProfilingInformation = useDebounced(
            this.renderProfilingInformation,
            100,
        );

        onWillStart(async () => {
            await loadBundle("web.ace_lib");
            await this._fetchViewData();
            this.state.view = this.viewObjects.find(
                (view) => view.id === this.state.viewID,
            );
        });
        onMounted(() => {
            this._startAce(this.ace.el);
            this._renderView();
        });
        onWillUnmount(() => {
            if (this.aceEditor) {
                this.aceEditor.destroy();
            }
        });
    }

    /**
     * @returns {{ archs: Object, data: Array<{template: string, xpath: string, directive: string, time: number, duration: number, query: number, view_id?: any, delay?: number}> }}
     */
    get profile() {
        return this.value ? this.value[0].results : { archs: {}, data: [] };
    }

    /**
     * @private
     * @returns {Promise<void>}
     */
    async _fetchViewData() {
        const viewIDs = Array.from(
            new Set(this.profile.data.map((line) => line.view_id)),
        );
        const viewObjects = await this.orm.call("ir.ui.view", "search_read", [], {
            fields: ["id", "display_name", "key"],
            domain: [["id", "in", viewIDs]],
        });
        for (const view of viewObjects) {
            view.delay = 0;
            view.query = 0;
            const lines = this.profile.data.filter((l) => l.view_id === view.id);
            const root = lines.find((l) => l.xpath === "");
            if (root) {
                view.delay += root.delay;
                view.query += root.query;
            } else {
                view.delay = lines.map((l) => l.delay).reduce((a, b) => a + b, 0);
                view.query = lines.map((l) => l.query).reduce((a, b) => a + b, 0);
            }
            view.delay = Math.ceil(view.delay * 10) / 10;
        }
        this.viewObjects = viewObjects;
        this._indexProfile();
    }

    _indexProfile() {
        /** @type {Map<string, any[]>} */
        this._linesByXpath = new Map();
        for (const line of this.profile.data) {
            const key = `${line.view_id}\0${line.xpath}`;
            let bucket = this._linesByXpath.get(key);
            if (!bucket) {
                bucket = [];
                this._linesByXpath.set(key, bucket);
            }
            bucket.push(line);
        }
    }

    /**
     * @param {string} xpath
     * @param {boolean} [withDescendants]
     * @returns {any[]}
     */
    _linesAt(xpath, withDescendants = false) {
        const prefix = `${this.state.viewID}\0`;
        if (!withDescendants) {
            return this._linesByXpath?.get(prefix + xpath) || [];
        }
        const lines = [];
        for (const [key, bucket] of this._linesByXpath ?? []) {
            if (key.startsWith(prefix) && key.slice(prefix.length).startsWith(xpath)) {
                lines.push(...bucket);
            }
        }
        return lines;
    }

    /**
     * @private
     * @param {number} delay
     * @returns {string}
     */
    _formatDelay(delay) {
        return delay ? (Math.ceil(delay * 10) / 10).toFixed(1) : ".";
    }

    /**
     * @private
     * @param {Node} node
     */
    _startAce(node) {
        this.aceEditor = window.ace.edit(node);
        this.aceEditor.setOptions({
            maxLines: Infinity,
            showPrintMargin: false,
            highlightActiveLine: false,
            highlightGutterLine: true,
            readOnly: true,
        });
        this.aceEditor.renderer.setOptions({
            displayIndentGuides: true,
            showGutter: true,
        });
        this.aceEditor.renderer.$cursorLayer.element.style.display = "none";

        this.aceEditor.$blockScrolling = true;
        this.aceSession = this.aceEditor.getSession();
        this.aceSession.setOptions({
            useWorker: false,
            mode: "ace/mode/qweb",
            tabSize: 2,
            useSoftTabs: true,
        });

        this.aceEditor.renderer.on(
            "afterRender",
            this.renderProfilingInformation.bind(this),
        );
    }

    _clearInjectedBadges() {
        for (const badge of this.ace.el.querySelectorAll(".o_info")) {
            badge.remove();
        }
    }

    /**
     * @private
     * @param {any} node
     * @param {any[]} arch
     * @param {any} parent
     */
    _popOnEndTagClose(node, arch, parent) {
        let previous = node;
        while ((previous = /** @type {any} */ (previous.previousElementSibling))) {
            if (previous?.classList.contains("ace_tag-name")) {
                break;
            }
        }
        if (parent.tag === previous?.textContent) {
            arch.pop();
        }
    }

    /**
     * @private
     * @param {any} node
     * @param {any[]} arch
     * @param {any} parent
     */
    _popOnEndTagOpen(node, arch, parent) {
        if (parent.tag === node.nextElementSibling?.textContent) {
            arch.pop();
        }
    }

    /**
     * @private
     * @param {any} node
     * @param {any} parent
     * @param {string} xpath
     */
    _annotateDirective(node, parent, xpath) {
        const directive = node.textContent;
        parent.directive.push({ el: node, directive });
        let delay = 0;
        let query = 0;
        for (const line of this._linesAt(xpath)) {
            if (line.directive.includes(directive)) {
                delay += line.delay;
                query += line.query;
            }
        }
        if (delay || query) {
            this._renderHover(delay, query, node);
        }
    }

    /**
     * @private
     * @param {string} xpath
     * @param {any} row
     */
    _renderOpenTagInfo(xpath, row) {
        const closed = !!row.querySelector(".ace_closed");
        const delays = [];
        const querys = [];
        const groups = {};
        let displayDetail = false;
        for (const line of this._linesAt(xpath, closed)) {
            delays.push(line.delay);
            querys.push(line.query);
            const directive = line.directive.split("=")[0];
            if (!groups[directive]) {
                groups[directive] = { delays: [], querys: [] };
            } else {
                displayDetail = true;
            }
            groups[directive].delays.push(this._formatDelay(line.delay));
            groups[directive].querys.push(line.query);
        }
        if (delays.length) {
            this._renderInfo(delays, querys, displayDetail, groups, row);
        }
    }

    /**
     * @private
     * @param {any} node
     * @param {any[]} arch
     * @param {Record<string, any>} flat
     * @param {any} parent
     * @param {string} xpath the parent's xpath, extended and returned
     * @param {any} rows
     * @returns {string}
     */
    _openTag(node, arch, flat, parent, xpath, rows) {
        const nodeTagName = node.nextElementSibling;
        const aceLine = nodeTagName.parentNode;
        const index = [...aceLine.parentNode.children].indexOf(
            /** @type {Element} */ (aceLine),
        );
        const row = rows[index];

        xpath += `/${nodeTagName.textContent}`;
        let i = 1;
        while (flat[`${xpath}[${i}]`]) {
            i++;
        }
        xpath += `[${i}]`;
        flat[xpath] = {
            xpath,
            tag: nodeTagName.textContent,
            children: [],
            directive: [],
        };
        arch.push(flat[xpath]);
        parent.children.push(flat[xpath]);

        this._renderOpenTagInfo(xpath, row);
        return xpath;
    }

    renderProfilingInformation() {
        this._clearInjectedBadges();

        /** @type {Record<string, any>} */
        const flat = {};
        const arch = [{ xpath: "", children: [], directive: [] }];
        const rows = this.ace.el.querySelectorAll(".ace_gutter .ace_gutter-cell");
        const elems = this.ace.el.querySelectorAll(
            ".ace_tag-open, .ace_end-tag-close, .ace_end-tag-open, .ace_qweb",
        );
        elems.forEach((node) => {
            const parent = arch.at(-1);
            let xpath = parent.xpath;
            if (node.classList.contains("ace_end-tag-close")) {
                this._popOnEndTagClose(node, arch, parent);
            } else if (node.classList.contains("ace_end-tag-open")) {
                this._popOnEndTagOpen(node, arch, parent);
            } else if (node.classList.contains("ace_qweb")) {
                this._annotateDirective(node, parent, xpath);
            } else if (node.classList.contains("ace_tag-open")) {
                xpath = this._openTag(node, arch, flat, parent, xpath, rows);
            }
            node.setAttribute("data-xpath", xpath);
        });
    }
    /**
     * @private
     */
    _renderView() {
        const view = this.viewObjects.find((view) => view.id === this.state.viewID);
        if (view) {
            const arch = this.profile.archs[view.id] || "";
            if (this.aceSession.getValue() !== arch) {
                this.aceSession.setValue(arch);
            }
        } else {
            this.aceSession.setValue("");
        }
        this.state.view = view;
    }
    /**
     * @param {string} template
     * @param {Record<string, any>} context
     * @param {Element} node
     */
    _appendBadge(template, context, node) {
        const div = new DOMParser()
            .parseFromString(renderToString(template, context), "text/html")
            .querySelector("div");
        node.appendChild(div);
    }

    _renderHover(delay, query, node) {
        this._appendBadge(
            "web.ProfilingQwebView.hover",
            { delay: this._formatDelay(delay), query },
            node,
        );
    }

    _renderInfo(delays, querys, displayDetail, groups, node) {
        const sum = (values) => values.reduce((a, b) => a + b, 0);
        this._appendBadge(
            "web.ProfilingQwebView.info",
            {
                delay: this._formatDelay(sum(delays)),
                query: sum(querys) || ".",
                displayDetail,
                groups,
            },
            node,
        );
    }

    /**
     * @private
     * @param {number} viewID
     */
    _onSelectView(viewID) {
        this.state.viewID = viewID;
        this._renderView();
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const profilingQwebView = {
    component: ProfilingQwebView,
    supportedTypes: ["text"],
};

registerField("profiling_qweb_view", profilingQwebView);
