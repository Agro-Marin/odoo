import random

from addons.account.tools.reconciliation import group_lines_by_matching_number


def components_by_smallest_partial(edges):
    neighbours = {}
    for _partial_id, debit_id, credit_id in edges:
        neighbours.setdefault(debit_id, set()).add(credit_id)
        neighbours.setdefault(credit_id, set()).add(debit_id)

    seen = set()
    grouped = {}
    for start in neighbours:
        if start in seen:
            continue
        component, pending = set(), [start]
        while pending:
            line_id = pending.pop()
            if line_id in component:
                continue
            component.add(line_id)
            pending.extend(neighbours[line_id] - component)
        seen |= component
        grouped[
            min(
                partial_id
                for partial_id, debit_id, credit_id in edges
                if debit_id in component or credit_id in component
            )
        ] = sorted(component)
    return grouped


def normalized(number2lines):
    return {number: sorted(lines) for number, lines in number2lines.items()}


def test_no_partial_yields_no_group():
    assert group_lines_by_matching_number([]) == {}


def test_one_partial_is_numbered_by_itself():
    assert group_lines_by_matching_number([(7, 10, 20)]) == {7: [10, 20]}


def test_a_chain_collapses_into_one_group():
    edges = [(30, 1, 2), (10, 2, 3), (20, 3, 4)]
    assert normalized(group_lines_by_matching_number(edges)) == {10: [1, 2, 3, 4]}


def test_disjoint_chains_keep_their_own_numbers():
    edges = [(5, 1, 2), (9, 3, 4)]
    assert normalized(group_lines_by_matching_number(edges)) == {5: [1, 2], 9: [3, 4]}


def test_a_second_partial_between_the_same_lines_lowers_the_number():
    edges = [(8, 1, 2), (3, 1, 2)]
    assert normalized(group_lines_by_matching_number(edges)) == {3: [1, 2]}


def test_the_number_does_not_depend_on_the_order_partials_arrive_in():
    edges = [(30, 1, 2), (10, 2, 3), (20, 3, 4)]
    expected = normalized(group_lines_by_matching_number(edges))
    for _ in range(20):
        shuffled = list(edges)
        random.Random(len(shuffled)).shuffle(shuffled)
        assert normalized(group_lines_by_matching_number(shuffled)) == expected


def test_it_agrees_with_a_brute_force_component_walk():
    rng = random.Random(20260824)
    for _ in range(2000):
        line_ids = rng.sample(range(100, 160), rng.randint(2, 12))
        partial_id = rng.randint(1, 5)
        edges = []
        for _ in range(rng.randint(1, 15)):
            debit_id, credit_id = rng.sample(line_ids, 2)
            edges.append((partial_id, debit_id, credit_id))
            partial_id += rng.randint(1, 4)
        rng.shuffle(edges)
        assert normalized(group_lines_by_matching_number(edges)) == (
            components_by_smallest_partial(edges)
        ), edges
