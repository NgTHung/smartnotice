"""Report legacy email retention decisions locally without granting public status."""

import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from importlib.metadata import version
from pathlib import Path
from platform import python_version

from smartnotice.collectors.local import discover_email_files
from smartnotice.parsers.addresses import find_email_addresses, normalize_email
from smartnotice.parsers.mime import extract_content
from smartnotice.preprocessing.links import extract_links
from smartnotice.preprocessing.privacy import load_privacy_rules
from smartnotice.preprocessing.urls import inspect_url


def _body_addresses(body: str) -> set[str]:
    text, links = extract_links(body)
    addresses = {email.address for email in find_email_addresses(text)}
    for link in links:
        addresses.update(inspect_url(link).addresses)
    return addresses


def audit_email_policy(
    inputs: list[Path], output_dir: Path, *, privacy_rules: Path | None = None
) -> dict:
    """Write private CSV decisions and a reproducible aggregate legacy-policy report.

    Scan headers and decoded bodies, including quotations but excluding MIME
    attachments. Deduplicate identical source bytes before counting documents.
    Never print addresses, names, bodies or filenames. The CSV is a candidate
    review list, not an approved allowlist. Return only aggregate metadata.
    """
    rules, config_hash = load_privacy_rules(privacy_rules, email_policy="legacy")
    files = discover_email_files(inputs)
    counts: Counter[str] = Counter()
    source_hashes: set[str] = set()
    failed_hashes: list[str] = []
    warning_counts: Counter[str] = Counter()
    for path in files:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in source_hashes:
            continue
        source_hashes.add(digest)
        mail = BytesParser(policy=policy.default).parsebytes(raw)
        addresses = set()
        for key in ("From", "To", "Cc", "Bcc", "Reply-To"):
            for header in mail.get_all(key, []):
                addresses.update(
                    normalize_email(address.addr_spec)
                    for address in getattr(header, "addresses", ())
                    if address.username and address.domain
                )
        warnings: list[str] = []
        try:
            body = extract_content(mail, warnings, include_email_quotes=True)
            addresses.update(_body_addresses(body))
        except (ValueError, LookupError, UnicodeError):
            failed_hashes.append(digest)
        warning_counts.update(set(warnings))
        counts.update(addresses)

    # Include explicit contacts absent from the corpus so the private config can be reviewed too.
    addresses = set(counts) | rules.public_emails
    allowed = []
    decisions: Counter[str] = Counter()
    for address in sorted(addresses):
        keep, reason = rules.email_decision(address)
        decisions[reason] += 1
        if keep:
            allowed.append(
                {
                    "email": address,
                    "reason": reason,
                    "source_count": counts[address],
                    "configured_public": address in rules.public_emails,
                    "review_required": True,
                }
            )
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": "legacy",
        "privacy_rules_sha256": config_hash,
        "policy_code_sha256": hashlib.sha256(
            Path(__file__).with_name("privacy.py").read_bytes()
        ).hexdigest(),
        "audit_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": python_version(),
        "beautifulsoup4_version": version("beautifulsoup4"),
        "extractor_code_sha256": {
            name: hashlib.sha256(
                (Path(__file__).resolve().parents[1] / name).read_bytes()
            ).hexdigest()
            for name in [
                "parsers/mime.py",
                "parsers/html.py",
                "parsers/thread.py",
                "parsers/addresses.py",
                "preprocessing/links.py",
                "preprocessing/urls.py",
                "preprocessing/text.py",
                "collectors/local.py",
            ]
        },
        "input_file_count": len(files),
        "unique_source_count": len(source_hashes),
        "duplicate_source_count": len(files) - len(source_hashes),
        "observed_unique_address_count": len(counts),
        "configured_public_count": len(rules.public_emails),
        "allowed_candidate_count": len(allowed),
        "decision_counts": dict(sorted(decisions.items())),
        "parser_warning_counts": dict(sorted(warning_counts.items())),
        "failed_body_count": len(failed_hashes),
        "failed_body_sha256": sorted(failed_hashes),
        "source_sha256": sorted(source_hashes),
        "review_required": True,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "allowed_emails.csv"
    metadata_path = output_dir / "audit_metadata.json"
    if privacy_rules and privacy_rules.resolve() in {csv_path.resolve(), metadata_path.resolve()}:
        raise ValueError("Audit outputs must not replace the privacy configuration")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "email",
                "reason",
                "source_count",
                "configured_public",
                "review_required",
            ],
        )
        writer.writeheader()
        writer.writerows(allowed)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        key: value
        for key, value in metadata.items()
        if key
        not in {
            "source_sha256",
            "failed_body_sha256",
        }
    }
