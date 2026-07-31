import importlib.util
import subprocess
import sys
import time
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "addon"
    / "synthDrivers"
    / "sonata_neural_voices"
    / "process_lifetime.py"
)


def load_process_lifetime_module():
    spec = importlib.util.spec_from_file_location(
        "sonata_process_lifetime_under_test",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_closing_job_terminates_child_process():
    process_lifetime = load_process_lifetime_module()
    process = subprocess.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    job_handle = None
    try:
        job_handle = process_lifetime.create_kill_on_close_job(process)
        time.sleep(0.1)
        assert process.poll() is None
        process_lifetime.close_job_handle(job_handle)
        job_handle = None
        process.wait(timeout=5)
        assert process.poll() is not None
    finally:
        if job_handle is not None:
            process_lifetime.close_job_handle(job_handle)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
