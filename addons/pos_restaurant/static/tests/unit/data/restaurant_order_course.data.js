import { models } from "@web/../tests/web_test_helpers";

export class RestaurantOrderCourse extends models.ServerModel {
    _name = "restaurant.order.course";

    _load_pos_data_fields() {
        return ["uuid", "fired", "order_id", "line_ids", "index", "write_date"];
    }
}

