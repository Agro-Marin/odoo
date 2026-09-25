/** @odoo-module native */
import { provideAccountContext } from "@account/account_context";
import { useSetupAction } from "@web/core/action_hook";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { KanbanController } from "@web/views/kanban";

export class AccountReturnCheckKanbanController extends KanbanController {
    setup() {
        super.setup();

        provideAccountContext({
            reload: () => this.model.load(),
        });

        useSetupAction({
            rootRef: this.rootRef,
            getLocalState: () => {
                const renderer = this.rootRef.el.querySelector(
                    ".kanban_return_and_checks_cards",
                );
                return {
                    rendererScrollPositions: {
                        top: renderer?.scrollTop || 0,
                    },
                };
            },
        });

        let { rendererScrollPositions } = this.props.state || {};
        useLayoutEffect(() => {
            if (rendererScrollPositions) {
                const renderer = this.rootRef.el.querySelector(
                    ".kanban_return_and_checks_cards",
                );
                if (renderer) {
                    renderer.scrollTop = rendererScrollPositions.top;
                    rendererScrollPositions = null;
                }
            }
        });
    }
}
