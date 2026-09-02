import { PosSession } from "@point_of_sale/../tests/unit/data/pos_session.data";
import { patch } from "@web/core/utils/patch";

patch(PosSession.prototype, {
    _get_model_names_to_load() {
        return [
            ...super._get_model_names_to_load(),
            "loyalty.card",
            "loyalty.program",
            "loyalty.reward",
            "loyalty.rule",
        ];
    },
});
