// @ts-check
/** @odoo-module native */

import { Component, useRef } from "@odoo/owl";
import { Notebook } from "@web/components/notebook/notebook";
import { Dialog } from "@web/ui/dialog/dialog";

/**
 * @param {number} min
 * @param {number} max
 * @returns {number}
 */
const random = (min, max) => Math.floor(Math.random() * (max - min) + min);

class KanbanExamplesNotebookTemplate extends Component {
    static template = "web.KanbanExamplesNotebookTemplate";
    static props = {
        columns: { type: Array, element: String, optional: true },
        foldedColumns: { type: Array, element: String, optional: true },
        bullets: { type: Array, optional: true },
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
            /** @type {Record<string, any>[]} */
            const records = [];
            this.columns.push({ title, records });
            for (let i = 0; i < random(1, 5); i++) {
                /** @type {Record<string, any>} */
                const rec = { id: i };
                if (hasBullet && Math.random() > 0.3) {
                    const sampleId = Math.floor(
                        Math.random() * this.props.bullets.length,
                    );
                    rec.bullet = this.props.bullets[sampleId];
                }
                records.push(rec);
            }
        }
    }
}

export class KanbanColumnExamplesDialog extends Component {
    static template = "web.KanbanColumnExamplesDialog";
    static components = { Dialog, Notebook };
    static props = {
        examples: { type: Array, element: Object },
        applyExamples: Function,
        applyExamplesText: { type: String, optional: true },
        close: Function,
    };

    /** @type {Record<string, any>[]} */
    pages;
    /** @type {string | null} */
    activePage;

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
     * @param {string} page
     */
    onPageUpdate(page) {
        this.activePage = page;
    }

    applyExamples() {
        const index = this.props.examples.findIndex((e) => e.name === this.activePage);
        this.props.applyExamples(index);
        this.props.close();
    }
}
