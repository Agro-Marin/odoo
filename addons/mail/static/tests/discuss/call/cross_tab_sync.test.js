import { CrossTabSync, PING_INTERVAL } from "@mail/discuss/call/common/cross_tab_sync";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";

describe.current.tags("desktop");

function makeWire() {
    const channels = [];
    return {
        createChannel() {
            const channel = {
                onmessage: undefined,
                postMessage(data) {
                    for (const other of channels) {
                        if (other !== channel) {
                            other.onmessage?.({ data });
                        }
                    }
                },
            };
            channels.push(channel);
            return channel;
        },
    };
}

function makeSync(wire, { isHost = () => false } = {}) {
    const state = {
        remoteSessionId: undefined,
        remoteChannelId: undefined,
        isPipMode: false,
    };
    const steps = { hostClosed: 0, remoteUpdates: [] };
    const sync = new CrossTabSync({
        state,
        hooks: {
            isHost,
            onRemoteUpdate: (changes) => steps.remoteUpdates.push(changes),
            onHostClosed: () => steps.hostClosed++,
            onPipChange: () => {},
            onRemoteTabInit: () => {},
            onActionRequest: async () => {},
            onLeaveRequest: async () => {},
            onVolumeChange: () => {},
            log: () => {},
        },
        createBroadcastChannel: () => wire.createChannel(),
    });
    sync.start();
    return { sync, state, steps };
}

test("a host ignores CLOSE broadcast by one of its remote tabs", async () => {
    const wire = makeWire();
    const host = makeSync(wire, { isHost: () => true });
    host.sync.host(42);
    const remote = makeSync(wire);
    host.sync.updateRemoteTabs(1, 42, {});
    expect(remote.state.remoteSessionId).toBe(42);
    remote.sync.endHost();
    expect(host.steps.hostClosed).toBe(0);
    host.sync.endHost();
    expect(remote.steps.hostClosed).toBe(1);
});

test("PING only feeds the watchdog of remotes mirroring that host", async () => {
    const wire = makeWire();
    const hostA = makeSync(wire, { isHost: () => true });
    hostA.sync.host(42);
    const hostB = makeSync(wire, { isHost: () => true });
    hostB.sync.host(43);
    const remote = makeSync(wire);
    hostA.sync.updateRemoteTabs(1, 42, {});
    expect(remote.state.remoteSessionId).toBe(42);
    const idle = makeSync(wire);
    hostA.sync.ping(42);
    await advanceTime(PING_INTERVAL + 10_001);
    expect(remote.steps.hostClosed).toBe(1);
    expect(hostB.steps.hostClosed).toBe(0);
    expect(idle.steps.hostClosed).toBe(0);
});
