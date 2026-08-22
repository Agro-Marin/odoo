import { CrmLead } from "@crm/../tests/mock_server/mock_models/crm_lead";

import { ResUsers } from "@crm_livechat/../tests/mock_server/mock_models/res_users";

import {
    defineLivechatModels,
    livechatModels,
} from "@im_livechat/../tests/livechat_test_helpers";

export function defineCrmLivechatModels() {
    return defineLivechatModels({ ...livechatModels, CrmLead, ResUsers });
}
