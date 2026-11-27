import json
from pathlib import Path

import pytest
from smartnotice.cli import main
from smartnotice.io import read_jsonl
from smartnotice.labeling.applicability import match_profile
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.schemas import AudienceConstraint, Profile

ROOT = Path(__file__).resolve().parents[1]

LISTED = AudienceConstraint(
    audience_span_id="a",
    scope="listed",
    cohorts=[2024],
    programs=["CLC"],
    excluded_statuses=["defended"],
)
BOUNDED = AudienceConstraint(
    audience_span_id="b", scope="listed", cohort_max=2022, degree_levels=["master"]
)
EVERYONE = AudienceConstraint(
    audience_span_id="c", scope="all_students", excluded_statuses=["graduated"]
)
IMPLICIT = AudienceConstraint(audience_span_id="d", scope="implicit")


def _reasons(constraint, profiles):
    return {match_profile(constraint, profile)[1] for profile in profiles}


def test_profiles_cover_match_mismatch_exclusion_and_missing_cases():
    profiles = generate_profiles([LISTED, BOUNDED, EVERYONE, IMPLICIT], seed=7)
    assert {
        "all_constraints_match",
        "mismatched_cohort",
        "excluded_status",
        "missing_profile_attribute",
    } <= _reasons(LISTED, profiles)
    assert {"all_constraints_match", "mismatched_cohort", "mismatched_degree_level"} <= _reasons(
        BOUNDED, profiles
    )
    assert {"all_students", "excluded_status"} <= _reasons(EVERYONE, profiles)


def test_profiles_use_only_observed_codes_and_unique_ids():
    profiles = generate_profiles([LISTED, BOUNDED, EVERYONE], seed=7)
    assert all(isinstance(profile, Profile) for profile in profiles)
    assert len({p.profile_id for p in profiles}) == len(profiles)
    assert {p.program for p in profiles} <= {"CLC", None}
    assert {p.major for p in profiles} == {None}
    attributes = [p.model_dump(exclude={"profile_id"}) for p in profiles]
    assert len(attributes) == len({json.dumps(a, sort_keys=True) for a in attributes})


def test_profile_generation_repeats_for_one_seed():
    first = generate_profiles([LISTED, BOUNDED, EVERYONE], seed=11)
    assert first == generate_profiles([LISTED, BOUNDED, EVERYONE], seed=11)


def test_repeated_constraints_add_no_profiles():
    copies = [
        constraint.model_copy(update={"audience_span_id": f"{constraint.audience_span_id}-copy"})
        for constraint in [EVERYONE, LISTED, EVERYONE]
    ]
    distinct = generate_profiles([LISTED, BOUNDED, EVERYONE], seed=7)
    assert generate_profiles([LISTED, BOUNDED, EVERYONE, *copies], seed=7) == distinct


def test_profile_generation_requires_a_resolvable_constraint():
    with pytest.raises(ValueError, match="constraint"):
        generate_profiles([IMPLICIT], seed=7)


def test_cli_generates_profiles_with_a_generation_record(tmp_path, capsys):
    output = tmp_path / "profiles.jsonl"
    annotations = ROOT / "data/annotations/examples/events.jsonl"
    main(
        [
            "generate-profiles",
            "--annotations",
            str(annotations),
            "--output",
            str(output),
            "--seed",
            "5",
        ]
    )
    profiles = [Profile.model_validate(row) for row in read_jsonl(output)]
    record = json.loads(output.with_suffix(".record.json").read_text(encoding="utf-8"))
    assert record["seed"] == 5
    assert record["profile_count"] == len(profiles) > 0
    assert len(record["annotations_sha256"]) == 64
    assert len(record["profile_set_sha256"]) == 64
    assert str(output) in capsys.readouterr().out
