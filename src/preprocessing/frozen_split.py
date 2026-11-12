"""Allocate grouped documents while preserving previously frozen assignments."""

import hashlib
import random
from collections import Counter

from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import Notice

RATIOS = {"train": 0.65, "validation": 0.15, "test": 0.20}
RESERVED = {"domain_test", "excluded"}


def allocate_frozen_groups(
    notices: list[Notice],
    groups: dict[str, str],
    features: dict[str, dict[str, int]],
    *,
    seed: int = DEFAULT_SEED,
    previous: list[dict] | None = None,
) -> list[dict]:
    """Balance document counts and supplied nonnegative feature counts by group.

    ``groups`` must cover exactly the current documents and come from reviewed
    duplicate grouping. Features can count sources, span labels or rare audience
    categories; no model outcomes belong here. Each feature has equal weight
    after normalization by its corpus total. The local RNG breaks ties only.
    Up to 20 passes of improving whole-group moves refine the initial allocation.
    Previous rows pin their entire current group to their ordinary split. New
    members of a reserved group receive domain_test (web) or excluded (email).
    Raise ValueError for missing old documents, conflicting frozen groups,
    duplicate IDs, incompatible reserved memberships or invalid features. Only a versioned
    re-freeze may resolve a merge between previously distinct splits.
    """
    documents = {n.doc_id: n for n in notices}
    if len(documents) != len(notices) or set(groups) != set(documents):
        raise ValueError("Grouping must cover unique current document IDs exactly")
    if set(features) != set(documents):
        raise ValueError("Features must cover current document IDs exactly")
    if any(
        not isinstance(value, int) or value < 0
        for row in features.values()
        for value in row.values()
    ):
        raise ValueError("Feature counts must be nonnegative integers")
    old = {row["doc_id"]: row for row in previous or []}
    if len(old) != len(previous or []) or not set(old) <= set(documents):
        raise ValueError("Previous assignments contain duplicate or missing documents")
    for doc_id, row in old.items():
        if (
            "text_sha256" in row
            and row["text_sha256"]
            != hashlib.sha256(documents[doc_id].text.encode("utf-8")).hexdigest()
        ):
            raise ValueError(f"Frozen text changed for {doc_id}")
    members: dict[str, list[Notice]] = {}
    for notice in sorted(notices, key=lambda n: n.doc_id):
        members.setdefault(groups[notice.doc_id], []).append(notice)
    assigned: dict[str, str] = {}
    for key, items in members.items():
        pins = {old[n.doc_id]["split"] for n in items if n.doc_id in old}
        if not pins <= set(RATIOS) | RESERVED:
            raise ValueError(f"Unknown frozen split in group {key}")
        ordinary = pins & set(RATIOS)
        reserved = any(n.domain_holdout for n in items) or bool(pins & RESERVED)
        if len(ordinary) > 1 or (reserved and ordinary):
            raise ValueError(f"Conflicting frozen splits in merged group {key}")
        if reserved:
            assigned[key] = "reserved"
        elif ordinary:
            assigned[key] = next(iter(ordinary))
    vectors = {
        key: Counter({"documents": len(items)})
        for key, items in members.items()
        if assigned.get(key) != "reserved"
    }
    for key, vector in vectors.items():
        for notice in members[key]:
            for feature, count in features[notice.doc_id].items():
                vector[f"feature:{feature}"] += count
    totals = sum(vectors.values(), Counter())
    counts = {name: Counter() for name in RATIOS}
    for key, name in assigned.items():
        if name in counts:
            counts[name].update(vectors[key])
    rng = random.Random(seed)
    pending = sorted(key for key in vectors if key not in assigned)
    rng.shuffle(pending)
    pending.sort(
        key=lambda key: sum(v / totals[f] for f, v in vectors[key].items() if totals[f]),
        reverse=True,
    )
    for key in pending:
        vector = vectors[key]

        def cost(name: str, vector: Counter = vector) -> float:
            return sum(
                (
                    (counts[name][f] + value - RATIOS[name] * total) ** 2
                    - (counts[name][f] - RATIOS[name] * total) ** 2
                )
                / total**2
                for f, value in vector.items()
                if (total := totals[f])
            )

        selected = min(RATIOS, key=cost)
        assigned[key] = selected
        counts[selected].update(vector)
    for _ in range(20):
        moved = False
        for key in pending:
            vector = vectors[key]
            origin = assigned[key]
            best, improvement = origin, 0.0
            for destination in RATIOS:
                if destination == origin:
                    continue
                delta = sum(
                    (
                        (counts[origin][f] - value - RATIOS[origin] * total) ** 2
                        - (counts[origin][f] - RATIOS[origin] * total) ** 2
                        + (counts[destination][f] + value - RATIOS[destination] * total) ** 2
                        - (counts[destination][f] - RATIOS[destination] * total) ** 2
                    )
                    / total**2
                    for f, value in vector.items()
                    if (total := totals[f])
                )
                if delta < improvement - 1e-12:
                    best, improvement = destination, delta
            if best != origin:
                counts[origin].subtract(vector)
                counts[best].update(vector)
                assigned[key] = best
                moved = True
        if not moved:
            break
    rows = []
    for notice in notices:
        selected = assigned[groups[notice.doc_id]]
        if selected == "reserved":
            selected = "domain_test" if notice.source_type == "web" else "excluded"
        if notice.doc_id in old and old[notice.doc_id]["split"] != selected:
            raise ValueError(f"Frozen source/split changed for {notice.doc_id}")
        rows.append(
            {
                "doc_id": notice.doc_id,
                "group_id": groups[notice.doc_id],
                "split": selected,
                "text_sha256": hashlib.sha256(notice.text.encode("utf-8")).hexdigest(),
            }
        )
    return rows
