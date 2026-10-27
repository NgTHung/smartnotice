# HCMUS crawler reference

The crawler turns one public HCMUS student listing into a bounded set of source snapshots and prepared notices. Contributors use this reference to locate the owning code, understand failures, and change the source adapter without weakening collection provenance. The [collection protocol](collection.md) owns the operator procedure and human review, and the [README](../README.md) owns working commands.

## Follow the module boundaries

| Owner | Guarantee |
|---|---|
| [`collectors/web.py`](../src/collectors/web.py) | Robots policy, origin checks, spacing, bounded decoding, media types, and redirects |
| [`collectors/hcmus.py`](../src/collectors/hcmus.py) | Pure listing/detail parsing and source-specific sampling/date evidence |
| [`collectors/crawl.py`](../src/collectors/crawl.py) | Run validation, bounded iteration, snapshot retention, deduplication, checkpoints, and preparation |
| [`collectors/local.py`](../src/collectors/local.py) | Content-addressed selected sources and manifest provenance |
| [`io.py`](../src/io.py) | UTF-8 JSONL serialization and atomic replacement for a single writer |
| [`schemas.py`](../src/schemas.py) | Typed candidate, index, log, summary, and existing Notice boundaries |
| [`cli.py`](../src/cli.py) | CLI options, client lifetime, summary display, and exit codes |

`crawl_web` takes an injected `WebCollector` so automated tests use `httpx.MockTransport` without live requests. One client and collector live for the entire run, preserving robots cache and per-origin timing. The package mapping remains `smartnotice` directly under `src/`; no second package tree or dependency is added.

## Check requests before following redirects

`WebCollector.fetch(url, allowed_origin=...)` validates the current origin before any request, including robots.txt at a redirected destination. The HCMUS runner fixes the allowed origin to its listing origin. Default ports are normalized; other explicit ports remain distinct. Cross-origin redirects raise `CollectionPolicyError` before contacting the other host. Callers omitting the option retain explicit-URL collection across robots-checked origins.

Robots 404 follows the existing allow policy. Other unsuccessful robots responses, redirects included, stop collection. Allowed pages use the maximum of configured spacing, parsed Crawl-delay, and average seconds per request from Request-rate. Robots are cached per collector, with no refresh during a run. Fractional Crawl-delay values unsupported by Python's `RobotFileParser` are not interpreted. URL syntax validation does not itself perform DNS/private-address enforcement; the HCMUS runner's fixed origin restricts its source.

Every response is streamed through HTTPX decoding and checked against the decoded byte limit. The reconstructed response drops content-encoding, content-length, and transfer-encoding headers so decoded content is not decompressed twice. HTML media types are `text/html` and `application/xhtml+xml`. A response can be HTML yet contain a login page; the adapter's title/body checks reject pages outside its expected structure. These checks do not guarantee detection of every soft error page.

## Parse the configured source

| Setting in `hcmus.py` | Purpose |
|---|---|
| `LIST_URL` | Fixed HCMUS student listing |
| `LINK_SELECTOR` | Detail links within listing title blocks |
| `TITLE_SELECTOR` | Exactly one article title |
| `BODY_SELECTOR` | Exactly one article body, also persisted for `prepare` |
| `DATE_SELECTOR` | Displayed publication evidence, separate from body dates |

Discovery resolves relative links, drops fragments, normalizes default ports, retains queries, and removes repeated URLs. It ignores unsupported schemes, malformed/credentialed/off-origin URLs and obvious file extensions. No discovered links raises a layout error. Zero eligible academic titles produces a valid partial run.

Title sampling uses NFC-normalized, case-folded substring rules. Action-prose sampling removes links, embedded media, and view counters, then ignores paragraphs/sentences handing the reader to attached files. At least one remaining segment must contain a configured action phrase at word boundaries. Full prepared text retains link labels and useful attachment references. A valid notice expressed only through a linked instruction, an unsupported action synonym, or a paragraph mixed with an attachment handoff can be excluded. Change these heuristics with synthetic regression cases and source review; do not describe them as model predictions.

`parse_html` removes `.post-views` counters as article boilerplate. It preserves ordinary paragraphs and table header/value relationships through the existing parser. Attachment handoffs retained alongside other action prose receive `attachment_context_review`. Merged table cells and Unicode replacement characters receive their own review warnings; they do not silently change raw bytes.

Publication candidates come from the displayed `DD/MM/YYYY` date. If publication metadata contains a timezone, compare its date in UTC+07:00. Without a timezone, compare the written calendar date. Multiple evidence nodes, invalid values, out-of-range timezone conversions, or disagreement produce a review status. A matching pair is `unverified`, not a verified reference date. No modified-time field is used.

## Interpret outcomes

| Condition | Runner behavior |
|---|---|
| Target reached and preparation succeeds | `complete`, exit 0 |
| No eligible titles, exhausted listing, or detail budget exhausted | `partial`, exit 2; prepare selected subset |
| Detail HTTP 404 or 410 | Record reason and continue |
| Detail non-HTML media type | Record `non_html` and continue; no HTML snapshot |
| Body/title mismatch, title excluded, or no independent action prose | Save snapshot, record stable rejection reason, continue |
| Duplicate prepared text | Save snapshot and `duplicate_of`; count the first source only |
| Missing/invalid/conflicting publication date | Retain notice with date evidence and pending review |
| Short text, merged cells, or replacement characters | Retain notice with warnings |
| Robots denial, off-origin redirect, missing redirect location, redirect limit | Stop, checkpoint failure, exit 1 |
| Other HTTP error, network/decoding failure, or excessive decoded body | Stop, checkpoint failure, exit 1 |
| Storage error or manifest conflict | Stop; preserve earlier files when possible; exit 1 |
| Preparation failure | Record `preparation` failure; never report successful completion |
| Keyboard interruption | Best-effort checkpoint, exit 130 |
| Unexpected exception | Best-effort checkpoint, then re-raise with a traceback |

Each selected detail URL consumes one candidate attempt, regardless of redirects or rejection. The candidate budget counts selected detail URLs rather than individual HTTP requests. Robots and redirects add requests, and the listing request is separate. Counts describe this run; no corpus coverage or research-quality claim follows from them.

Argparse also exits 2 for invalid CLI syntax before a collection run starts. Distinguish that usage error from a recorded `partial` run by reading the error message and the run summary.

## Change and verify the adapter

Read the [writing guide](WRITING_GUIDE.md) and [contributor rules](../AGENTS.md). Add synthetic HTML for selector/date/sampling changes and mocked HTTP for request/error behavior. Keep raw snapshots distinct from selected manifest entries, keep all human-review flags, and update the [data contract](interface.md) with persisted field changes.

`tests/test_crawl.py` covers adapter rules, CLI, preparation, failure checkpoints and bounded collection. `tests/test_collectors.py` covers robots, redirects, gzip decoding, spacing, response limits, and email compatibility. `tests/test_io.py` checks preservation when manifest replacement fails. `tests/test_parsers.py` covers article/table behavior. Run the required suite, lint, formatting and offline demo from AGENTS.md; a live pilot is separate evidence recorded under [reports](../reports/README.md).
