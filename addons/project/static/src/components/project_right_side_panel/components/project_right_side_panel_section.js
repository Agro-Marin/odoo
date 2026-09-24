/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { useBus, useService } from "@web/core/utils/hooks";

export class ProjectRightSidePanelSection extends Component {
    static props = {
        name: { type: String, optional: true },
        header: { type: Boolean, optional: true },
        show: Boolean,
        showData: { type: Boolean, optional: true },
        slots: {
            type: Object,
            shape: {
                default: Object,
                header: { type: Object, optional: true },
                title: { type: Object, optional: true },
            },
        },
        dataClassName: { type: Object, optional: true },
        headerClassName: { type: String, optional: true },
        canBeClosed: { type: Boolean, optional: true },
    };
    static defaultProps = {
        header: true,
        showData: true,
        canBeClosed: true,
    };

    static template = "project.ProjectRightSidePanelSection";

    setup() {
        this.ui = useService("ui");
        this.state = useState({
            isClosed: !!this.ui.isSmall && this.props.canBeClosed,
        });

        useBus(this.ui.bus, "resize", this.setDefaultIsClosed.bind(this));
    }

    setDefaultIsClosed() {
        this.state.isClosed = this.ui.isSmall && this.props.canBeClosed;
    }

    toggleSection() {
        if (!this.ui.isSmall || !this.props.canBeClosed) {
            this.state.isClosed = false;
        } else {
            this.state.isClosed = !this.state.isClosed;
        }
    }
}
