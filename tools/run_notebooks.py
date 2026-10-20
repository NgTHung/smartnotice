"""Execute the analysis notebooks using the active uv Python interpreter."""

import os
import sys
import tempfile
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpec
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Save executed copies under reports, leaving source notebooks output-free."""
    destination = ROOT / "reports/generated/demo/notebooks"
    destination.mkdir(parents=True, exist_ok=True)
    # The working interpreter owns the kernel, regardless of globally installed kernels.
    with tempfile.TemporaryDirectory(prefix="smartnotice-kernel-") as directory:
        for path in sorted((ROOT / "notebooks").glob("*.ipynb")):
            notebook = nbformat.read(path, as_version=4)
            manager = KernelManager(kernel_name="python3")
            manager._kernel_spec = KernelSpec(
                argv=[sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                display_name="SmartNotice uv",
                language="python",
            )
            client = NotebookClient(
                notebook, km=manager, timeout=180, resources={"metadata": {"path": str(ROOT)}}
            )
            try:
                client.execute(env={**os.environ, "IPYTHONDIR": directory, "MPLBACKEND": "Agg"})
            finally:
                if manager.has_kernel:
                    manager.shutdown_kernel(now=True)
            nbformat.write(notebook, destination / path.name)
            print(f"Executed {path.name}")


if __name__ == "__main__":
    main()
