"""Boban work visibility, time estimate and approval safety tests."""
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import execution_overview as ex

NOW = datetime(2026,11,14,15,0,tzinfo=ex.PRAGUE)


def job(i,status="queued",kind="seo_apply_action", **kw):
    return dict(id=i, status=status, job_type=kind, action_id=i,
                started_at=None, finished_at=None, run_after=None, **kw)


def historic(kind="seo_apply_action", seconds=35):
    start=NOW - timedelta(minutes=4)
    return {"job_type":kind,"started_at":start.isoformat(),
            "finished_at":(start+timedelta(seconds=seconds)).isoformat()}


class ExecutionOverviewTests(unittest.TestCase):
    def test_evidence_based_eta_only_when_cron_recent_and_samples_sufficient(self):
        history=[historic(seconds=x) for x in (20,45,60,50)]
        work=[job(3),job(4)]
        live={"status":"idle","healthy":False,"scheduler_confirmed":True}
        view=ex.overview(work,history,live,0,now=NOW)
        self.assertEqual(view["eta_confidence"],"estimated_from_history")
        self.assertGreaterEqual(view["eta"]["max_minutes"],view["eta"]["min_minutes"])
        self.assertGreaterEqual(view["eta"]["samples"],3)
        view2=ex.overview(work,history[:2],live,0,now=NOW)
        self.assertIsNone(view2["eta"])

    def test_missing_cron_never_promises_time(self):
        view=ex.overview([job(1)], [historic(seconds=35)]*4,
                         {"status":"idle","healthy":False,"scheduler_confirmed":False},
                         0,now=NOW)
        self.assertIsNone(view["eta"])
        self.assertEqual(view["eta_confidence"],"waiting_for_worker")

    def test_stale_running_job_never_gets_eta(self):
        view=ex.overview([job(2,status="running")], [historic()]*4,
                         {"status":"running","healthy":False,"scheduler_confirmed":False},
                         0,now=NOW)
        self.assertIn("nepotvrzeno",view["title"])
        self.assertIsNone(view["eta"])

    def test_real_job_reasons_and_approval_waiting(self):
        j=job(4,kind="seo_verify_action")
        j["action_reason"]="Ověřit title na cílové stránce"
        view=ex.overview([j],[],{},2,now=NOW)
        self.assertEqual(view["items"][0]["why"],"Ověřit title na cílové stránce")
        self.assertEqual(view["approvals"],2)
        waiting=ex.overview([],[],{},2,now=NOW)
        self.assertIn("schválení",waiting["title"])
        self.assertIsNone(waiting["eta"])

    def test_approval_inbox_cap(self):
        self.assertTrue(ex.can_prepare_more(0,0))
        self.assertTrue(ex.can_prepare_more(0,7))
        self.assertFalse(ex.can_prepare_more(1,0))
        self.assertFalse(ex.can_prepare_more(0,8))

    def test_untrusted_reason_safely_shortened(self):
        j=job(5);j["action_reason"]="<script>" + "A"*800
        result=ex.overview([j],[],{},0,now=NOW)
        self.assertLessEqual(len(result["items"][0]["why"]),220)

    def test_age_is_not_guessed_with_insufficient_history(self):
        hist=[historic("seo_ai_prepare",30)]*5
        view=ex.overview([job(12,kind="seo_apply_action")],hist,
                         {"status":"idle","scheduler_confirmed":True},0,now=NOW)
        self.assertIsNone(view["eta"])


class PlannerRegressions(unittest.TestCase):
    def test_ai_draft_generation_cannot_implicitly_publish(self):
        txt=(Path(__file__).resolve().parents[1]/"manage.py").read_text(encoding="utf-8")
        self.assertIn("auto_apply = False",txt)
        self.assertNotIn("if auto_apply and created:",txt)
        self.assertIn("locked_boban_cycle",txt)
        self.assertIn("can_prepare_more(preparing, drafts)",txt)


if __name__=="__main__":
    unittest.main()
