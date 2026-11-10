"""Design synthetic student profiles that exercise each reviewed audience constraint."""

import random
from typing import Any, get_args

from smartnotice.labeling.applicability import constraint_requirements
from smartnotice.schemas import AudienceConstraint, DegreeLevel, Profile, StudentStatus

DEGREE_LEVELS: tuple[str, ...] = get_args(DegreeLevel)
STATUSES: tuple[str, ...] = get_args(StudentStatus)
FIELDS = ("cohort", "degree_level", "major", "program", "status")


def _value_pools(constraints: list[AudienceConstraint]) -> dict[str, list]:
    """Collect candidate values from the constraints, adding neighbouring cohorts.

    Neighbouring admission years give every cohort requirement a nearby
    mismatch. Majors and programs come only from observed codes, so profiles
    never introduce a code that the annotation log does not contain.
    """
    cohorts: set[int] = set()
    majors: set[str] = set()
    programs: set[str] = set()
    for constraint in constraints:
        for year in [*constraint.cohorts, constraint.cohort_min, constraint.cohort_max]:
            if year is not None:
                cohorts.update({year - 1, year, year + 1})
        majors.update(constraint.majors)
        programs.update(constraint.programs)
    return {
        "cohort": sorted(cohorts),
        "degree_level": list(DEGREE_LEVELS),
        "major": sorted(majors),
        "program": sorted(programs),
        "status": list(STATUSES),
    }


def _matching_profile(
    constraint: AudienceConstraint, pools: dict[str, list], rng: random.Random
) -> dict[str, Any]:
    requirements = dict(constraint_requirements(constraint))
    profile: dict[str, Any] = {}
    for field in FIELDS:
        accepts = requirements.get(field)
        candidates = [v for v in pools[field] if accepts is None or accepts(v)]
        if field == "status":
            candidates = [v for v in candidates if v not in constraint.excluded_statuses]
        profile[field] = rng.choice(candidates) if candidates else None
    return profile


def _variants(
    constraint: AudienceConstraint, pools: dict[str, list], rng: random.Random
) -> list[dict[str, Any]]:
    """Return a match plus one mismatch, exclusion, and missing value per requirement."""
    base = _matching_profile(constraint, pools, rng)
    variants = [base]
    for field, accepts in constraint_requirements(constraint):
        others = [value for value in pools[field] if not accepts(value)]
        if others:
            variants.append({**base, field: rng.choice(others)})
        variants.append({**base, field: None})
    for status in constraint.excluded_statuses:
        variants.append({**base, "status": status})
    if constraint.excluded_statuses:
        variants.append({**base, "status": None})
    return variants


def generate_profiles(constraints: list[AudienceConstraint], seed: int) -> list[Profile]:
    """Design a deduplicated synthetic profile set for the given constraints.

    For each ``listed`` or ``all_students`` constraint, the set contains a
    matching profile and, per requirement, a known mismatch where the observed
    values allow one and a profile missing that attribute. Each excluded status
    adds an excluded profile. ``implicit`` and ``outside_population`` constraints
    do not depend on profile values and add none. The same constraints and seed
    return the same profiles with IDs ``p0001``, ``p0002``, and so on.

    Raises:
        ValueError: if no constraint has scope ``listed`` or ``all_students``.
    """
    resolvable = [c for c in constraints if c.scope in {"listed", "all_students"}]
    if not resolvable:
        raise ValueError("Profile generation needs a listed or all_students constraint")
    rng = random.Random(seed)
    pools = _value_pools(resolvable)
    seen: dict[tuple, dict[str, Any]] = {}
    for constraint in resolvable:
        for variant in _variants(constraint, pools, rng):
            seen.setdefault(tuple(variant[field] for field in FIELDS), variant)
    return [
        Profile(profile_id=f"p{index:04d}", **values)
        for index, values in enumerate(seen.values(), 1)
    ]
