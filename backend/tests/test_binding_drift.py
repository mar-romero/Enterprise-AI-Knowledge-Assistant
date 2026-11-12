"""Binding-drift acceptance tests for validate_provider_active.

The OpenCode runtime re-serializes model-selections.json payload-identically
when agent model state updates, so a byte-hash mismatch alone must not reject
an otherwise intact binding; a selections-content mutation must still fail on
either the guarded integrity check (T2) or the semantic tamper line (T3).

These tests are placed under the backend project so the deterministic
check-runner exercises them within its per-project timeout model; a repo-root
tests/ placement resolves the check-runner project root to the repository root
whose full suite (~9-10 min) exceeds the runner's hardcoded 60s per-command cap
with no override knob.
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import harnesslib


TASK_ID = 'BINDING-DRIFT-001'
OVERLAY = '.harness/overlays/FIXTURE-ID/opencode/model-selections.json'


def _selection_payload() -> dict:
    return {
        'schema_version': 2,
        'task_id': TASK_ID,
        'provider': 'opencode',
        'inventory_path': None,
        'inventory_sha256': None,
        'selections': [{
            'agent': 'implementer',
            'status': 'selected',
            'action': 'use',
            'model_id': 'vendor/impl',
            'base_model_id': 'vendor/impl',
            'model_family': 'impl-family',
            'model_vendor': 'vendor',
        }],
    }


class ValidateProviderActiveBindingDriftTest(unittest.TestCase):
    """validate_provider_active tolerates payload-identical re-serialization."""

    def _install(self):
        temp = tempfile.TemporaryDirectory(prefix='binding-drift-')
        self.addCleanup(temp.cleanup)
        temp_root = Path(temp.name).resolve()

        for patcher in (
            mock.patch.object(
                harnesslib, '_worktree_metadata',
                lambda root=None: (temp_root, temp_root)),
            mock.patch.object(
                harnesslib, 'worktree_identity',
                lambda root=None: {
                    'schema_version': harnesslib._OVERLAY_SCHEMA,
                    'worktree_id': 'FIXTURE-ID'}),
            mock.patch.object(
                harnesslib, 'run_dir',
                lambda task: temp_root / '.harness' / 'runs' / task),
            mock.patch.object(
                harnesslib, 'runtime_reference',
                lambda value: temp_root / '.harness' / 'runs' / TASK_ID
                / Path(value).name),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        selections_path = harnesslib.provider_model_selections_path('opencode')
        self.assertEqual(
            selections_path, temp_root / OVERLAY,
            'overlay fixture path must resolve through provider_overlay_dir')

        payload = _selection_payload()
        self._write_selections(selections_path, json.dumps(payload))

        run_dir = harnesslib.run_dir(TASK_ID)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / 'task.json').write_text(
            json.dumps({'id': TASK_ID}), encoding='utf-8')

        active = {
            'schema_version': 3,
            'provider': 'opencode',
            'overlay': {
                'schema_version': harnesslib._OVERLAY_SCHEMA,
                'worktree_id': 'FIXTURE-ID',
            },
            'task_id': TASK_ID,
            'task_path': f'tasks/{TASK_ID}.json',
            'route_path': 'route.json',
            'context_path': 'context.json',
            'progress_path': 'progress.json',
            'task_snapshot_path': 'task.json',
            'impact_path': 'impact.json',
            'agent_budget_path': 'agent-budget.json',
            'model_selections_path': OVERLAY,
            'model_selections_sha256': harnesslib.sha256_file(selections_path),
            'selections': payload['selections'],
        }
        return temp_root, selections_path, payload, active

    @staticmethod
    def _write_selections(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_t0_baseline_valid_binding_passes(self):
        """T0 (control): an intact binding validates and is returned as-is."""
        _, _, _, active = self._install()
        self.assertEqual(
            harnesslib.validate_provider_active('opencode', active, None),
            active)

    def test_t1_payload_identical_re_serialization_is_accepted(self):
        """T1 (fail-to-pass): byte drift with identical selections passes."""
        _, selections_path, payload, active = self._install()
        self._write_selections(
            selections_path, json.dumps(payload, separators=(',', ':')))
        self.assertNotEqual(
            harnesslib.sha256_file(selections_path),
            active['model_selections_sha256'])
        self.assertEqual(
            harnesslib.validate_provider_active('opencode', active, None),
            active)

    def test_t2_mutated_selections_with_re_serialization_is_rejected(self):
        """T2 (negative): content mutation plus re-serialization is rejected."""
        _, selections_path, payload, active = self._install()
        mutated = copy.deepcopy(payload)
        mutated['selections'][0]['model_id'] = 'other/impl'
        self._write_selections(
            selections_path, json.dumps(mutated, separators=(',', ':')))
        self.assertNotEqual(
            harnesslib.sha256_file(selections_path),
            active['model_selections_sha256'])
        with self.assertRaisesRegex(
                ValueError, 'model selections integrity mismatch'):
            harnesslib.validate_provider_active('opencode', active, None)

    def test_t3_mutated_stored_selections_with_matching_bytes_is_rejected(self):
        """T3 (negative characterization): the semantic line still fires when
        the byte hash matches again but the stored binding was mutated."""
        _, selections_path, payload, active = self._install()
        mutated = copy.deepcopy(payload)
        mutated['selections'][0]['model_id'] = 'other/impl'
        active['selections'] = mutated['selections']
        # Restore the original file bytes so the byte hash matches the binding.
        self._write_selections(selections_path, json.dumps(payload))
        self.assertEqual(
            harnesslib.sha256_file(selections_path),
            active['model_selections_sha256'])
        with self.assertRaisesRegex(
                ValueError, 'provider active binding selections mismatch'):
            harnesslib.validate_provider_active('opencode', active, None)


class ExtraRuntimeAgentTest(unittest.TestCase):
    """Cross-task runtime entries in model-selections.json are tolerated."""

    def _install(self):
        temp = tempfile.TemporaryDirectory(prefix='binding-extra-')
        self.addCleanup(temp.cleanup)
        temp_root = Path(temp.name).resolve()

        for patcher in (
            mock.patch.object(
                harnesslib, '_worktree_metadata',
                lambda root=None: (temp_root, temp_root)),
            mock.patch.object(
                harnesslib, 'worktree_identity',
                lambda root=None: {
                    'schema_version': harnesslib._OVERLAY_SCHEMA,
                    'worktree_id': 'FIXTURE-ID'}),
            mock.patch.object(
                harnesslib, 'run_dir',
                lambda task: temp_root / '.harness' / 'runs' / task),
            mock.patch.object(
                harnesslib, 'runtime_reference',
                lambda value: temp_root / '.harness' / 'runs' / TASK_ID
                / Path(value).name),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        selections_path = harnesslib.provider_model_selections_path('opencode')
        payload = _selection_payload()
        self._write_selections(selections_path, json.dumps(payload))

        run_dir = harnesslib.run_dir(TASK_ID)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / 'task.json').write_text(
            json.dumps({'id': TASK_ID}), encoding='utf-8')

        active = {
            'schema_version': 3,
            'provider': 'opencode',
            'overlay': {
                'schema_version': harnesslib._OVERLAY_SCHEMA,
                'worktree_id': 'FIXTURE-ID',
            },
            'task_id': TASK_ID,
            'task_path': f'tasks/{TASK_ID}.json',
            'route_path': 'route.json',
            'context_path': 'context.json',
            'progress_path': 'progress.json',
            'task_snapshot_path': 'task.json',
            'impact_path': 'impact.json',
            'agent_budget_path': 'agent-budget.json',
            'model_selections_path': OVERLAY,
            'model_selections_sha256': harnesslib.sha256_file(selections_path),
            'selections': payload['selections'],
        }
        return selections_path, payload, active

    @staticmethod
    def _write_selections(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_t4_extra_runtime_agent_entry_is_accepted(self):
        """T4 (fail-to-pass): a runtime-persisted extra agent entry does not
        raise; the byte hash drifts but every bound agent is intact."""
        selections_path, payload, active = self._install()
        extra = {
            'task_id': 'MVP-EVAL-001',
            'provider': 'opencode',
            'agent': 'verifier',
            'model_class': 'reasoning',
            'risk': 'R1',
            'model_id': 'other/verifier',
            'base_model_id': 'other/verifier',
            'status': 'selected',
            'action': 'use',
        }
        extra_payload = dict(payload, selections=payload['selections'] + [extra])
        # Re-serialize compactly so the file bytes differ from the binding.
        self._write_selections(
            selections_path, json.dumps(extra_payload, separators=(',', ':')))
        self.assertNotEqual(
            harnesslib.sha256_file(selections_path),
            active['model_selections_sha256'])
        self.assertEqual(
            harnesslib.validate_provider_active('opencode', active, None),
            active)

    def test_t5_extra_agent_does_not_mask_bound_agent_tampering(self):
        """T5 (negative): an extra runtime entry must not mask a mutation of
        a bound agent's selections; the integrity guard still fires."""
        selections_path, payload, active = self._install()
        extra = {
            'task_id': 'MVP-EVAL-001',
            'provider': 'opencode',
            'agent': 'verifier',
            'model_class': 'reasoning',
            'risk': 'R1',
            'model_id': 'other/verifier',
            'base_model_id': 'other/verifier',
            'status': 'selected',
            'action': 'use',
        }
        mutated = copy.deepcopy(payload['selections'][0])
        mutated['model_id'] = 'other/impl'
        mixed_payload = dict(payload, selections=[mutated, extra])
        self._write_selections(
            selections_path, json.dumps(mixed_payload, separators=(',', ':')))
        with self.assertRaisesRegex(
                ValueError, 'model selections integrity mismatch'):
            harnesslib.validate_provider_active('opencode', active, None)


if __name__ == '__main__':
    unittest.main()
