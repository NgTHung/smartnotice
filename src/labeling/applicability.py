"""Generate silver applicability labels from annotated audience constraints."""

from smartnotice.schemas import AudienceConstraint, Profile


def _canonical(value: str) -> str:
    return " ".join(value.casefold().split())


def match_profile(constraint: AudienceConstraint, profile: Profile) -> tuple[str, str]:
    """Return a three-way label and its rule reason for one audience branch.

    Included attributes combine with AND; values within an attribute use OR.
    Exclusions take priority. Missing attributes and implicit audiences abstain.
    """
    if constraint.implicit:
        return "UNCLEAR", "implicit_audience"
    if profile.status and _canonical(profile.status) in {
        _canonical(value) for value in constraint.excluded_statuses
    }:
        return "NOT_APPLIES", "excluded_status"
    unknown = bool(constraint.excluded_statuses and profile.status is None)
    specified = bool(constraint.excluded_statuses)
    for field, values in [
        ("cohort", constraint.cohorts),
        ("major", constraint.majors),
        ("program", constraint.programs),
        ("status", constraint.statuses),
    ]:
        if not values:
            continue
        specified = True
        actual = getattr(profile, field)
        if actual is None:
            unknown = True
        elif _canonical(actual) not in {_canonical(value) for value in values}:
            return "NOT_APPLIES", f"mismatched_{field}"
    if unknown or not specified:
        return "UNCLEAR", "missing_profile_attribute" if unknown else "unspecified_audience"
    return "APPLIES", "all_constraints_match"


def match_audiences(constraints: list[AudienceConstraint], profile: Profile) -> tuple[str, str]:
    """Combine alternative audience branches with OR, abstaining without evidence."""
    if not constraints:
        return "UNCLEAR", "no_audience_constraint"
    labels = [match_profile(constraint, profile) for constraint in constraints]
    for target in ("APPLIES", "UNCLEAR", "NOT_APPLIES"):
        if any(label == target for label, _ in labels):
            return target, ";".join(reason for label, reason in labels if label == target)
    raise AssertionError("Unreachable audience label")
