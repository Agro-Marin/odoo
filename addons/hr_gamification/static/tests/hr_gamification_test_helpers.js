import { hrModels } from "@hr/../tests/hr_test_helpers";
import { defineModels } from "@web/../tests/web_test_helpers";
import { GamificationBadge } from "./mock_server/mock_models/gamification_badge.js";
import { GamificationBadgeUser } from "./mock_server/mock_models/gamification_badge_user.js";

export function defineHrGamificationModels() {
    return defineModels(hrGamificationModels);
}

export const hrGamificationModels = {
    ...hrModels,
    GamificationBadge,
    GamificationBadgeUser,
};
