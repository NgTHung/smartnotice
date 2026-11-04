# Collect notice sources

The collection manifest preserves how each notice entered the corpus so the team can explain its sources and reproduce preprocessing. Keep source bytes unchanged and document consent before importing participant email.

## Select sources

Use public faculty and academic-office notice pages with Vietnamese academic content. Record the actual page URL, institution, notice-body CSS selector, verified publication date, and any template/update group. Use only voluntarily supplied .eml files and keep consent records outside the repository. The corpus targets belong in the [course requirements](assignment.md).

The [root README](../README.md) owns collection and preparation commands. Run `uv run smartnotice collect-web --help` for options. The collector requests robots.txt before a page, checks redirected destinations, and separates requests by the configured interval or the site's larger Crawl-delay/Request-rate. It stops on HTTP errors, unavailable robots rules except 404, non-HTML responses, and responses above 5 MiB. It does not bypass authentication, retry denied requests, or discover links.

Use `--domain-holdout` for reserved web notices and `--group-id` for known templates or update families. Do not select reserved test data after looking at model errors. Review duplicate grouping before freezing split assignments.

## Review the manifest

Collectors write content-addressed files and `data/raw/manifest.jsonl`. Email references and automatic thread IDs are hashed before entering prepared records. Add `pii_names` privately to a manifest entry when known names need masking. Supply a web `reference_date` only after verifying it on the source page. A missing date remains missing.

Record institution and sampling decisions in the private collection log. The executable manifest fields are defined in the [data contract](interface.md). Do not add unreviewed scraped data to the synthetic example manifest.

## Inspect prepared text

Check that MIME decoding preserved Vietnamese characters, quoted replies and signatures were removed, and table header/value lines retained the action/date relationship. The parser falls back to HTML for blank plain-text alternatives, respects multipart/related roots, and excludes MIME attachments. It separates English/Vietnamese reply boundaries and HTML quotes while preserving the outer author's inline replies. Institution-specific forwarding and merged table headers still require review. Check `parser_warnings` when fallback codecs or replacement characters were used.

Automatic privacy filtering masks email addresses according to the selected policy, supplied/recognized student and staff names, student IDs, phone numbers, labeled birthdates, identity/account numbers, home addresses, and credentials. URL query filtering handles sensitive parameter names and private email values after URL decoding. URLs stay in both the text and `attachments`; no link is fetched. Academic dates, class codes, and BMP symbols remain available for annotation; the [data contract](interface.md#keep-offsets-stable) explains why emoji outside the BMP are removed. Every prepared document retains `privacy_review_required=true`; automated matching does not establish anonymity. Review body names, unlabeled IDs, URL paths/fragments, and free-form personal details before exporting tasks. Fix privacy defects in the source preparation settings and regenerate offsets before annotation.

## Review email retention

The private JSON configuration accepts `student_names`, `student_emails`, `student_ids`, `student_domains`, and `public_emails`, each an array of nonempty strings. Empty arrays add no rules; in particular, an empty `student_domains` array does not remove built-in student domains. Keep populated configurations in private storage. The root README owns the commands and links to an empty template.

The default `all` policy masks email addresses except explicit `public_emails`. A public exception takes precedence even if the same address appears in `student_emails`; review overlapping entries. `legacy` reproduces the supplied cleaner's address decisions, in this order:

| Decision | Reason code | Behavior |
|---|---|---|
| Explicit public contact | `explicit_public` | Retain |
| Explicit student/private address | `explicit_private` | Mask |
| Class/group local-part pattern | `group_local_part` | Retain, even on a personal/student domain |
| Built-in personal domain | `personal_domain` | Mask |
| Built-in/configured student domain | `student_domain` | Mask |
| Local part containing 7–12 consecutive digits | `numeric_local_part` | Mask |
| None of the private rules matched | `not_matched_private_rule` | Retain as a review candidate |

The exact patterns and domain sets live in [`privacy.py`](../src/preprocessing/privacy.py). The last rule permits unknown domains and individual institutional addresses; it does not establish that they are official contacts. Select the legacy policy explicitly and review its output before sharing.

The local audit scans headers and decoded bodies, including quotes but excluding MIME attachments. It deduplicates identical raw sources, counts documents containing each address, includes configured public contacts absent from the corpus with a zero count, and reports parser failures by source hash. CSV rows retain addresses, decision reasons, and `review_required=true`; keep the whole report private. The audit does not import email, grant consent, or add candidates to `public_emails` automatically.

The email-cleaning implementation is the work of the SmartNotice team.

MIME decoding, footer handling, and normalization are implemented in [`mime.py`](../src/parsers/mime.py), [`boilerplate.py`](../src/parsers/boilerplate.py), and [`text.py`](../src/preprocessing/text.py). Thread separation, URL handling, and privacy filtering are implemented in [`thread.py`](../src/parsers/thread.py), [`links.py`](../src/preprocessing/links.py), and [`privacy.py`](../src/preprocessing/privacy.py). Their regression tests use synthetic inputs in [`tests/`](../tests/). The [data contract](interface.md) defines source provenance, dates, document boundaries, and annotation offsets.

## Record evidence

For each collection run, retain the manifest, collection date, source selection method, consent record references, parser decisions, quality output, and split assignment file in controlled storage. Record failed sources and exclusion reasons in the collection log. Share reviewed aggregates and source descriptions rather than participant source files.
