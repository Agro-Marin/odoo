import { Command, serverState } from "@web/../tests/web_test_helpers";

/** @typedef {"self" | number | Object} MemberEntry */
/**
 * @param {MemberEntry} member
 * @returns {ReturnType<typeof Command.create>}
 */
function memberCommand(member) {
    if (member === "self") {
        return Command.create({ partner_id: serverState.partnerId });
    }
    if (typeof member === "number") {
        return Command.create({ partner_id: member });
    }
    const vals = { ...member };
    if (vals.partner_id === "self") {
        vals.partner_id = serverState.partnerId;
    }
    return Command.create(vals);
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {string} name
 * @param {Object} [options]
 * @param {Object} [options.partner]
 * @param {Object} [options.user]
 * @returns {{ partnerId: number, userId: number }}
 */
export function createUserAndPartner(pyEnv, name, { partner = {}, user = {} } = {}) {
    const partnerId = pyEnv["res.partner"].create({ name, ...partner });
    const userId = pyEnv["res.users"].create({ name, partner_id: partnerId, ...user });
    return { partnerId, userId };
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {string | Object} nameOrOptions
 * @param {string} [nameOrOptions.name]
 * @param {number} [nameOrOptions.partnerId]
 * @param {Object | false} [nameOrOptions.user]
 * @param {Object} [nameOrOptions.partner]
 * @param {Object} [nameOrOptions.selfMember]
 * @param {Object} [nameOrOptions.member]
 * @param {Object} [nameOrOptions.channel]
 * @returns {{ channelId: number, partnerId: number, userId: number | undefined }}
 */
export function createChatWith(pyEnv, nameOrOptions) {
    const options =
        typeof nameOrOptions === "string" ? { name: nameOrOptions } : nameOrOptions;
    const {
        channel = {},
        member = {},
        name,
        partner = {},
        selfMember = {},
        user = {},
    } = options;
    let { partnerId } = options;
    let userId;
    if (partnerId === undefined) {
        partnerId = pyEnv["res.partner"].create({ name, ...partner });
        if (user !== false) {
            userId = pyEnv["res.users"].create({
                name,
                partner_id: partnerId,
                ...user,
            });
        }
    }
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId, ...selfMember }),
            Command.create({ partner_id: partnerId, ...member }),
        ],
        channel_type: "chat",
        ...channel,
    });
    return { channelId, partnerId, userId };
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {string | { members?: MemberEntry[] } & Object} [nameOrVals]
 * @returns {number}
 */
export function createChannel(pyEnv, nameOrVals = {}) {
    const { members, ...vals } =
        typeof nameOrVals === "string" ? { name: nameOrVals } : nameOrVals;
    if (members) {
        vals.channel_member_ids = members.map(memberCommand);
    }
    return pyEnv["discuss.channel"].create(vals);
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {Object} [options]
 * @param {number} [options.unread=1]
 * @param {Object} [options.selfMember]
 * @param {MemberEntry[]} [options.members]
 * @returns {number}
 */
export function createChannelWithUnreads(pyEnv, options = {}) {
    const { members = [], selfMember = {}, unread = 1, ...vals } = options;
    return createChannel(pyEnv, {
        members: [
            { message_unread_counter: unread, partner_id: "self", ...selfMember },
            ...members,
        ],
        ...vals,
    });
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {number} channelId
 * @param {(string | Object)[]} messages
 * @returns {number[]}
 */
export function createChannelMessages(pyEnv, channelId, messages) {
    return pyEnv["mail.message"].create(
        messages.map((message) => ({
            model: "discuss.channel",
            res_id: channelId,
            ...(typeof message === "string" ? { body: message } : message),
        })),
    );
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {number} channelId
 * @param {number} [partnerId=serverState.partnerId]
 * @returns {number}
 */
export function getMemberId(pyEnv, channelId, partnerId = serverState.partnerId) {
    const [memberId] = pyEnv["discuss.channel.member"].search([
        ["channel_id", "=", channelId],
        ["partner_id", "=", partnerId],
    ]);
    return memberId;
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {number} channelId
 * @param {number} partnerId
 * @param {Object} vals
 */
export function writeMember(pyEnv, channelId, partnerId, vals) {
    pyEnv["discuss.channel.member"].write(
        [getMemberId(pyEnv, channelId, partnerId)],
        vals,
    );
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {number} channelId
 * @param {Object} vals
 */
export function writeMembers(pyEnv, channelId, vals) {
    const memberIds = pyEnv["discuss.channel.member"].search([
        ["channel_id", "=", channelId],
    ]);
    pyEnv["discuss.channel.member"].write(memberIds, vals);
}

/**
 * @param {import("@web/../tests/web_test_helpers").MockServerEnvironment} pyEnv
 * @param {number} channelId
 * @param {Object} vals
 */
export function writeSelfMember(pyEnv, channelId, vals) {
    writeMember(pyEnv, channelId, serverState.partnerId, vals);
}
