import { patch } from "@web/core/utils/patch";
import { PosSession } from "@point_of_sale/../tests/unit/data/pos_session.data";

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
