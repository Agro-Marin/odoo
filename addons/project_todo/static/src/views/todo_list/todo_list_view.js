/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";
import { TodoListController } from "./todo_list_controller.js";
import { TaskListRenderer } from "@project/components/task_list_renderer";

export const todoListView = {
    ...listView,
    Controller: TodoListController,
    Renderer: TaskListRenderer,
};

registry.category("views").add("todo_list", todoListView);
