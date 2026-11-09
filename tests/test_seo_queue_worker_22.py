"""Isolated worker orchestration tests without production DB imports."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

MANAGE = Path(__file__).resolve().parents[1] / 'manage.py'


def isolated_queue():
    source = ast.parse(MANAGE.read_text(encoding='utf-8'))
    fn = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'work_queue')
    code = compile(ast.Module(body=[fn], type_ignores=[]), str(MANAGE), 'exec')
    env = dict(wb=SimpleNamespace(touch_worker=Mock()), recover_stale_jobs=Mock(return_value=0),
               migrate_legacy_queue=Mock(return_value=0),
               process_seo_apply_jobs=Mock(return_value=2),
               work_queue_status=Mock(return_value={}), work_queue_pending_details=Mock(return_value=[]), json=json)
    exec(code, env)
    return env


class WorkQueueTests(unittest.TestCase):
    def test_only_queue_jobs_bounded(self):
        env=isolated_queue()
        env['work_queue']()
        env['process_seo_apply_jobs'].assert_called_once_with(limit_jobs=3)
        env['recover_stale_jobs'].assert_called_once()
        env['migrate_legacy_queue'].assert_called_once()
        self.assertEqual(env['wb'].touch_worker.call_args.args[:2], ('seo_queue','idle'))

    def test_exception_marks_worker_failed(self):
        env=isolated_queue()
        env['recover_stale_jobs'].side_effect = RuntimeError('db unavailable')
        with self.assertRaises(RuntimeError):env['work_queue']()
        self.assertEqual(env['wb'].touch_worker.call_args.args[:2], ('seo_queue','error'))
