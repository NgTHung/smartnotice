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

Check that MIME decoding preserved Vietnamese characters, quoted replies and signatures were removed, and table header/value lines retained the action/date relationship. Quote stripping handles common boundaries and `>` lines; institution-specific footers and inline forwarding require review. Tables with merged headers can need manual correction.

Automatic privacy filtering masks email addresses, labeled student IDs/phone numbers, and supplied names. Every prepared document retains `privacy_review_required=true`; automated matching does not establish anonymity. Review body names, unlabeled IDs, URLs, and free-form personal details before exporting tasks. Fix privacy defects in the source preparation settings and regenerate offsets before annotation.

## Record evidence

For each collection run, retain the manifest, collection date, source selection method, consent record references, parser decisions, quality output, and split assignment file in controlled storage. Record failed sources and exclusion reasons in the collection log. Share reviewed aggregates and source descriptions rather than participant source files.
