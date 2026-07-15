import { Command, serverState } from "@web/../tests/web_test_helpers";

/**
 * @module @mail/../tests/mail_scenarios
 *
 * Composable scenario factories for the recurring pyEnv topologies of the mail
 * test suites (measured over static/tests: 849 inline `discuss.channel`
 * creates, 438 hand-built member `Command.create({ partner_id: ... })`
 * literals, 156 partner+user pairs, 44 member `search([...])` + `write`
 * blocks).
 *
 * Every factory is **exact-behavior**: it creates the same records with the
 * same fields as the inline code it replaces — no extra defaults, no implicit
 * records. Anything not covered by an option can be spread through verbatim
 * (`...vals` ends up on the created record untouched).
 *
 * All helpers are synchronous, take `pyEnv` first and return plain ids (or
 * small `{ ...Id }` objects), so they read like native `pyEnv` calls:
 *
 *     const { partnerId, userId } = createUserAndPartner(pyEnv, "Bob");
 *     const { channelId } = createChatWith(pyEnv, "Bob");
 *     const channelId = createChannel(pyEnv, {
 *         name: "General",
 *         members: ["self", partnerId, { partner_id: "self", message_unread_counter: 1 }],
 *     });
 *     writeSelfMember(pyEnv, channelId, { new_message_separator: messageId + 1 });
 */

/**
 * A member entry for {@link createChannel}-style `members` options:
 * - `"self"`: the current user's partner (`serverState.partnerId`);
 * - a number: a `res.partner` id;
 * - an object: raw `discuss.channel.member` vals passed to `Command.create()`,
 *   where `partner_id: "self"` resolves to `serverState.partnerId`.
 *
 * @typedef {"self" | number | Object} MemberEntry
 */

/**
 * Convert a {@link MemberEntry} into the exact `Command.create()` the inline
 * boilerplate builds.
 *
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
 * Create a `res.partner` and its `res.users`, both named `name` — the
 * dominant "chat correspondent" fixture:
 *
 *     const partnerId = pyEnv["res.partner"].create({ name: "Bob" });
 *     const userId = pyEnv["res.users"].create({ name: "Bob", partner_id: partnerId });
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {string} name
 * @param {Object} [options]
 * @param {Object} [options.partner] extra `res.partner` vals
 * @param {Object} [options.user] extra `res.users` vals (may override `name`)
 * @returns {{ partnerId: number, userId: number }}
 */
export function createUserAndPartner(pyEnv, name, { partner = {}, user = {} } = {}) {
    const partnerId = pyEnv["res.partner"].create({ name, ...partner });
    const userId = pyEnv["res.users"].create({ name, partner_id: partnerId, ...user });
    return { partnerId, userId };
}

/**
 * Create a chat between the current user and a (new or existing)
 * correspondent — the single most duplicated topology of the suite:
 *
 *     const channelId = pyEnv["discuss.channel"].create({
 *         channel_member_ids: [
 *             Command.create({ partner_id: serverState.partnerId }),
 *             Command.create({ partner_id: partnerId }),
 *         ],
 *         channel_type: "chat",
 *     });
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {string | Object} nameOrOptions correspondent name, or options:
 * @param {string} [nameOrOptions.name] correspondent name (when creating them)
 * @param {number} [nameOrOptions.partnerId] reuse an existing partner instead
 *   of creating one (no partner/user is created then)
 * @param {Object | false} [nameOrOptions.user] extra `res.users` vals, or
 *   `false` to create the partner without a user
 * @param {Object} [nameOrOptions.partner] extra `res.partner` vals
 * @param {Object} [nameOrOptions.selfMember] extra vals on the current user's
 *   `discuss.channel.member`
 * @param {Object} [nameOrOptions.member] extra vals on the correspondent's
 *   `discuss.channel.member`
 * @param {Object} [nameOrOptions.channel] extra `discuss.channel` vals
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
 * Create a `discuss.channel`. `members` (optional) is a list of
 * {@link MemberEntry}; when omitted, no `channel_member_ids` key is passed —
 * exactly like the inline `pyEnv["discuss.channel"].create({ name })` calls
 * (the mock model then applies its own defaults). All other keys are
 * forwarded verbatim as channel vals.
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {string | { members?: MemberEntry[] } & Object} [nameOrVals]
 * @returns {number} the channel id
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
 * Create a channel whose *self* member starts with `unread` unread messages —
 * the messaging-menu / sidebar counter fixture:
 *
 *     const channelId = pyEnv["discuss.channel"].create({
 *         channel_member_ids: [
 *             Command.create({ message_unread_counter: 1, partner_id: serverState.partnerId }),
 *             Command.create({ partner_id: partnerId }),
 *         ],
 *     });
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {Object} [options]
 * @param {number} [options.unread=1] self member's `message_unread_counter`
 * @param {Object} [options.selfMember] extra vals on the self member
 * @param {MemberEntry[]} [options.members] the *other* members
 * @param {...*} [options.vals] any other key: forwarded as channel vals
 * @returns {number} the channel id
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
 * Create messages in a channel. Each entry is either a body string or raw
 * `mail.message` vals; `model` / `res_id` are filled in, everything else is
 * forwarded verbatim (and may override the fill-ins).
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {number} channelId
 * @param {(string | Object)[]} messages
 * @returns {number[]} the created message ids
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
 * Find the `discuss.channel.member` id of `partnerId` in `channelId` — the
 * recurring `search([["channel_id", "="], ["partner_id", "="]])` block.
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {number} channelId
 * @param {number} [partnerId=serverState.partnerId]
 * @returns {number} the member id
 */
export function getMemberId(pyEnv, channelId, partnerId = serverState.partnerId) {
    const [memberId] = pyEnv["discuss.channel.member"].search([
        ["channel_id", "=", channelId],
        ["partner_id", "=", partnerId],
    ]);
    return memberId;
}

/**
 * Write vals on `partnerId`'s member of `channelId` (lookup + write). Used
 * for the seen-infrastructure fixtures (`seen_message_id`,
 * `fetched_message_id`, `new_message_separator`, ...).
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {number} channelId
 * @param {number} partnerId
 * @param {Object} vals `discuss.channel.member` vals
 */
export function writeMember(pyEnv, channelId, partnerId, vals) {
    pyEnv["discuss.channel.member"].write(
        [getMemberId(pyEnv, channelId, partnerId)],
        vals,
    );
}

/**
 * Write vals on *all* members of `channelId` — the bulk seen/fetched fixture:
 *
 *     const memberIds = pyEnv["discuss.channel.member"].search([["channel_id", "=", channelId]]);
 *     pyEnv["discuss.channel.member"].write(memberIds, { seen_message_id: messageId });
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {number} channelId
 * @param {Object} vals `discuss.channel.member` vals
 */
export function writeMembers(pyEnv, channelId, vals) {
    const memberIds = pyEnv["discuss.channel.member"].search([
        ["channel_id", "=", channelId],
    ]);
    pyEnv["discuss.channel.member"].write(memberIds, vals);
}

/**
 * {@link writeMember} for the current user's member — collapses the
 * "simulate that there is at least one read message" boilerplate:
 *
 *     const [memberId] = pyEnv["discuss.channel.member"].search([
 *         ["channel_id", "=", channelId],
 *         ["partner_id", "=", serverState.partnerId],
 *     ]);
 *     pyEnv["discuss.channel.member"].write([memberId], { new_message_separator: messageId + 1 });
 *
 * @param {import("./mail_test_helpers").MailMockServer} pyEnv
 * @param {number} channelId
 * @param {Object} vals `discuss.channel.member` vals
 */
export function writeSelfMember(pyEnv, channelId, vals) {
    writeMember(pyEnv, channelId, serverState.partnerId, vals);
}
