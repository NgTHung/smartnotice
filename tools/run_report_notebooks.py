"""Execute selected SmartNotice pipeline notebooks with the active Python kernel."""

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpec
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "notebook/bamibert pipeline test"


def rebase_links(notebook: nbformat.NotebookNode, source: Path, destination: Path) -> None:
    """Keep parent-relative Markdown links working in the executed copy."""
    for cell in notebook.cells:
        if cell.cell_type != "markdown":
            continue
        cell.source = re.sub(
            r"(?<=\]\()\.\./[^)]+",
            lambda match: Path(
                os.path.relpath((source / match[0]).resolve(), destination)
            ).as_posix(),
            cell.source,
        )


def main() -> None:
    """Write each executed notebook to the run directory and surface cell failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebooks", nargs="*", help="Notebook number prefixes, such as 01 05")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination == SOURCE.resolve() or destination.is_relative_to(SOURCE.resolve()):
        parser.error("Choose a separate directory for executed notebooks")
    destination.mkdir(parents=True, exist_ok=True)
    paths = sorted(SOURCE.glob("*.ipynb"))
    for prefix in args.notebooks:
        if not any(path.name.startswith(prefix + "-") for path in paths):
            parser.error(f"Unknown notebook number {prefix}")
    with tempfile.TemporaryDirectory(prefix="smartnotice-report-kernel-") as config:
        for path in paths:
            if args.notebooks and path.name.split("-", 1)[0] not in args.notebooks:
                continue
            notebook = nbformat.read(path, as_version=4)
            print(f"Running {path.name}", flush=True)
            manager = KernelManager(kernel_name="python3")
            manager._kernel_spec = KernelSpec(
                argv=[sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                display_name="SmartNotice experiments",
                language="python",
            )
            client = NotebookClient(
                notebook,
                km=manager,
                timeout=10800,
                resources={"metadata": {"path": str(ROOT)}},
                on_cell_executed=lambda cell_index, **_: print(
                    f"  Finished cell {cell_index + 1}", flush=True
                ),
            )
            try:
                client.execute(
                    env={
                        **os.environ,
                        "IPYTHONDIR": config,
                        "SMARTNOTICE_NOTEBOOK_OUTPUT": str(destination),
                        "TOKENIZERS_PARALLELISM": "false",
                        "PYTHONHASHSEED": "42",
                    }
                )
            finally:
                if manager.has_kernel:
                    manager.shutdown_kernel(now=True)
                rebase_links(notebook, path.parent, destination)
                nbformat.write(notebook, destination / path.name)
            print(f"Executed {path.name}", flush=True)


if __name__ == "__main__":
    main()
