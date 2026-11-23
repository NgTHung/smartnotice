"""Train BamiBERT span and action-conditioned role selectors on the private Kaggle bundle."""

import argparse
import bisect
import json
import math
import random
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import torch
from tokenizers import Tokenizer
from torch import nn
from torch.nn import functional as F
from transformers import AutoModel

TYPES = ("ACTION", "TIME", "AUDIENCE", "CONDITION", "CHANNEL", "DOCUMENT")
ROLES = ("START", "DEADLINE", "EVENT_TIME", *TYPES[2:])
CUTS = (0.10, 0.18, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85)
WIDTH = 64
SEED = 42


def _write(path, data):
    temp = path.with_suffix(".part")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
    temp.replace(path)


def _windows(rows, tok):
    for doc in rows:
        text = doc.pop("text")
        doc["spans"] = {tuple(s) for s in doc.get("spans", [])}
        doc["links"] = {(tuple(a), tuple(b), r) for a, b, r in doc.get("links", [])}
        words = tok.encode(text, add_special_tokens=False)
        offsets = []
        for a, b in words.offsets:
            while a < b and text[a].isspace():
                a += 1
            while a < b and text[b - 1].isspace():
                b -= 1
            offsets.append((a, b))
        doc["starts"] = [s[0] for s in doc["sentences"]]
        doc["token_ids"] = words.ids
        doc["bounds"] = offsets
        doc["windows"] = []
        for start in range(0, len(offsets), 128):
            part = offsets[start : start + 192]
            ids = words.ids[start : start + 192]
            sids = []
            for a, b in part:
                i = bisect.bisect_right(doc["starts"], a) - 1
                sids.append(i if a < b and i >= 0 and b <= doc["sentences"][i][1] else -100)
            doc["windows"].append((ids, part, sids))
            if start + 192 >= len(offsets):
                break


def _actions(doc):
    return {s for s in doc["spans"] if s[2] == "ACTION"}


def _examples(rows, stage, queries=None, training=False, seed=SEED):
    rng = random.Random(seed)
    examples = []
    for doc in rows:
        by_action = defaultdict(set)
        for a, b, r in doc["links"]:
            by_action[a].add((*b[:2], r))
        anchors = (
            [None]
            if stage == "span"
            else sorted(_actions(doc) if queries is None else queries[doc["id"]])
        )
        if training and stage == "role":
            # Nearby incomplete action phrases teach the selector to abstain.
            for a, b, _ in list(anchors):
                inner = [e for s, e in doc["bounds"] if a < e < b]
                if inner and rng.random() < 0.25:
                    false = (a, inner[-1], "ACTION")
                    if false not in by_action and false not in _actions(doc):
                        anchors.append(false)
        for anchor in anchors:
            if anchor is None:
                query, origin, expected = [], None, doc["spans"]
            else:
                a, b, _ = anchor
                query = [
                    t
                    for t, (s, e) in zip(doc["token_ids"], doc["bounds"], strict=True)
                    if s < e and s < b and a < e
                ][:48]
                origin = bisect.bisect_right(doc["starts"], a) - 1
                expected = by_action.get(anchor, set())
            matches, empty = [], []
            for ids, offsets, sids in doc["windows"]:
                left = {a: i for i, (a, b) in reversed(list(enumerate(offsets))) if a < b}
                right = {b: i for i, (a, b) in enumerate(offsets) if a < b}
                positives = []
                for a, b, label in expected:
                    i, j = left.get(a, -1), right.get(b, -1)
                    if 0 <= i <= j < i + WIDTH and sids[i] >= 0 and sids[i] == sids[j]:
                        positives.append((i, j, (TYPES if anchor is None else ROLES).index(label)))
                ex = (doc["id"], anchor, query, origin, ids, offsets, sids, positives)
                (matches if positives else empty).append(ex)
            if training and stage == "role":
                empty = rng.sample(empty, min(len(empty), max(1, len(matches))))
            examples.extend(matches + empty)
    return examples


class BoundaryModel(nn.Module):
    """Use a Vietnamese encoder and a label-specific biaffine score for each boundary pair."""

    def __init__(self, encoder, labels):
        super().__init__()
        self.encoder = encoder
        hidden = encoder.config.hidden_size
        self.distance = nn.Embedding(35, hidden)
        nn.init.zeros_(self.distance.weight)
        self.start = nn.Linear(hidden, 32)
        self.end = nn.Linear(hidden, 32)
        self.weight = nn.Parameter(torch.empty(labels, 33, 33))
        nn.init.normal_(self.weight, std=0.02)
        self.bias = nn.Parameter(torch.full((labels,), -3.0))

    def forward(self, ids, indices, relative, marked):
        """Return float logits for each label and token pair in the context window."""
        embedded = self.encoder.get_input_embeddings()(ids)
        h = self.encoder(
            inputs_embeds=embedded + self.distance(marked), attention_mask=ids.ne(1)
        ).last_hidden_state
        h = h.gather(1, indices.unsqueeze(-1).expand(-1, -1, h.size(-1))) + self.distance(relative)
        left = F.pad(self.start(h).tanh(), (0, 1), value=1)
        right = F.pad(self.end(h).tanh(), (0, 1), value=1)
        return (
            torch.einsum("bix,lxy,bjy->blij", left, self.weight, right).float()
            + self.bias[None, :, None, None]
        )


def _batch(batch, device):
    ids, indices, relative, marked, sids = [], [], [], [], []
    positives = []
    for n, (_, anchor, q, origin, context, offsets, se, labels) in enumerate(batch):
        prefix = [0, *q, 2, 2] if anchor else [0]
        tokens = prefix + context + [2]
        ids.append(tokens)
        indices.append(list(range(len(prefix), len(prefix) + len(context))))
        relative.append(
            [min(15, max(-15, s - origin)) + 16 if origin is not None else 0 for s in se]
        )
        marked.append(
            [0] * len(prefix)
            + [
                33 if anchor and a < b and a < anchor[1] and anchor[0] < b else 0
                for a, b in offsets
            ]
            + [0]
        )
        sids.append(se)
        positives.extend((n, label, i, j) for i, j, label in labels)

    def pad(rows, value):
        width = max(map(len, rows))
        return torch.tensor([r + [value] * (width - len(r)) for r in rows], device=device)

    sentences = pad(sids, -100)
    idx = torch.arange(sentences.size(1), device=device)
    delta = idx[None, :] - idx[:, None]
    mask = (
        (sentences[:, :, None] == sentences[:, None, :])
        & (sentences[:, :, None] >= 0)
        & (delta >= 0)
        & (delta < WIDTH)
    )
    return (pad(ids, 1), pad(indices, 0), pad(relative, 0), pad(marked, 0)), mask, positives


@torch.inference_mode()
def _scores(model, examples, stage, device, batch_size):
    model.eval()
    result = defaultdict(dict)
    labels = TYPES if stage == "span" else ROLES
    for k in range(0, len(examples), batch_size):
        batch = examples[k : k + batch_size]
        inputs, mask, _ = _batch(batch, device)
        with torch.autocast(device.type, enabled=device.type == "cuda"):
            logits = model(*inputs)
        scores = logits.sigmoid().masked_fill(~mask[:, None], 0)
        vals, positions = scores.flatten(2).topk(min(24, scores.size(2) ** 2), dim=2)
        size = scores.size(2)
        for (ident, anchor, _, _, _, offsets, _, _), vs, ps in zip(
            batch, vals.tolist(), positions.tolist(), strict=True
        ):
            cache = result[ident]
            for label, values, locs in zip(labels, vs, ps, strict=True):
                for v, pos in zip(values, locs, strict=True):
                    if v < CUTS[0]:
                        break
                    i, j = divmod(pos, size)
                    a, b = offsets[i][0], offsets[j][1]
                    span = (a, b, label)
                    key = (
                        span
                        if stage == "span"
                        else (anchor, (a, b, "TIME" if label in ROLES[:3] else label), label)
                    )
                    cache[key] = max(v, cache.get(key, 0))
    return result


def _counts(rows, scores, stage, cutoffs, label=None):
    tp = pred = ref = 0
    for doc in rows:
        gold = doc["spans" if stage == "span" else "links"]
        chosen = {
            s
            for s, v in scores.get(doc["id"], {}).items()
            if v >= cutoffs.get(s[-1], 1) and (label is None or s[-1] == label)
        }
        target = {s for s in gold if label is None or s[-1] == label}
        tp += len(chosen & target)
        pred += len(chosen)
        ref += len(target)
    return {"matched": tp, "predicted": pred, "expected": ref, "f1": 2 * tp / max(1, pred + ref)}


def _train(model, train_examples, valid_examples, rows, stage, epochs, batch_size, device, output):
    labels = TYPES if stage == "span" else ROLES
    params = [p for n, p in model.named_parameters() if not n.startswith("encoder.")]
    opt = torch.optim.AdamW(
        [{"params": model.encoder.parameters(), "lr": 2e-5}, {"params": params, "lr": 6e-4}],
        weight_decay=0.01,
    )
    total = epochs * math.ceil(len(train_examples) / batch_size)

    def schedule(step):
        warm = max(1, total // 12)
        return min((step + 1) / warm, max(0.05, (total - step) / max(1, total - warm)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(opt, schedule)
    scaler = torch.amp.GradScaler(device.type, enabled=device.type == "cuda")
    rng = random.Random(SEED)
    best = -1
    history = []
    for epoch in range(epochs):
        model.train()
        rng.shuffle(train_examples)
        for k in range(0, len(train_examples), batch_size):
            batch = train_examples[k : k + batch_size]
            inputs, mask, positives = _batch(batch, device)
            with torch.autocast(device.type, enabled=device.type == "cuda"):
                logits = model(*inputs)
            targets = torch.zeros_like(logits)
            if positives:
                targets[tuple(torch.tensor(positives, device=device).T)] = 1
            prob = logits.sigmoid().detach()
            weight = torch.where(targets.bool(), (1 - prob) ** 2, 0.25 * prob**2)
            loss = (
                F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
                * weight
                * mask[:, None]
            ).sum() / max(len(batch), len(positives))
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss")
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
            scaler.step(opt)
            scaler.update()
            scheduler.step()
        scores = _scores(model, valid_examples, stage, device, batch_size)
        cuts = {
            label: max(
                CUTS, key=lambda c: (_counts(rows, scores, stage, {label: c}, label)["f1"], c)
            )
            for label in labels
        }
        score = _counts(rows, scores, stage, cuts)
        criterion = score["f1"]
        if stage == "span":
            action = _counts(rows, scores, stage, cuts, "ACTION")
            criterion = (criterion + action["f1"]) / 2
        history.append({"epoch": epoch + 1, "validation": score, "cuts": cuts})
        print(stage, epoch + 1, score, flush=True)
        if criterion > best:
            best = criterion
            torch.save(
                {n: p.detach().cpu().half() for n, p in model.state_dict().items()},
                output / f"{stage}.pt",
            )
            best_cuts = cuts
        _write(output / f"{stage}-history.json", history)
    model.load_state_dict(torch.load(output / f"{stage}.pt", map_location="cpu"))
    return best_cuts


def _save_predictions(rows, span_scores, role_scores, span_cuts, role_cuts, path):
    records = []
    for d in rows:
        ident = d["id"]
        spans = {s for s, v in span_scores.get(ident, {}).items() if v >= span_cuts[s[-1]]}
        links = {r for r, v in role_scores.get(ident, {}).items() if v >= role_cuts[r[-1]]}
        records.append(
            {
                "doc_id": ident,
                "stage_one_spans": sorted(spans),
                "spans": sorted(spans | {b for a, b, r in links}),
                "links": sorted(links),
            }
        )
    _write(path, records)


def main() -> None:
    """Train both selectors and export frozen predictions as source offsets and labels."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("/kaggle/input"))
    parser.add_argument("--output", type=Path, default=Path("/kaggle/working"))
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    start = time.monotonic()
    torch.manual_seed(SEED)
    if not torch.cuda.is_available():
        raise RuntimeError("GPU required for the recorded run")
    device = torch.device("cuda")
    print("GPU:", torch.cuda.get_device_name(), flush=True)
    with tempfile.TemporaryDirectory() as scratch:
        roots = list(args.data.rglob("provenance.json"))
        if roots:
            root = roots[0].parent
        else:
            root = Path(scratch)
            archive = next(args.data.rglob("experiment.zip"))
            with zipfile.ZipFile(archive) as z:
                for name in (
                    "train.json",
                    "validation.json",
                    "test.json",
                    "provenance.json",
                    "base/config.json",
                    "base/model.safetensors",
                    "base/tokenizer.json",
                    "base/tokenizer_config.json",
                    "base/special_tokens_map.json",
                ):
                    z.extract(name, root)
        data = {
            s: json.loads((root / f"{s}.json").read_text(encoding="utf8"))
            for s in ("train", "validation", "test")
        }
        tok = Tokenizer.from_file(str(root / "base/tokenizer.json"))
        tok.no_truncation()
        tok.no_padding()
        for rows in data.values():
            _windows(rows, tok)
        train, valid, test = (data[s] for s in ("train", "validation", "test"))
        if {d["group"] for d in train} & {d["group"] for d in valid}:
            raise ValueError("Group overlap")
        span = BoundaryModel(
            AutoModel.from_pretrained(root / "base", add_pooling_layer=False), len(TYPES)
        ).to(device)
        span_cuts = _train(
            span,
            _examples(train, "span"),
            _examples(valid, "span"),
            valid,
            "span",
            args.epochs,
            args.batch,
            device,
            args.output,
        )
        span_outputs = {}
        predicted = {}
        for part, rows in (("validation", valid), ("test", test)):
            span_outputs[part] = _scores(span, _examples(rows, "span"), "span", device, args.batch)
            predicted[part] = {
                d["id"]: {
                    s
                    for s, v in span_outputs[part].get(d["id"], {}).items()
                    if s[-1] == "ACTION" and v >= span_cuts["ACTION"]
                }
                for d in rows
            }
        role = BoundaryModel(span.encoder, len(ROLES)).to(device)
        role_cuts = _train(
            role,
            _examples(train, "role", training=True),
            _examples(valid, "role", predicted["validation"]),
            valid,
            "role",
            args.epochs,
            args.batch,
            device,
            args.output,
        )
        oracle = _scores(role, _examples(valid, "role"), "role", device, args.batch)
        oracle_result = _counts(valid, oracle, "role", role_cuts)
        for part, rows in (("validation", valid), ("test", test)):
            scores = _scores(
                role, _examples(rows, "role", predicted[part]), "role", device, args.batch
            )
            _save_predictions(
                rows,
                span_outputs[part],
                scores,
                span_cuts,
                role_cuts,
                args.output / f"{part}-predictions.json",
            )
        _write(
            args.output / "run.json",
            {
                "span_cuts": span_cuts,
                "role_cuts": role_cuts,
                "oracle_validation": oracle_result,
                "seed": SEED,
                "epochs_each": args.epochs,
                "batch": args.batch,
                "gpu": torch.cuda.get_device_name(),
                "torch": torch.__version__,
                "seconds": time.monotonic() - start,
                "peak_cuda_bytes": torch.cuda.max_memory_allocated(),
                "counts": {s: len(rows) for s, rows in data.items()},
                "provenance": json.loads((root / "provenance.json").read_text()),
            },
        )


if __name__ == "__main__":
    main()
