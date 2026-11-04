"""Private audit reports use synthetic sources and never certify publication."""

import csv
import json
from email.message import EmailMessage

import pytest
from smartnotice.cli import main
from smartnotice.collectors.local import collect_emails, discover_email_files
from smartnotice.preprocessing.privacy_audit import audit_email_policy


def test_audit_aggregates_unique_sources_and_records_rule_reasons(tmp_path, capsys):
    source = tmp_path / "mail"
    source.mkdir()
    mail = EmailMessage()
    mail["From"] = "Office <office@example.invalid>"
    mail["To"] = "learner@gmail.com"
    mail.set_content("Liên hệ office@example.invalid; 24c06@student.hcmus.edu.vn")
    (source / "one.eml").write_bytes(mail.as_bytes())
    (source / "copy.EML").write_bytes(mail.as_bytes())
    config = tmp_path / "privacy.json"
    config.write_text(json.dumps({"public_emails": ["explicit@gmail.com"]}), encoding="utf-8")
    output = tmp_path / "report"
    main(
        [
            "audit-email-policy",
            str(source),
            "--privacy-rules",
            str(config),
            "--output-dir",
            str(output),
        ]
    )
    console = capsys.readouterr().out
    summary = json.loads(console)
    assert summary["input_file_count"] == 2
    assert summary["unique_source_count"] == 1
    assert summary["allowed_candidate_count"] == 3
    assert "@" not in console and "one.eml" not in console
    with (output / "allowed_emails.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["email"]: row for row in csv.DictReader(handle)}
    assert "learner@gmail.com" not in rows
    assert rows["office@example.invalid"]["reason"] == "not_matched_private_rule"
    assert rows["office@example.invalid"]["source_count"] == "1"
    assert rows["explicit@gmail.com"]["source_count"] == "0"
    assert all(row["review_required"] == "True" for row in rows.values())


def test_batch_discovery_and_consent_import_preserve_sources(tmp_path):
    source = tmp_path / "mail"
    source.mkdir()
    raw = b"Content-Type: text/plain\n\nNotice"
    (source / "a.eml").write_bytes(raw)
    (source / "b.EML").write_bytes(raw)
    assert len(discover_email_files([source, source / "a.eml"])) == 2
    with pytest.raises(ValueError, match="consent"):
        collect_emails([source], tmp_path / "raw", "")
    assert not (tmp_path / "raw").exists()
    rows = collect_emails([source], tmp_path / "raw", "consent-synthetic")
    assert rows[0] == rows[1]
    assert (source / "a.eml").read_bytes() == raw
    assert (tmp_path / "raw" / rows[0]["path"]).read_bytes() == raw


def test_audit_does_not_overwrite_its_configuration(tmp_path):
    source = tmp_path / "one.eml"
    source.write_bytes(b"Content-Type: text/plain\n\nNotice")
    config = tmp_path / "audit_metadata.json"
    config.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="configuration"):
        audit_email_policy([source], tmp_path, privacy_rules=config)
    assert config.read_text(encoding="utf-8") == "{}"


def test_audit_extracts_addresses_inside_urls_without_path_or_query_prefixes(tmp_path):
    mail = EmailMessage()
    mail.set_content(
        "https://example.invalid/send/office%40example.invalid?to=contact%40example.invalid\n"
        "https://example.invalid/\n"
        "body@example.invalid"
    )
    source = tmp_path / "notice.eml"
    source.write_bytes(mail.as_bytes())
    output = tmp_path / "report"
    audit_email_policy([source], output)
    with (output / "allowed_emails.csv").open(encoding="utf-8-sig", newline="") as handle:
        addresses = {row["email"] for row in csv.DictReader(handle)}
    assert addresses == {
        "office@example.invalid",
        "contact@example.invalid",
        "body@example.invalid",
    }
