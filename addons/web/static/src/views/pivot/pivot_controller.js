// @ts-check
/** @odoo-module native */

import { useEffect } from "@odoo/owl";
import { ReportController } from "@web/views/report_controller";

export class PivotController extends ReportController {
    static template = "web.PivotView";

    setup() {
        super.setup();
        useEffect(
            (isReady) => {
                if (isReady) {
                    this.actionState.setScrollFromState();
                }
            },
            () => [this.model.isReady],
        );
    }

    /**
     * @returns {boolean}
     */
    get displayNoContent() {
        if (this.props.info.noContentHelp === false) {
            return false;
        }
        const { metaData, useSampleModel } = this.model;
        return (
            useSampleModel || !this.model.hasData() || !metaData.activeMeasures.length
        );
    }

    /**
     * @returns {Object}
     */
    getLocalState() {
        const { data, metaData } = this.model;
        return { data, metaData };
    }

    /**
     * @returns {Object}
     */
    getContext() {
        return {
            pivot_measures: this.model.metaData.activeMeasures,
            pivot_column_groupby: this.model.metaData.fullColGroupBys,
            pivot_row_groupby: this.model.metaData.fullRowGroupBys,
        };
    }
}
