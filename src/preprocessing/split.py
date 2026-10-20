"""Keep threads, manually assigned templates, and similar texts in one split."""

import hashlib
import random
import re
from difflib import SequenceMatcher

from smartnotice.schemas import Notice

DEFAULT_SEED = 42


def group_documents(notices: list[Notice], similarity: float = 0.9) -> dict[str, str]:
    """Merge source groups and similar normalized texts transitively.

    Pairwise character similarity costs O(n²). Review merged groups before
    training, especially when common boilerplate dominates short notices.
    """
    if not 0 < similarity <= 1:
        raise ValueError("Similarity must be in (0, 1]")
    parents = list(range(len(notices)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    texts = [re.sub(r"\s+", " ", notice.text.casefold()).strip() for notice in notices]
    for i, notice in enumerate(notices):
        for j in range(i):
            same = notice.group_id == notices[j].group_id
            if (
                same
                or SequenceMatcher(None, texts[i], texts[j], autojunk=False).ratio() >= similarity
            ):
                parents[find(i)] = find(j)
    members: dict[int, list[str]] = {}
    for i, notice in enumerate(notices):
        members.setdefault(find(i), []).append(notice.doc_id)
    keys = {
        root: hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()[:20]
        for root, ids in members.items()
    }
    return {notice.doc_id: keys[find(i)] for i, notice in enumerate(notices)}


def split_documents(
    notices: list[Notice], seed: int = DEFAULT_SEED, similarity: float = 0.9
) -> list[dict]:
    """Assign whole groups near 70/15/15 and isolate reserved web groups.

    A group touching the domain holdout is reserved in full. Related email
    records receive `excluded` so the holdout remains web-only. Tiny corpora
    can have empty validation or test splits; exact proportions are not promised.
    """
    ids = [notice.doc_id for notice in notices]
    if len(ids) != len(set(ids)):
        raise ValueError("Document IDs must be unique")
    mapping = group_documents(notices, similarity)
    groups: dict[str, list[Notice]] = {}
    for notice in notices:
        groups.setdefault(mapping[notice.doc_id], []).append(notice)
    reserved = {key for key, items in groups.items() if any(n.domain_holdout for n in items)}
    pool = sorted(key for key in groups if key not in reserved)
    rng = random.Random(seed)
    rng.shuffle(pool)
    pool.sort(key=lambda key: len(groups[key]), reverse=True)
    total = sum(len(groups[key]) for key in pool)
    targets = {"train": 0.7 * total, "validation": 0.15 * total, "test": 0.15 * total}
    counts = dict.fromkeys(targets, 0)
    assignments = {}
    for key in pool:
        split = max(targets, key=lambda name: targets[name] - counts[name])
        assignments[key] = split
        counts[split] += len(groups[key])
    return [
        {
            "doc_id": n.doc_id,
            "group_id": mapping[n.doc_id],
            "split": ("domain_test" if n.source_type == "web" else "excluded")
            if mapping[n.doc_id] in reserved
            else assignments[mapping[n.doc_id]],
            "seed": seed,
        }
        for n in notices
    ]
