/** @odoo-module native */
import { Component, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";

export class MobileTablePicker extends Component {
    static template = "html_editor.MobileTablePicker";
    static props = {
        insertTable: Function,
        close: Function,
        editable: {
            validate: (el) => el.nodeType === Node.ELEMENT_NODE,
        },
    };

    setup() {
        this.state = useState({
            rows: 3,
            cols: 3,
        });
        this.rowsRef = useRef("rows");
        this.colsRef = useRef("cols");
        useEffect(
            (el) => el?.focus(),
            () => [this.rowsRef.el],
        );
        useExternalListener(
            this.props.editable.ownerDocument,
            "keydown",
            (ev) => {
                if (!ev.target.matches(".o-we-mobile-tablepicker input")) {
                    return;
                }
                ev.stopPropagation();
                switch (ev.key) {
                    case "Enter":
                        ev.preventDefault();
                        this.insertTable();
                        break;
                    case "Escape":
                        ev.preventDefault();
                        this.props.close();
                        break;
                }
            },
            { capture: true },
        );
    }

    updateSize() {
        this.state.rows = parseInt(this.rowsRef.el.value);
        this.state.cols = parseInt(this.colsRef.el.value);
    }

    insertTable() {
        if (this.state.cols > 0 && this.state.rows > 0) {
            this.props.insertTable({ cols: this.state.cols, rows: this.state.rows });
            this.props.close();
        }
    }
}
