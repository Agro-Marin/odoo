import type { ServiceFactories } from "services";
import "@mail/core/common/out_of_focus_service";

declare module "@mail/core/common/out_of_focus_service" {
    interface OutOfFocusService {
        titleService: ServiceFactories["title"];
        counter: number;
        contributingMessageLocalIds: Set<string>;
        clearUnreadMessage(): void;
        onWindowFocus(): void;
    }
}
