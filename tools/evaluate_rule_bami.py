"""Compare rule-proposed evidence spans with frozen and refitted BamiBERT relationship heads."""

import argparse
import copy
import json
import platform
import random
import re
from itertools import product
from pathlib import Path

import joblib
import torch
from compare_notice_pipelines import _metrics, _test_docs
from smartnotice.labeling.span_rules import SpanRules
from smartnotice.modeling.data import (
    LINK_LABELS,
    Document,
    labeled_links,
    load_development,
    sha256,
    span_key,
    tokenize,
)
from smartnotice.modeling.experiment import Settings, load_extractor, write_summary
from smartnotice.modeling.extraction import decode_notice, pair_keys
from smartnotice.modeling.metrics import prf_counts
from smartnotice.schemas import Annotation
from transformers import AutoTokenizer


def _tokens(doc, tokenizer, settings, width):
    blank = Annotation(doc_id=doc.notice.doc_id, annotator_id="inference", spans=[], events=[])
    return tokenize(
        Document(doc.notice, blank, doc.group_id),
        tokenizer,
        settings.length,
        settings.overlap,
        width,
    )


def _aligned(spans, token_doc):
    return {s for s in spans if s[:2] in token_doc.candidates}


def _refit(model, docs, rules, tokenizer, settings, width, device):
    rng = random.Random(settings.seed)
    features, targets, masks = [], [], []

    def capture(_layer, inputs):
        features.append(inputs[0].detach().cpu())

    hook = model.link_head.register_forward_pre_hook(capture)
    try:
        with torch.no_grad():
            for doc in docs:
                td = _tokens(doc, tokenizer, settings, width)
                gold = {
                    (a, b): LINK_LABELS.index(role) for a, b, role in labeled_links(doc.annotation)
                }
                reference = _aligned({span_key(s) for s in doc.annotation.spans}, td)
                proposed = _aligned(rules.predict(doc.notice, phrases=True), td)
                annotated_pairs = set(pair_keys(reference))
                pos = sorted(annotated_pairs.intersection(gold))
                pairs = list(pos)
                for pool in (
                    annotated_pairs.difference(gold),
                    set(pair_keys(proposed)) - annotated_pairs,
                ):
                    pairs.extend(rng.sample(sorted(pool), min(len(pool), max(8, 3 * len(pos)))))
                if pairs:
                    hidden = model.encode(td)
                    logits = model.relations(td, hidden, pairs)
                    masks.append(logits.isneginf().cpu())
                    targets.extend(gold.get(pair, 0) for pair in pairs)
    finally:
        hook.remove()
    x, mask = torch.cat(features).to(device), torch.cat(masks).to(device)
    y = torch.tensor(targets, device=device)
    weights = y.bincount(minlength=len(LINK_LABELS)).clamp_min(1).float().rsqrt()
    head = copy.deepcopy(model.link_head).train()
    opt = torch.optim.AdamW(head.parameters(), lr=0.001)
    for _ in range(12):
        for batch in torch.randperm(len(y), device=device).split(256):
            logits = head(x[batch]).masked_fill(mask[batch], -torch.inf)
            loss = torch.nn.functional.cross_entropy(logits, y[batch], weight=weights)
            opt.zero_grad()
            loss.backward()
            opt.step()
    return head.eval(), dict(
        zip(LINK_LABELS, y.bincount(minlength=len(LINK_LABELS)).tolist(), strict=True)
    )


@torch.no_grad()
def _cache(docs, rules, model, heads, tokenizer, settings, width, variants):
    cache = []
    for doc in docs:
        td = _tokens(doc, tokenizer, settings, width)
        proposals = {k: rules.predict(doc.notice, phrases=k == "gazetteer") for k in variants}
        aligned = {k: _aligned(spans, td) for k, spans in proposals.items()}
        pairs = sorted({pair for spans in aligned.values() for pair in pair_keys(spans)})
        scored = {name: {} for name in heads}
        if pairs:
            hidden = model.encode(td)
            for name, head in heads.items():
                model.link_head = head
                for start in range(0, len(pairs), 512):
                    batch = pairs[start : start + 512]
                    probs = model.relations(td, hidden, batch).softmax(-1)[:, 1:]
                    vals, labels = probs.max(-1)
                    for (a, b), v, i in zip(batch, vals.tolist(), labels.tolist(), strict=True):
                        scored[name][a, b, LINK_LABELS[i + 1]] = v
        cache.append((proposals, aligned, scored))
    return cache


def _links(spans, scores, cuts):
    return {
        (a, b, r)
        for (a, b, r), v in scores.items()
        if a in spans and b in spans and v >= cuts[int(b[2] != "TIME")]
    }


def _nearest(notice, spans):
    actions = sorted(s for s in spans if s[2] == "ACTION")
    for b in sorted(spans):
        if not actions or b[2] == "ACTION":
            continue
        a = min(actions, key=lambda s: (max(0, s[0] - b[1], b[0] - s[1]), s))
        role = b[2]
        if role == "TIME":
            prefix = notice.text[max(0, b[0] - 45) : b[0]].casefold()
            if re.search(r"(?:trước|hạn|đến|chậm nhất)(?:\s+ngày)?\s*[:(]?\s*$", prefix):
                role = "DEADLINE"
            elif re.search(r"(?:từ|bắt đầu)(?:\s+ngày)?\s*[:(]?\s*$", prefix):
                role = "START"
            else:
                role = "EVENT_TIME"
        yield a, b, role


def _evaluate(docs, cache, variant, head, cuts):
    outputs, expected, covered, aligned_gold, saved = {}, set(), set(), set(), []
    aligned_counts = 0
    for doc, (proposals, aligned, scores) in zip(docs, cache, strict=True):
        ident = doc.notice.doc_id
        spans = proposals[variant]
        endpoints = aligned[variant]
        aligned_counts += len(endpoints)
        for a, b, r in labeled_links(doc.annotation):
            key = (ident, a, b, r)
            expected.add(key)
            if a in spans and b in spans:
                covered.add(key)
            if a in endpoints and b in endpoints:
                aligned_gold.add(key)
        links = (
            set(_nearest(doc.notice, endpoints))
            if head == "nearest"
            else _links(endpoints, scores[head], cuts)
        )
        pred = decode_notice(doc.notice, spans, links, "rule-bami-prediction")
        outputs[ident] = spans, pred
        saved.append(
            {
                "doc_id": ident,
                "spans": sorted(spans),
                "links": sorted(links),
                "events": [e.model_dump(mode="json") for e in pred.events],
                "span_ids": {s.span_id: span_key(s) for s in pred.spans},
            }
        )
    result = _metrics(docs, outputs)
    result.update(
        {
            "reference_links_with_both_rule_spans": len(covered),
            "reference_links_with_both_encodable_spans": len(aligned_gold),
            "aligned_rule_spans": aligned_counts,
            "documents": len(docs),
        }
    )
    return result, saved


def _select_cuts(docs, cache, variant, head):
    expected = sum(len(labeled_links(d.annotation)) for d in docs)
    results = {}
    for cuts in product((0.15, 0.30, 0.50, 0.70), (0.35, 0.50, 0.70)):
        tp = count = 0
        for doc, (_, aligned, scores) in zip(docs, cache, strict=True):
            pred = _links(aligned[variant], scores[head], cuts)
            count += len(pred)
            tp += len(pred & labeled_links(doc.annotation))
        results[cuts] = prf_counts(tp, count, expected)["f1"]
    return max(results, key=lambda c: (results[c], c))


def main() -> None:
    """Select on validation, then score the locked rules and relationship head on ordinary test."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("select", "test"))
    for key in ("split", "base", "baseline", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    locked = args.output / "selection.json"
    selecting = args.stage == "select"
    if selecting and args.output.exists() and any(args.output.iterdir()):
        parser.error("Select in a new output directory")
    args.output.mkdir(exist_ok=True, parents=True)
    docs, provenance = load_development(args.split)
    baseline = json.loads((args.baseline / "run.json").read_text())
    paths = {
        "base": args.base / "model.safetensors",
        "tokenizer": args.base / "tokenizer.json",
        "original": args.baseline / "extraction.pt",
        "runner": Path(__file__),
        "rules_code": Path("src/labeling/span_rules.py"),
    }
    hashes = {k: sha256(v) for k, v in paths.items()}
    if (
        provenance["hashes"] != baseline["data"]["hashes"]
        or hashes["base"] != baseline["model_weights_sha256"]
        or hashes["tokenizer"] != baseline["tokenizer_sha256"]
    ):
        raise ValueError("Dataset or base checkpoint differs from the recorded baseline")
    saved = torch.load(paths["original"], map_location="cpu")
    settings = Settings(**saved["settings"])
    torch.manual_seed(settings.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.base, use_fast=True)
    model = load_extractor(args.base, saved, tokenizer.pad_token_id, settings, device).eval()
    rule_file, head_file = args.output / "rules.joblib", args.output / "relationship.pt"
    heads = {"original": model.link_head}
    if selecting:
        rules = SpanRules()
        rules.fit_phrases(d.annotation for d in docs["train"])
        joblib.dump(rules, rule_file)
        heads["refit"], counts = _refit(
            model, docs["train"], rules, tokenizer, settings, saved["width"], device
        )
        torch.save(heads["refit"].state_dict(), head_file)
        evaluation = docs["validation"]
        variants = ("handwritten", "gazetteer")
    else:
        selection = json.loads(locked.read_text())
        if (
            selection["hashes"]
            != {**hashes, "rules": sha256(rule_file), "refit": sha256(head_file)}
            or selection["data"] != provenance["hashes"]
        ):
            raise ValueError("Frozen experiment has changed")
        winner = selection["winner"]
        rules = joblib.load(rule_file)
        if winner["head"] == "refit":
            model.link_head.load_state_dict(torch.load(head_file, map_location=device))
        heads = {winner["head"]: model.link_head}
        variants = (winner["variant"],)
        evaluation = _test_docs(args.split)
    cache = _cache(evaluation, rules, model, heads, tokenizer, settings, saved["width"], variants)
    results, configs = {}, {}
    for variant in variants:
        for head in heads:
            cuts = _select_cuts(evaluation, cache, variant, head) if selecting else winner["cuts"]
            key = f"{variant}-{head}"
            results[key], rows = _evaluate(evaluation, cache, variant, head, cuts)
            configs[key] = {"variant": variant, "head": head, "cuts": cuts}
            if not selecting:
                with (args.output / "test_predictions.jsonl").open("w", encoding="utf8") as stream:
                    for row in rows:
                        stream.write(json.dumps(row) + "\n")
        results[f"{variant}-nearest"], _ = _evaluate(evaluation, cache, variant, "nearest", None)
    if selecting:
        key = max(
            configs, key=lambda k: (results[k]["link"]["micro"]["f1"], results[k]["event"]["f1"])
        )
        write_summary(
            locked,
            {
                "winner": configs[key],
                "configs": configs,
                "selection": "link micro-F1, then exact event F1",
                "hashes": {**hashes, "rules": sha256(rule_file), "refit": sha256(head_file)},
                "data": provenance["hashes"],
                "training_pairs_by_role": counts,
                "seed": settings.seed,
                "torch": torch.__version__,
                "python": platform.python_version(),
                "device": str(device),
                "baseline_revision": baseline["revision"],
                "uv_lock": sha256(Path("uv.lock")),
            },
        )
    write_summary(args.output / f"{args.stage}.json", results)
    print({k: round(v["link"]["micro"]["f1"], 4) for k, v in results.items()}, flush=True)


if __name__ == "__main__":
    main()
