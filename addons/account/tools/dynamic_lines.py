"""Pure planning logic for the dynamic-lines synchronization engine."""

# `plan_dynamic_line_sync` is the decision core of `AccountMove._sync_dynamic_line`:
# given snapshots of the existing dynamic lines (before/after the wrapped operation)
# and of the needed lines, it decides what to create, update and delete. It is
# deliberately free of any ORM dependency — line handles and keys are opaque
# hashables, values are plain dicts — so the historically most bug-prone logic of
# account_move.py can be unit-tested without a database (Tier 1, see
# doc/coding_guidelines.rst §6).


def filter_trivial(mapping):
    """Drop entries whose key carries an ``id`` marker (technical lines)."""
    return {k: v for k, v in mapping.items() if "id" not in v}


def plan_dynamic_line_sync(
    existing_before,
    existing_after,
    needed_before,
    needed_after,
    values_differ,
):
    """Compute the create/write/delete plan for one dynamic-line type.

    :param existing_before: mapping ``line handle -> key`` snapshot taken
        before the wrapped operation. Handles must be hashable; keys must be
        hashable mappings (e.g. frozendict).
    :param existing_after: same mapping, snapshot taken after.
    :param needed_before: mapping ``key -> values`` of the needed lines before.
    :param needed_after: mapping ``key -> values`` of the needed lines after.
    :param values_differ: callable ``(line, values) -> bool`` telling whether
        an existing line's stored values differ from the needed ones (kept as
        a callback so ORM value conversion stays out of the planning logic).
    :return: ``None`` when user input must not be modified, else a triple
        ``(to_delete, to_create, to_write)``:

        - ``to_delete``: list of line handles to unlink,
        - ``to_create``: ``{key: values}`` of lines to create,
        - ``to_write``: ``{line handle: values}`` of in-place updates.
    """
    # old key to new key for the same line
    before2after = {
        before: existing_after[line]
        for line, before in existing_before.items()
        if line in existing_after
    }

    if needed_after == needed_before:
        return None  # do not modify user input if nothing changed in the needs
    if not needed_before and (
        filter_trivial(existing_after) != filter_trivial(existing_before)
    ):
        return None  # do not modify user input if already created manually

    lines_by_after_key = {}
    for line, key in existing_after.items():
        lines_by_after_key.setdefault(key, []).append(line)

    to_delete = [
        line
        for line, key in existing_before.items()
        if key not in needed_after
        and key in lines_by_after_key
        # .get(): when no surviving line had `key` as its before-key (the line
        # was deleted during the operation while another line took the key
        # over), there is no after-key to check — treat as unneeded.
        and before2after.get(key) not in needed_after
    ]
    to_delete_set = set(to_delete)
    to_delete.extend(
        line
        for line, key in existing_after.items()
        if key not in needed_after and line not in to_delete_set
    )
    to_delete_set = set(to_delete)

    to_create = {
        key: values
        for key, values in needed_after.items()
        if key not in lines_by_after_key
    }

    # A needed key matched by several existing lines (e.g. the user manually
    # split a payment-term line into two identical keys) must be merged back
    # into one line: writing the full needed amount to each of them would
    # double it and leave the move unbalanced.
    to_write = {}
    for key, values in needed_after.items():
        lines = lines_by_after_key.get(key)
        if not lines:
            continue
        keep_line, *extra_lines = lines
        for extra_line in extra_lines:
            if extra_line not in to_delete_set:
                to_delete.append(extra_line)
                to_delete_set.add(extra_line)
        if values_differ(keep_line, values):
            to_write[keep_line] = values

    return to_delete, to_create, to_write
