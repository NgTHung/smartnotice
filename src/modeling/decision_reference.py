"""Query external decision models as a zero-shot applicability reference.

Jev (TypeSafe) and d1.2-ultra (Liquid AI) share the System One request shape:
a ``state`` plus named ``choice`` questions, answered with a choice, class
probabilities, and a confidence. Each question sees the state and its own
instructions, so one request carries one event and one question per profile.

Outputs are vendor model predictions. They are a reference point, not one of
the compared course models, and silver-label agreement is not human agreement.
Requests carry only the fields that ``build_inputs`` allowlists; response
records keep identifiers, answers, usage, and hashes, never notice text.
"""

import asyncio
import json
import math
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from random import Random

import httpx
import numpy as np
from smartnotice.io import read_jsonl
from smartnotice.labeling.llm import json_sha256
from smartnotice.modeling.applicability_features import ApplicabilityInput
from smartnotice.modeling.applicability_training import compute_metrics
from smartnotice.modeling.lexicon import Lexicon
from smartnotice.schemas import Annotation, Record

LABELS = ("APPLIES", "NOT_APPLIES", "UNCLEAR")
INSTRUCTIONS_VERSION = "applicability-reference-v1"
TASK = (
    "Decide whether this event from a Vietnamese university notice applies to the "
    "student described by student_profile. Use only the notice state and the profile. "
    "admission_year is the year the student was admitted: K24 or khóa 2024 means "
    "admission in 2024. reference_date is the notice date. A null profile field is unknown."
)
CRITERIA = {
    "APPLIES": "The event's stated audience includes this student and every stated "
    "eligibility condition can be confirmed from the profile.",
    "NOT_APPLIES": "The stated audience excludes this student, for example by admission "
    "year, degree level, major, program, or status, or the event addresses non-students.",
    "UNCLEAR": "The notice does not settle it: no audience is stated, the profile lacks "
    "an attribute the audience requires, the audience uses a requirement the profile "
    "cannot express (such as a class, role, or final year), or an eligibility condition "
    "cannot be checked from the profile.",
}
INSTRUCTIONS_SHA256 = json_sha256(
    {"version": INSTRUCTIONS_VERSION, "task": TASK, "criteria": CRITERIA}
)
_RETRY_STATUSES = {429, 500, 502, 503, 504, 529}


class Provider(Record):
    """Name one decision endpoint, its pinned model, and its key variable."""

    name: str
    url: str
    model: str
    key_env: str
    input_usd_per_mtok: float


PROVIDERS = {
    "jev": Provider(
        name="jev",
        url="https://api.typesafe.ai/v1/systemone",
        model="jev-1.14.0",
        key_env="TYPESAFE_API_KEY",
        input_usd_per_mtok=0.042,
    ),
    "d1.2-ultra": Provider(
        name="d1.2-ultra",
        url="https://api.liquid.ai/decisions/v1/systemone",
        model="d1.2-ultra",
        key_env="LIQUID_API_KEY",
        input_usd_per_mtok=0.042,
    ),
}


def _hard_events(annotations: Sequence[Annotation]) -> set[tuple[str, str]]:
    """Return events with a CONDITION or a listed or outside-population audience."""
    hard = set()
    for annotation in annotations:
        labels = {span.span_id: span.label for span in annotation.spans}
        scopes = {c.audience_span_id: c.scope for c in annotation.audience_constraints}
        for event in annotation.events:
            ids = [argument.span_id for argument in event.arguments]
            if any(labels[i] == "CONDITION" for i in ids) or any(
                scopes.get(i) in {"listed", "outside_population"} for i in ids
            ):
                hard.add((annotation.doc_id, event.event_id))
    return hard


def select_pilot(
    pairs: Sequence[dict],
    annotations: Sequence[Annotation],
    source_types: dict[str, str],
    *,
    quotas: dict[str, int],
    profiles_per_event: int,
    seed: int,
    hard_share: float = 2 / 3,
    max_events_per_doc: int = 3,
) -> list[dict]:
    """Sample events per source and a few labelled profiles per event.

    For each source, about ``hard_share`` of the quota comes from events whose
    reviewed audience is ``listed`` or ``outside_population`` or that carry a
    CONDITION, where the profile comparison matters. At most
    ``max_events_per_doc`` events come from one document. Each event keeps one
    profile per available silver label, in random label order, and is filled
    with random profiles up to ``profiles_per_event``. Constraints and labels
    steer selection only; they are not request inputs. The sample is stratified,
    so its label mix is not a corpus estimate.

    Raises:
        ValueError: if a source has too few events for its quota.
    """
    rng = Random(seed)
    events: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for pair in pairs:
        events[(pair["doc_id"], pair["event_id"])].append(pair)
    hard = _hard_events(annotations)
    chosen: list[tuple[str, str]] = []
    for source, quota in sorted(quotas.items()):
        keys = sorted(key for key in events if source_types[key[0]] == source)
        strata = [[k for k in keys if k in hard], [k for k in keys if k not in hard]]
        for stratum in strata:
            rng.shuffle(stratum)
        per_doc: Counter[str] = Counter()
        picked: list[tuple[str, str]] = []
        passes = [(strata[0], round(quota * hard_share)), (strata[1], quota), (strata[0], quota)]
        for candidates, limit in passes:
            for key in candidates:
                if len(picked) >= limit:
                    break
                if key not in picked and per_doc[key[0]] < max_events_per_doc:
                    picked.append(key)
                    per_doc[key[0]] += 1
        if len(picked) < quota:
            raise ValueError(f"{source}: only {len(picked)} eligible events for quota {quota}")
        chosen.extend(picked)

    sample = []
    for key in sorted(chosen):
        rows = sorted(events[key], key=lambda row: row["profile_id"])
        by_label: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_label[row["label"]].append(row)
        labels = sorted(by_label)
        rng.shuffle(labels)
        kept = [rng.choice(by_label[label]) for label in labels[:profiles_per_event]]
        rest = [row for row in rows if row not in kept]
        kept += rng.sample(rest, min(len(rest), profiles_per_event - len(kept)))
        for row in sorted(kept, key=lambda row: row["profile_id"]):
            sample.append(
                {
                    "doc_id": row["doc_id"],
                    "event_id": row["event_id"],
                    "profile_id": row["profile_id"],
                    "label": row["label"],
                    "source_type": source_types[row["doc_id"]],
                    "hard_event": key in hard,
                }
            )
    return sample


def _code_view(code: str | None, forms: dict[str, list[str]]) -> str | None:
    if code is None or code not in forms:
        return code
    return f"{code} ({', '.join(forms[code])})"


def build_request(
    model: str, inputs: Sequence[ApplicabilityInput], lexicon: Lexicon
) -> tuple[dict, dict[str, str]]:
    """Build one System One request and its question-name to profile-ID map.

    The state holds the event text, reference date, and source type, plus the
    AUDIENCE and CONDITION span texts when the inputs carry them. Each profile
    becomes one choice question over ``LABELS``. Major and program codes are
    shown with their lexicon surface forms. Question names are neutral
    (``q1``, ``q2``, ...) and never reveal profile IDs or labels.

    Raises:
        ValueError: if the inputs are empty, cover more than one event, mix
            audience modes, or repeat a profile.
    """
    if not inputs or len({(i.doc_id, i.event_id) for i in inputs}) != 1:
        raise ValueError("A request must hold one event")
    first = inputs[0]
    if len({i.audience_texts is None for i in inputs}) != 1:
        raise ValueError("A request must use one audience mode")
    if len({i.profile_id for i in inputs}) != len(inputs):
        raise ValueError("A request must not repeat a profile")
    state: dict = {
        "event_text": first.event_text,
        "reference_date": first.reference_date.isoformat() if first.reference_date else None,
        "source": first.source_type,
    }
    if first.audience_texts is not None:
        state["audience_spans"] = first.audience_texts
        state["condition_spans"] = first.condition_texts
    questions, names = {}, {}
    for number, item in enumerate(inputs, 1):
        name = f"q{number}"
        names[name] = item.profile_id
        profile = {
            "admission_year": item.cohort,
            "degree_level": item.degree_level,
            "major": _code_view(item.major, lexicon.majors),
            "program": _code_view(item.program, lexicon.programs),
            "status": item.status,
        }
        questions[name] = {
            "type": "choice",
            "instructions": {"task": TASK, "student_profile": profile},
            "criteria": dict(CRITERIA),
        }
    return {"model": model, "state": state, "questions": questions}, names


def parse_answers(body: dict, questions: dict[str, str]) -> dict[str, dict]:
    """Map each profile ID to its validated choice, probabilities, and confidence.

    Probabilities must cover exactly ``LABELS`` with finite values in [0, 1]
    that sum to 1 within 0.02.

    Raises:
        ValueError: naming the question whose answer is missing or invalid.
    """
    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("response has no answers object")
    parsed = {}
    for name, profile_id in questions.items():
        answer = answers.get(name)
        if not isinstance(answer, dict) or answer.get("choice") not in LABELS:
            raise ValueError(f"question {name}: missing answer or unknown choice")
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != set(LABELS):
            raise ValueError(f"question {name}: probabilities must cover {', '.join(LABELS)}")
        values = [probabilities[label] for label in LABELS]
        if not all(isinstance(v, int | float) and math.isfinite(v) and 0 <= v <= 1 for v in values):
            raise ValueError(f"question {name}: probabilities must lie in [0, 1]")
        if abs(sum(values) - 1) > 0.02:
            raise ValueError(f"question {name}: probabilities must sum to 1")
        confidence = answer.get("confidence")
        parsed[profile_id] = {
            "choice": answer["choice"],
            "probabilities": {label: float(probabilities[label]) for label in LABELS},
            "confidence": float(confidence) if isinstance(confidence, int | float) else None,
        }
    return parsed


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    header = response.headers.get("retry-after") if response is not None else None
    try:
        return max(0.0, float(header)) if header is not None else min(0.5 * 2**attempt, 30.0)
    except ValueError:
        return min(0.5 * 2**attempt, 30.0)


async def run_requests(
    jobs: Sequence[dict],
    provider: Provider,
    api_key: str,
    output: Path,
    *,
    concurrency: int,
    rate: float,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_attempts: int = 5,
    timeout: float = 30.0,
) -> Counter[str]:
    """Send jobs within a request rate and append one record per finished job.

    Each job has ``request_id``, ``payload``, ``questions`` (name to profile
    ID), and ``meta``. Jobs already recorded with status 200 are skipped, so an
    interrupted run resumes. 429, 5xx, 529, and transport errors are retried
    with ``Retry-After`` or exponential backoff up to ``max_attempts``. Other
    statuses and invalid answers are recorded without retry. Records hold no
    request text and no error bodies, which can echo the input. Returns status
    counts for the jobs sent.
    """
    done = set()
    if output.exists():
        done = {row["request_id"] for row in read_jsonl(output) if row.get("status") == 200}
    output.parent.mkdir(parents=True, exist_ok=True)
    gate, write_lock, pace_lock = asyncio.Semaphore(concurrency), asyncio.Lock(), asyncio.Lock()
    next_slot = [time.monotonic()]
    statuses: Counter[str] = Counter()

    async def pace() -> None:
        async with pace_lock:
            wait = next_slot[0] - time.monotonic()
            next_slot[0] = max(next_slot[0], time.monotonic()) + 1 / rate
        if wait > 0:
            await sleep(wait)

    async def send(client: httpx.AsyncClient, job: dict, handle) -> None:
        async with gate:
            record = {
                "request_id": job["request_id"],
                "provider": provider.name,
                "requested_model": provider.model,
                "payload_sha256": json_sha256(job["payload"]),
                **job["meta"],
                "model": None,
                "status": None,
                "error": None,
                "answers": None,
                "usage": None,
            }
            for attempt in range(1, max_attempts + 1):
                await pace()
                started = time.perf_counter()
                response = None
                try:
                    response = await client.post(provider.url, json=job["payload"])
                    record["status"] = response.status_code
                except httpx.TransportError as exc:
                    record["status"], record["error"] = None, type(exc).__name__
                record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
                record["attempts"] = attempt
                retry = record["status"] is None or record["status"] in _RETRY_STATUSES
                if not retry or attempt == max_attempts:
                    break
                await sleep(_retry_delay(response, attempt))
            if response is not None and record["status"] == 200:
                body = response.json()
                record["model"] = body.get("model")
                record["usage"] = body.get("usage")
                try:
                    record["answers"] = parse_answers(body, job["questions"])
                except ValueError as exc:
                    record["status"], record["error"] = "invalid_response", str(exc)
            elif record["status"] is not None:
                record["error"] = f"http_{record['status']}"
            record["finished_at"] = datetime.now(UTC).isoformat()
            statuses[str(record["status"])] += 1
            async with write_lock:
                handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()

    headers = {"Authorization": f"Bearer {api_key}"}
    pending = [job for job in jobs if job["request_id"] not in done]
    async with httpx.AsyncClient(headers=headers, timeout=timeout, transport=transport) as client:
        with output.open("a", encoding="utf-8", newline="\n") as handle:
            await asyncio.gather(*(send(client, job, handle) for job in pending))
    return statuses


def _latest(rows: Sequence[dict]) -> dict[tuple, dict]:
    latest = {}
    for row in rows:
        latest[(row["mode"], row["doc_id"], row["event_id"], row["repeat"])] = row
    return latest


def _calibration(gold: list[str], probs: np.ndarray, bins: int = 10) -> tuple[float, list, float]:
    onehot = np.array([[float(g == label) for label in LABELS] for g in gold])
    brier = float(((probs - onehot) ** 2).sum(axis=1).mean())
    confidence = probs.max(axis=1)
    correct = probs.argmax(axis=1) == onehot.argmax(axis=1)
    index = np.minimum((confidence * bins).astype(int), bins - 1)
    table, ece = [], 0.0
    for b in range(bins):
        mask = index == b
        count = int(mask.sum())
        if count:
            accuracy, mean_conf = float(correct[mask].mean()), float(confidence[mask].mean())
            ece += count / len(gold) * abs(accuracy - mean_conf)
            table.append(
                {"bin": b, "count": count, "accuracy": accuracy, "mean_confidence": mean_conf}
            )
    return brier, table, float(ece)


def _bootstrap_macro_f1(
    gold: list[str], pred: list[str], groups: list[str], seed: int, n_boot: int
) -> list[float]:
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[group].append(index)
    names = sorted(by_group)
    rng = np.random.default_rng(seed)
    scores = []
    for _ in range(n_boot):
        drawn = rng.choice(len(names), size=len(names), replace=True)
        rows = [i for g in drawn for i in by_group[names[g]]]
        sub_gold, sub_pred = [gold[i] for i in rows], [pred[i] for i in rows]
        scores.append(compute_metrics(sub_gold, sub_pred, np.ones(len(rows)))["macro_f1"])
    return [float(np.percentile(scores, 2.5)), float(np.percentile(scores, 97.5))]


def _segment(sample: list[dict], answers: dict, seed: int, n_boot: int) -> dict:
    kept = [row for row in sample if row["key"] in answers]
    result: dict = {"pairs": len(sample), "missing_pairs": len(sample) - len(kept)}
    if not kept:
        return result
    gold = [row["label"] for row in kept]
    pred = [answers[row["key"]]["choice"] for row in kept]
    probs = np.array([[answers[row["key"]]["probabilities"][k] for k in LABELS] for row in kept])
    brier, table, ece = _calibration(gold, probs)
    groups = [row.get("group_id", row["doc_id"]) for row in kept]
    return result | {
        "events": len({(row["doc_id"], row["event_id"]) for row in kept}),
        "groups": len(set(groups)),
        "metrics": compute_metrics(gold, pred, np.ones(len(kept))),
        "macro_f1_ci95_group_bootstrap": _bootstrap_macro_f1(gold, pred, groups, seed, n_boot),
        "brier": brier,
        "ece": ece,
        "ece_bins": table,
    }


def predictions(rows: Sequence[dict], mode: str, repeat: int = 0) -> dict[tuple, dict]:
    """Return answers by (doc_id, event_id, profile_id) for one mode and pass."""
    found = {}
    for (row_mode, doc_id, event_id, row_repeat), row in _latest(rows).items():
        if row_mode == mode and row_repeat == repeat and row.get("status") == 200:
            for profile_id, answer in (row.get("answers") or {}).items():
                found[(doc_id, event_id, profile_id)] = answer
    return found


def score_pilot(
    rows: Sequence[dict],
    sample: Sequence[dict],
    *,
    seed: int,
    n_boot: int = 1000,
    input_usd_per_mtok: float | None = None,
) -> dict:
    """Score one provider's pilot answers against silver labels.

    The latest record per (mode, document, event, repeat) counts. Metrics use
    first-pass answers with unweighted pairs, per mode for all pairs and for
    each source type, with a 95% macro-F1 interval from bootstrap resampling
    of ``group_id`` (document ID when absent). Brier score sums squared class
    errors; ECE uses ten equal-width top-label confidence bins and reports
    their counts. Consistency compares first and second passes. Unanswered
    sample pairs are reported as missing, never scored as errors.
    """
    latest = _latest(rows)
    ok = [row for row in latest.values() if row.get("status") == 200]
    failed = Counter(str(row.get("status")) for row in latest.values() if row.get("status") != 200)
    keyed = [row | {"key": (row["doc_id"], row["event_id"], row["profile_id"])} for row in sample]
    scores: dict = {
        "label_origin": "constraint_rule silver labels; answers are vendor model predictions",
        "requests": {"total": len(latest), "ok": len(ok), "failed_by_status": dict(failed)},
        "modes": {},
        "consistency": {},
    }
    first_pass = [row["latency_ms"] for row in ok if row["repeat"] == 0]
    if first_pass:
        scores["latency_ms"] = {
            "n": len(first_pass),
            "p50": float(np.percentile(first_pass, 50)),
            "p95": float(np.percentile(first_pass, 95)),
        }
    tokens = sum((row.get("usage") or {}).get("input_tokens", 0) for row in ok)
    scores["input_tokens"] = tokens
    if input_usd_per_mtok is not None:
        scores["input_cost_usd"] = tokens / 1e6 * input_usd_per_mtok
    for mode in sorted({key[0] for key in latest}):
        answers = predictions(rows, mode)
        segments = {"all": keyed} | {
            source: [row for row in keyed if row["source_type"] == source]
            for source in sorted({row["source_type"] for row in keyed})
        }
        scores["modes"][mode] = {
            name: _segment(part, answers, seed, n_boot) for name, part in segments.items()
        }
        repeat = predictions(rows, mode, repeat=1)
        both = [key for key in repeat if key in answers]
        if both:
            diffs = [
                max(
                    abs(answers[k]["probabilities"][c] - repeat[k]["probabilities"][c])
                    for c in LABELS
                )
                for k in both
            ]
            scores["consistency"][mode] = {
                "pairs": len(both),
                "same_choice": sum(answers[k]["choice"] == repeat[k]["choice"] for k in both)
                / len(both),
                "max_abs_prob_diff": float(max(diffs)),
            }
    return scores


def agreement(rows_a: Sequence[dict], rows_b: Sequence[dict], mode: str) -> dict:
    """Return how often two providers choose the same label on shared pairs."""
    first, second = predictions(rows_a, mode), predictions(rows_b, mode)
    shared = [key for key in first if key in second]
    same = sum(first[key]["choice"] == second[key]["choice"] for key in shared)
    return {"pairs": len(shared), "same_choice": same / len(shared) if shared else None}
