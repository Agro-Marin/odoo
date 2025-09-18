Project Module Terminology
==========================

This module follows PMI/PMBOK terminology where applicable.

Workflow Step (``project.workflow.step``)
    A named position in a project's Kanban board. Tasks move through
    workflow steps as work progresses (e.g., "Backlog → Development →
    Review → Done"). Each project defines its own set of steps.

    Displayed as: Kanban columns, statusbar in form view.

Task State (``project.task.state``)
    The internal condition of a task. Fixed set of values:

    - **In Progress** (``in_progress``) — actively being worked on
    - **Changes Requested** (``changes_requested``) — reviewer requested
      modifications
    - **Approved** (``approved``) — validated, ready to proceed
    - **Blocked** (``blocked``) — cannot proceed due to unfinished
      predecessors
    - **Done** (``done``) — completed
    - **Canceled** (``canceled``) — abandoned

    State is partially auto-computed: tasks with open predecessors are
    automatically set to "Blocked". Closed states (Done, Canceled) are
    never overridden by computation.

Personal Triage (``project.triage``)
    A user's personal time-horizon categorization for tasks they are
    assigned to. Not visible to other users. Not part of the project
    workflow. Default buckets: Inbox, Today, This Week, This Month,
    Later, Done, Cancelled.

    Displayed as: Kanban columns in "My Tasks" view only.

Project Phase (``project.phase``)
    The lifecycle stage of a project itself (not its tasks). Examples:
    "Planning", "Execution", "Closing". A project has exactly one
    current phase.

Milestone (``project.milestone``)
    A significant point or event in a project with zero duration.
    Milestones have a deadline and a reached/not-reached status.

Predecessor / Successor
    A dependency between two tasks. Task B has Task A as a predecessor
    if B cannot start until A is done (Finish-to-Start relationship).
    Task A is then a successor of nothing — Task B is A's successor.

Project Status (``project.update.status``)
    A health indicator for the project as a whole: On Track, At Risk,
    Off Track, On Hold, Complete. Updated via project updates.

Priority
    Relative urgency of a task: Normal (default), Important, High, Urgent.
