"""Generate review tasks and retain explicit failures for a selected corpus."""

from datetime import UTC, datetime

import httpx
from smartnotice.labeling.llm import parse_proposal, require_provider_approval
from smartnotice.labeling.providers import generate_draft
from smartnotice.labeling.studio import export_prediction_task
from smartnotice.schemas import LabelingFailure, Notice, Provider


def suggest_tasks(
    notices: list[Notice],
    *,
    provider: Provider,
    model: str,
    approvals: list[dict],
    client: httpx.Client | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return valid review tasks and safe failure rows from sequential requests.

    Check all document approvals before the first request. Each failed notice
    stays in the failure ledger; successful notices retain their source hashes.
    No request is automatically retried, so callers control repeated API usage.
    """
    if not notices or len({n.doc_id for n in notices}) != len(notices):
        raise ValueError("Select at least one notice with unique document IDs")
    for notice in notices:
        require_provider_approval(notice, provider, approvals)
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=90)
    tasks, failures = [], []
    try:
        for notice in notices:
            try:
                content = generate_draft(
                    notice, provider=provider, model=model, approvals=approvals, client=client
                )
                proposal = parse_proposal(notice, content)
                tasks.append(
                    export_prediction_task(notice, proposal, provider=provider, model=model)
                )
            except ValueError as exc:
                failures.append(
                    LabelingFailure(
                        doc_id=notice.doc_id,
                        provider=provider,
                        model=model,
                        failed_at=datetime.now(UTC),
                        reason=str(exc),
                    ).model_dump(mode="json")
                )
    finally:
        if own_client:
            client.close()
    return tasks, failures
