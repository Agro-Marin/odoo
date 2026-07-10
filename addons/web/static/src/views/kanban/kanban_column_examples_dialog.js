// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_column_examples_dialog - Dialog showcasing example column layouts for kanban board setup */

import { Component, useRef } from "@odoo/owl";
import { Notebook } from "@web/components/notebook/notebook";
import { Dialog } from "@web/ui/dialog/dialog";

/**
 * @param {number} min - Inclusive lower bound.
 * @param {number} max - Exclusive upper bound.
 * @returns {number} Random integer in [min, max).
 */
const random = (min, max) => Math.floor(Math.random() * (max - min) + min);

/** Renders a single example tab with randomized placeholder records. */
class KanbanExamplesNotebookTemplate extends Component {
    static template = "web.KanbanExamplesNotebookTemplate";
    // Receives the whole example descriptor via `props: eg` spread (see
    // `KanbanColumnExamplesDialog.setup` below); descriptors carry metadata
    // beyond columns/foldedColumns/bullets, hence the catch-all `"*": true`.
    static props = {
        columns: { type: Array, element: String, optional: true },
        foldedColumns: { type: Array, element: String, optional: true },
        bullets: { type: Array, optional: true },
        // Read by the XML template (line 5: ``<div t-if="props.description"``),
        // not by the JS class. Declared so the contract is explicit.
        description: { type: String, optional: true },
        "*": true,
    };
    static defaultProps = {
        columns: [],
        foldedColumns: [],
    };
    setup() {
        this.columns = [];
        const hasBullet = this.props.bullets && this.props.bullets.length;
        const allColumns = [...this.props.columns, ...this.props.foldedColumns];
        for (const title of allColumns) {
            const col = { title, records: [] };
            this.columns.push(col);
            for (let i = 0; i < random(1, 5); i++) {
                const rec = { id: i };
                if (hasBullet && Math.random() > 0.3) {
                    const sampleId = Math.floor(
                        Math.random() * this.props.bullets.length,
                    );
                    rec.bullet = this.props.bullets[sampleId];
                }
                col.records.push(rec);
            }
        }
    }
}

/**
 * Dialog presenting predefined column layouts a user can apply to
 * auto-create columns on a grouped kanban that has none yet.
 */
export class KanbanColumnExamplesDialog extends Component {
    static template = "web.KanbanColumnExamplesDialog";
    static components = { Dialog, Notebook };
    static props = {
        examples: { type: Array, element: Object },
        applyExamples: Function,
        // Read by the XML template (line 25:
        // ``<button … t-esc="props.applyExamplesText"/>``), not by JS.
        applyExamplesText: { type: String, optional: true },
        close: Function,
    };

    setup() {
        this.navList = useRef("navList");
        this.pages = [];
        this.activePage = null;
        this.props.examples.forEach((eg) => {
            this.pages.push({
                Component: KanbanExamplesNotebookTemplate,
                title: eg.name,
                props: eg,
                id: eg.name,
            });
        });
    }

    /**
     * Track the currently selected notebook tab.
     * @param {string} page - Tab identifier (example name).
     */
    onPageUpdate(page) {
        this.activePage = page;
    }

    /** Apply the selected example layout and close the dialog. */
    applyExamples() {
        const index = this.props.examples.findIndex((e) => e.name === this.activePage);
        this.props.applyExamples(index);
        this.props.close();
    }
}
