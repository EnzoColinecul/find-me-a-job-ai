"""Offline production-workflow regression checks (python3 + PyYAML + bash + jq).

Run: python3 scripts/test_deploy_prod_workflow.py
No GitHub dispatch, AWS credentials, or deployment commands are executed.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy-prod.yml"


class ProductionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # BaseLoader preserves the YAML key 'on' instead of treating it as bool.
        cls.workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
        cls.job = cls.workflow["jobs"]["deploy-prod"]
        cls.steps = cls.job["steps"]
        cls.confirm = cls.steps[0]
        cls.tested = cls.steps[1]

    def run_script(self, script, **environment):
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
            env={**os.environ, **environment},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_manual_trigger_and_credential_gate(self):
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(
            self.job["if"],
            "${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' }}",
        )
        self.assertEqual(self.workflow["permissions"]["id-token"], "write")
        credentials = next(
            i for i, step in enumerate(self.steps)
            if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
        )
        self.assertGreater(credentials, 3)
        for step in self.steps[:credentials + 1]:
            self.assertNotIn("continue-on-error", step)
        self.assertEqual(set(self.workflow["jobs"]), {"deploy-prod"})

    def test_confirmation_is_data_and_exact(self):
        self.assertEqual(self.confirm["env"]["CONFIRM"], "${{ github.event.inputs.confirm }}")
        for step in self.steps:
            self.assertNotIn("${{", step.get("run", ""))
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "injected"
            payloads = [
                "", "DEPLOY", " deploy", "deploy\n",
                f'deploy"; touch {marker}; #',
                f"$(touch {marker})", f"`touch {marker}`",
                f"deploy\ntouch {marker}",
            ]
            for value in payloads:
                with self.subTest(value=value):
                    result = self.run_script(self.confirm["run"], CONFIRM=value)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(marker.exists())
            self.assertEqual(self.run_script(self.confirm["run"], CONFIRM="deploy").returncode, 0)

    def test_tested_sha_is_main_push_and_must_pass(self):
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            gh = Path(directory) / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "expected = ['run', 'list', '--workflow', 'ci.yml', '--commit', "
                "os.environ['EXPECTED_SHA'], '--event', 'push', '--branch', 'main', "
                "'--json', 'headSha,conclusion']\n"
                "if sys.argv[1:] != expected: sys.exit(2)\n"
                "print(os.environ['MOCK_RUNS'])\n"
            )
            gh.chmod(0o755)
            for runs, allowed in [
                ([{"headSha": sha, "conclusion": "success"}], True),
                ([{"headSha": sha, "conclusion": "failure"}], False),
                ([{"headSha": "b" * 40, "conclusion": "success"}], False),
                ([], False),
            ]:
                with self.subTest(runs=runs):
                    result = self.run_script(
                        self.tested["run"], DEPLOY_REF=sha, EXPECTED_SHA=sha,
                        MOCK_RUNS=json.dumps(runs), PATH=f"{directory}:{os.environ['PATH']}",
                    )
                    self.assertEqual(result.returncode == 0, allowed)
            for ref in ["main", "refs/heads/main", "a" * 39, "a" * 41, "$(exit 0)"]:
                with self.subTest(ref=ref):
                    self.assertNotEqual(
                        self.run_script(self.tested["run"], DEPLOY_REF=ref).returncode, 0,
                    )

    def test_checkout_pinned_to_validated_sha(self):
        self.assertEqual(self.steps[2]["uses"], "actions/checkout@v4")
        self.assertEqual(self.steps[2]["with"]["ref"], "${{ github.event.inputs.ref }}")
        self.assertEqual(self.steps[3]["name"], "Verify checked-out commit")
        with tempfile.TemporaryDirectory() as directory:
            git = Path(directory) / "git"
            git.write_text('#!/bin/sh\n[ "$*" = "rev-parse HEAD" ] || exit 2\nprintf "%s\\n" "$MOCK_HEAD"\n')
            git.chmod(0o755)
            for head, allowed in [("a" * 40, True), ("b" * 40, False)]:
                result = self.run_script(
                    self.steps[3]["run"], TESTED_SHA="a" * 40, MOCK_HEAD=head,
                    PATH=f"{directory}:{os.environ['PATH']}",
                )
                self.assertEqual(result.returncode == 0, allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
