"""Execute the BamiBERT notebook with the active uv interpreter."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpec
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebook/bamibert pipeline test/legacy/01_bamibert_development.ipynb"


def main() -> None:
    """Save the executed notebook and aggregate metrics under the selected run directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--resume-extraction", type=Path, help="Run directory with extraction.pt")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Use a fresh run directory")
    output.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "SMARTNOTICE_SPLIT_ROOT": str(args.split.resolve()),
        "SMARTNOTICE_RUN_DIR": str(output),
        "TOKENIZERS_PARALLELISM": "false",
    }
    if args.checkpoint:
        env["SMARTNOTICE_BAMIBERT_DIR"] = str(args.checkpoint.resolve())
    if args.resume_extraction:
        env["SMARTNOTICE_RESUME_EXTRACTION"] = str(args.resume_extraction.resolve())
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    manager = KernelManager(kernel_name="python3")
    manager._kernel_spec = KernelSpec(
        argv=[sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        display_name="SmartNotice uv",
        language="python",
    )

    def on_executed(cell, cell_index, **_):
        print(f"Executed cell {cell_index + 1} ({cell.id})", flush=True)

    client = NotebookClient(
        notebook,
        km=manager,
        timeout=7200,
        resources={"metadata": {"path": str(ROOT)}},
        on_cell_executed=on_executed,
    )
    with tempfile.TemporaryDirectory(prefix="smartnotice-bamibert-kernel-") as config:
        try:
            client.execute(env={**env, "IPYTHONDIR": config})
        finally:
            if manager.has_kernel:
                manager.shutdown_kernel(now=True)
            nbformat.write(notebook, output / NOTEBOOK.name)


if __name__ == "__main__":
    main()
