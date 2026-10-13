"""Release packaging must use the same locked runtime closure as CI."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "lambda_requirements", ROOT / "scripts/lambda_requirements.py"
)
requirements = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(requirements)


def test_export_requires_current_lock_and_includes_hashed_runtime_sdk(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="boto3==1.43.60 --hash=sha256:" + "a" * 64 + "\n")

    monkeypatch.setattr(requirements.subprocess, "run", run)
    output = requirements.exported_requirements(tmp_path)
    command, kwargs = calls[0]
    for flag in ("--locked", "--offline", "--no-dev", "--no-emit-local"):
        assert flag in command
    assert "--no-hashes" not in command
    assert "--prune" not in command and "--no-emit-package" not in command
    assert kwargs["cwd"] == tmp_path and kwargs["check"]
    assert kwargs["timeout"] == 60
    assert "boto3==1.43.60" in output and "--hash=sha256:" in output


def test_check_fails_for_stale_requirements_without_rewriting(monkeypatch, tmp_path):
    monkeypatch.setattr(requirements, "exported_requirements", lambda _: "sdk==2.0\n")
    path = tmp_path / "requirements-lambda.txt"
    path.write_text("sdk>=1\n")
    assert not requirements.update_requirements(tmp_path, check=True)
    assert path.read_text() == "sdk>=1\n"


def test_generation_and_check_agree(monkeypatch, tmp_path):
    monkeypatch.setattr(requirements, "exported_requirements", lambda _: "sdk==2.0\n")
    assert requirements.update_requirements(tmp_path, check=False)
    assert requirements.update_requirements(tmp_path, check=True)


def test_missing_file_fails_check_without_creating_it(monkeypatch, tmp_path):
    monkeypatch.setattr(requirements, "exported_requirements", lambda _: "sdk==2.0\n")
    assert not requirements.update_requirements(tmp_path, check=True)
    assert not (tmp_path / "requirements-lambda.txt").exists()


def test_both_bundle_commands_enforce_hashes():
    from fmaj.stacks.api_stack import BUNDLE_CMD as API_BUNDLE_CMD
    from fmaj.stacks.pipeline_stack import BUNDLE_CMD as PIPELINE_BUNDLE_CMD

    for command in (API_BUNDLE_CMD, PIPELINE_BUNDLE_CMD):
        assert "--require-hashes" in command
        assert "--only-binary=:all:" in command
        assert "--timeout 60 --retries 3" in command
