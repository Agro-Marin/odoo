Project Module Terminology
==========================

This module follows PMI/PMBOK terminology where applicable.

Core Concepts
-------------

Workflow Step (``project.workflow.step``)
    A named position in a project's Kanban board. Tasks move through
    workflow steps as work progresses (e.g., "Backlog → Development →
    Review → Done"). Each project defines its own set of steps.
    Steps can have a **WIP limit** (maximum concurrent tasks).

    Displayed as: Kanban columns, statusbar in form view.

Task State (``project.task.state``)
    The internal condition of a task. Fixed set of values:

    - **To Do** (``todo``) — not yet started
    - **In Progress** (``in_progress``) — actively being worked on
    - **Changes Requested** (``changes_requested``) — reviewer requested
      modifications
    - **Approved** (``approved``) — validated, ready to proceed
    - **Waiting** (``blocked``) — cannot proceed due to unfinished
      predecessors
    - **Done** (``done``) — completed
    - **Canceled** (``canceled``) — abandoned

    State is partially auto-computed: tasks with open predecessors are
    automatically set to "Waiting". Closed states (Done, Canceled) are
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

Task Dependency (``project.task.dependency``)
    A typed dependency between two tasks. Extends the basic M2M
    predecessor/successor relationship with:

    - **FS** (Finish-to-Start) — B waits for A to finish (default, most common)
    - **SS** (Start-to-Start) — B waits for A to start
    - **FF** (Finish-to-Finish) — B cannot finish until A finishes
    - **SF** (Start-to-Finish) — B cannot finish until A starts (rare)
    - **Lag** — delay (or lead, if negative) after the condition is met

Project Status (``project.update.status``)
    A health indicator for the project as a whole: On Track, At Risk,
    Off Track, On Hold, Complete. Updated via project updates.

Health Score / Health Status
    Automated composite score (0-100) computed from objective data:
    schedule compliance, milestone progress, risk exposure, and task
    staleness. Prevents "status theater" where manual reports hide
    problems. Distinct from the manual Project Status above.

Priority
    Relative urgency of a task: Normal (default), Important, High, Urgent.

CD3 Score (Cost of Delay Divided by Duration)
    Economic prioritization metric. ``cost_of_delay / allocated_hours``.
    Higher score = do first. Based on Reinertsen's research showing
    85% of PMs cannot quantify cost of delay.

Risk & Governance
-----------------

Risk (``project.risk``)
    A potential event that could affect project outcomes. Assessed with
    probability (1-5) and impact (1-5), producing a risk score (1-25).
    Risk levels: Low (1-4), Medium (5-9), High (10-15), Critical (16-25).
    Each risk has a response strategy: Mitigate, Transfer, Accept, Avoid,
    or Exploit.

Gate Review (``project.gate``)
    A formal go/no-go decision point tied to a milestone. Contains
    evaluable criteria (``project.gate.criterion``) with pass/fail
    and evidence fields, plus kill criteria for project cancellation.

Benefit (``project.benefit``)
    An expected business outcome from the project, with target value,
    measurement method, actual value, and achievement percentage.
    Tracks whether projects deliver value, not just complete tasks.

Baseline (``project.baseline``)
    A point-in-time snapshot of a project's task names, dates, and
    hours. Used for schedule variance analysis ("how much scope was
    added since kickoff?"). One baseline per project is marked "current".

Project History (``project.history``)
    Archived metrics from a completed project: planned vs actual
    duration, effort, team size, tags. Foundation for reference class
    forecasting — answering "how long did similar projects actually take?"

Pre-Mortem
    A structured exercise at project kickoff: "Imagine this project has
    failed. Why?" Stored as fields on project (date, participants, notes).
    Klein's research: +30% cause identification vs standard risk analysis.

Learning & Improvement
----------------------

Retrospective (``project.retrospective``)
    A structured review capturing what went well, what needs improvement,
    and concrete action items. Actions can be carried forward from one
    retrospective to the next, preventing "lessons identified but not
    learned."

Retrospective Action (``project.retrospective.action``)
    A concrete improvement action from a retrospective, with owner,
    due date, category, and resolution tracking. Categories: Estimation,
    Scope, Communication, Technical, Process, Team, Tooling.

Agile
-----

Sprint (``project.sprint``)
    A time-boxed iteration within a project. Has start/end dates, a
    goal, capacity, and assigned tasks. Tracks velocity (hours or story
    points completed). Feature-flagged via ``use_sprints`` on project.
    Only one sprint can be active per project at a time.

Story Points
    Optional relative effort estimate on tasks. Used for sprint velocity
    tracking. The system works without them — hours-based velocity is
    the default.

Flow Metrics
------------

WIP Count
    Number of open, non-blocked tasks in a project.

Queue Time (``queue_time_hours``, ``queue_time_days``)
    Working hours/days from task creation to first assignment.
    Measures how long work sits before someone picks it up.

Lead Time (``lead_time_hours``, ``lead_time_days``)
    Working hours/days from task creation to closure (calendar-adjusted).
    Total request-to-delivery time, including queue wait.
    Aggregated as ``avg_lead_time`` on project (90-day rolling window).

Cycle Time (``cycle_time_hours``, ``cycle_time_days``)
    Working hours/days from first assignment to closure (calendar-adjusted).
    Active work time only, excluding queue wait.
    Aggregated as ``avg_cycle_time`` on project (90-day rolling window).
    Requires both ``date_assign`` and ``date_closed`` to compute.

Throughput
    Tasks closed per week. Aggregated as ``throughput_week`` on project
    (4-week rolling average).

Deadline Compliance
    Percentage of closed tasks with deadlines that met their deadline.
    Foundation for estimation improvement over time.

Critical Path
    The longest sequence of dependent tasks through a project. Tasks on
    the critical path have zero float — any delay on them delays the
    whole project. Computed on demand via forward/backward pass CPM
    using all four dependency types (FS/SS/FF/SF) with lag support.

Planned Start / Planned End (``planned_date_start``, ``planned_date_end``)
    Calendar-aware start and end dates computed by CPM. Distinct from
    ``date_end`` (user-entered target) and ``date_closed`` (actual
    completion). Accounts for the project's resource calendar (working
    hours, weekends, holidays).

Total Float (``total_float``)
    The amount of scheduling slack (in hours) a task has before it
    delays the project. ``latest_start - earliest_start``. Zero float
    means the task is on the critical path.

Resource Leveling
    A heuristic that adjusts planned dates of non-critical tasks to
    reduce user overallocation. Processes tasks in descending float
    order and shifts them forward within their float allowance when
    assigned users have concurrent work.

Backlog
    Tasks in a sprint-enabled project that are not assigned to any
    sprint. Visible via the Backlog filter/menu when ``use_sprints``
    is enabled on the project.

Strategic Objective (``is_strategic`` on ``project.tags``)
    A tag marked as representing a strategic business objective.
    Used in portfolio views to group and filter projects by their
    alignment to organizational strategy.

Monte Carlo Forecast
    Probabilistic completion date prediction using historical throughput
    data. Runs N simulations sampling random weeks from history to
    estimate 50th/85th/95th percentile completion dates.
