import { defineModels, webModels } from "@web/../tests/web_test_helpers";

import { ResourceResource } from "./mock_server/mock_models/resource_resource.js";
import { ResourceTask } from "./mock_server/mock_models/resource_task.js";

export const resourceModels = {
    ResourceTask,
    ResourceResource,
};

export function defineResourceModels() {
    return defineModels({ ...resourceModels, ...webModels });
}
