"""Generate silver applicability labels from annotated audience constraints."""

from collections.abc import Callable

from smartnotice.schemas import AudienceConstraint, Profile


def _canonical(value: str) -> str:
    return " ".join(value.casefold().split())


def _in_codes(values: list[str]) -> Callable[[str], bool]:
    codes = {_canonical(value) for value in values}
    return lambda actual: _canonical(actual) in codes


def constraint_requirements(constraint: AudienceConstraint) -> list[tuple[str, Callable]]:
    """Return ``(profile_field, accepts)`` for each specified inclusion attribute.

    ``accepts`` takes a known profile value and returns whether it satisfies the
    attribute. Majors and programs compare after case and whitespace folding.
    """
    requirements: list[tuple[str, Callable]] = []
    if constraint.degree_levels:
        requirements.append(("degree_level", lambda actual: actual in constraint.degree_levels))
    if constraint.cohorts:
        requirements.append(("cohort", lambda actual: actual in constraint.cohorts))
    elif constraint.cohort_min is not None or constraint.cohort_max is not None:
        low, high = constraint.cohort_min, constraint.cohort_max
        requirements.append(
            (
                "cohort",
                lambda actual: (low is None or actual >= low) and (high is None or actual <= high),
            )
        )
    if constraint.majors:
        requirements.append(("major", _in_codes(constraint.majors)))
    if constraint.programs:
        requirements.append(("program", _in_codes(constraint.programs)))
    if constraint.statuses:
        requirements.append(("status", lambda actual: actual in constraint.statuses))
    return requirements


def match_profile(constraint: AudienceConstraint, profile: Profile) -> tuple[str, str]:
    """Return a three-way label and its rule reason for one audience branch.

    Included attributes combine with AND; values within an attribute use OR.
    A known exclusion or mismatch gives NOT_APPLIES. Missing profile attributes,
    implicit audiences, and unrepresented requirements abstain with UNCLEAR.
    The data contract lists the reasons in evaluation order.
    """
    if constraint.scope == "implicit":
        return "UNCLEAR", "implicit_audience"
    if constraint.scope == "outside_population":
        return "NOT_APPLIES", "outside_population"
    if profile.status is not None and profile.status in constraint.excluded_statuses:
        return "NOT_APPLIES", "excluded_status"
    unknown = bool(constraint.excluded_statuses and profile.status is None)
    for field, accepts in constraint_requirements(constraint):
        actual = getattr(profile, field)
        if actual is None:
            unknown = True
        elif not accepts(actual):
            return "NOT_APPLIES", f"mismatched_{field}"
    if unknown:
        return "UNCLEAR", "missing_profile_attribute"
    if constraint.unrepresented:
        return "UNCLEAR", "unrepresented_requirement"
    if constraint.scope == "all_students":
        return "APPLIES", "all_students"
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
