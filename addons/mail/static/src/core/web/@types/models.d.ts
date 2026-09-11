declare module "models" {
    export interface Activity {
        isNoteEmpty: boolean;
        dateCreateFormatted: Readonly<string>;
        dateDeadlineFormatted: Readonly<string>;
        dateDoneFormatted: Readonly<string>;
        edit: () => Promise<void>;
        markAsDone: (attachmentIds: number[]) => Promise<void>;
        markAsDoneAndScheduleNext: () => Promise<ActionDescription>;
        remove: (param0?: { broadcast?: boolean }) => void;
    }
    export interface Message {
        canForward: (thread: Thread) => boolean;
        canReplyAll: (thread: Thread) => boolean;
    }
    export interface Store {
        _onActivityBroadcastChannelMessage: (param0: {
            data:
                | {
                      type: "INSERT" | "DELETE";
                      payload: Partial<Activity>;
                  }
                | {
                      type: "RELOAD_CHATTER";
                      payload: { model: string; id: number };
                  };
        }) => void;
        activity_counter_bus_id: number;
        activityBroadcastChannel: BroadcastChannel | null;
        activityCounter: number;
        activityGroups: Object[];
        computeGlobalCounter: () => number;
        globalCounter: number;
        history: Thread;
        inbox: Thread;
        onLinkFollowed: (fromThread: Thread) => void;
        onUpdateActivityGroups: () => void;
        scheduleActivity: (
            resModel: string | false,
            resIds: (number | string)[] | false,
            defaultActivityTypeId?: number,
        ) => Promise<void>;
        starred: Thread;
        unstarAll: () => Promise<void>;
        updateAppBadge: () => void;
    }
    export interface Thread {
        activities: Activity[];
        follow: () => Promise<void>;
        isDisplayedInDiscussAppDesktop: boolean;
        openRecordActionRequest: Readonly<ActionDescription>;
        loadMoreFollowers: () => Promise<void>;
        recipients: import("@mail/model/record_list").RecordList<Follower>;
    }
}
