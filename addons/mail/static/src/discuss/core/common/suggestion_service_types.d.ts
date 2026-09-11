import { SuggestionService as RawSuggestionService } from "@mail/core/common/suggestion_service";
import { ChannelCommandSuggestion } from "./suggestion_service_patch";

declare module "@mail/core/common/suggestion_service" {
    interface SuggestionService {
        getChannelCommands(
            thread?: import("models").Thread,
        ): ChannelCommandSuggestion[];
        searchChannelCommand(
            cleanedSearchTerm: string,
            thread?: import("models").Thread,
        ): { type: string; suggestions: ChannelCommandSuggestion[] };
    }
}
