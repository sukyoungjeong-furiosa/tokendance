import os, sys, io, json, unittest, tempfile, fcntl
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import librarian as LIB
import harvest_knowledge as HK

UTC = timezone.utc


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


# ── should_run 게이트 (KST 시각 + idle + 하루 1회) ──────────────────────────
class ShouldRunTest(unittest.TestCase):
    def test_runs_at_target_hour_when_idle_and_not_run_today(self):
        # 2026-06-24 18:00Z = 2026-06-25 03:00 KST → target_hour=3, idle, last≠오늘 → 실행.
        now = _utc(2026, 6, 24, 18)
        self.assertTrue(LIB.should_run(now, idle=True, last_run_date="", target_hour=3))

    def test_not_idle_blocks(self):
        now = _utc(2026, 6, 24, 18)
        self.assertFalse(LIB.should_run(now, idle=False, last_run_date="", target_hour=3))

    def test_wrong_hour_blocks(self):
        now = _utc(2026, 6, 24, 17)   # 02:00 KST
        self.assertFalse(LIB.should_run(now, idle=True, last_run_date="", target_hour=3))

    def test_already_ran_today_blocks(self):
        now = _utc(2026, 6, 24, 18)   # KST date 2026-06-25
        self.assertFalse(LIB.should_run(now, idle=True,
                                        last_run_date="2026-06-25", target_hour=3))

    def test_ran_yesterday_allows(self):
        now = _utc(2026, 6, 24, 18)   # KST date 2026-06-25
        self.assertTrue(LIB.should_run(now, idle=True,
                                       last_run_date="2026-06-24", target_hour=3))

    def test_kst_date_uses_plus9_offset(self):
        # 2026-06-25 16:00Z = 2026-06-26 01:00 KST (날짜가 넘어감).
        self.assertEqual(LIB.kst_date(_utc(2026, 6, 25, 16)), "2026-06-26")
        self.assertEqual(LIB.kst_hour(_utc(2026, 6, 25, 16)), 1)


# ── last-run 상태 ───────────────────────────────────────────────────────────
class LastRunStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_is_empty(self):
        self.assertEqual(LIB.read_last_run(self.root), "")

    def test_mark_and_read_roundtrip(self):
        LIB.mark_run(self.root, _utc(2026, 6, 24, 18))   # KST 2026-06-25
        self.assertEqual(LIB.read_last_run(self.root), "2026-06-25")


# ── 스키마 하위호환 (tier 누락 = primary) ────────────────────────────────────
class TierCompatTest(unittest.TestCase):
    def test_missing_tier_is_primary(self):
        self.assertEqual(HK.entry_tier({"title": "x"}), HK.TIER_PRIMARY)
        self.assertFalse(HK.is_candidate({"title": "x"}))

    def test_candidate_detected(self):
        self.assertTrue(HK.is_candidate({"tier": "candidate"}))

    def test_unknown_tier_falls_back_to_primary(self):
        self.assertEqual(HK.entry_tier({"tier": "weird"}), HK.TIER_PRIMARY)


# ── 순수 변형: merge / polish / reclassify / candidate / promote ─────────────
class MergeTest(unittest.TestCase):
    def _entries(self):
        return {
            "playbook:a": {"title": "재시도 A", "scope": "playbook", "repo": None,
                           "slug": "재시도-a", "dest": "playbooks/재시도-a.md",
                           "anchor": None, "summary": "요약A", "tags": "retry, x",
                           "body": "본문 A", "tier": "primary", "sources": ["t1"]},
            "playbook:b": {"title": "재시도 B", "scope": "playbook", "repo": None,
                           "slug": "재시도-b", "dest": "playbooks/재시도-b.md",
                           "anchor": None, "summary": "", "tags": "retry, y",
                           "body": "본문 B", "tier": "primary", "sources": ["t2"]},
        }

    def test_merge_unions_sources_and_tags(self):
        e = self._entries()
        new_key = LIB.merge_entries(e, ["playbook:a", "playbook:b"], into_title="재시도 통합")
        self.assertNotIn("playbook:a", e)
        self.assertNotIn("playbook:b", e)
        self.assertIn(new_key, e)
        m = e[new_key]
        self.assertEqual(m["title"], "재시도 통합")
        self.assertEqual(sorted(m["sources"]), ["t1", "t2"])
        # 태그 union, 순서 보존, 중복 제거.
        self.assertEqual([t.strip() for t in m["tags"].split(",")], ["retry", "x", "y"])
        self.assertEqual(m["dest"], "playbooks/재시도-통합.md")

    def test_merge_keeps_first_nonempty_summary(self):
        e = self._entries()
        k = LIB.merge_entries(e, ["playbook:b", "playbook:a"])
        self.assertEqual(e[k]["summary"], "요약A")

    def test_merge_with_explicit_body(self):
        e = self._entries()
        k = LIB.merge_entries(e, ["playbook:a", "playbook:b"], body="새 통합 본문")
        self.assertEqual(e[k]["body"], "새 통합 본문")

    def test_merge_default_body_joins(self):
        e = self._entries()
        k = LIB.merge_entries(e, ["playbook:a", "playbook:b"])
        self.assertIn("본문 A", e[k]["body"])
        self.assertIn("본문 B", e[k]["body"])

    def test_merge_primary_wins_tier(self):
        e = self._entries()
        e["playbook:b"]["tier"] = "candidate"
        k = LIB.merge_entries(e, ["playbook:a", "playbook:b"])
        self.assertEqual(HK.entry_tier(e[k]), "primary")


class PolishReclassifyTest(unittest.TestCase):
    def _e(self):
        # ledger 불변식: 키는 항상 slug 와 일치(title='원제목' → 'playbook:원제목').
        return {"playbook:원제목": {"title": "원제목", "scope": "playbook", "repo": None,
                                   "slug": "원제목", "dest": "playbooks/원제목.md",
                                   "anchor": None, "summary": "", "tags": "",
                                   "body": "본문", "tier": "primary", "sources": ["t1"]}}

    def test_polish_summary_tags_body(self):
        e = self._e()
        LIB.polish_entry(e, "playbook:원제목", summary="새요약", tags="a, b", body="다듬은 본문")
        m = e["playbook:원제목"]
        self.assertEqual(m["summary"], "새요약")
        self.assertEqual(m["tags"], "a, b")
        self.assertEqual(m["body"], "다듬은 본문")

    def test_polish_title_rekeys(self):
        e = self._e()
        nk = LIB.polish_entry(e, "playbook:원제목", title="새 제목")
        self.assertNotIn("playbook:원제목", e)
        self.assertIn(nk, e)
        self.assertEqual(e[nk]["dest"], "playbooks/새-제목.md")

    def test_reclassify_playbook_to_repo(self):
        e = self._e()
        nk = LIB.reclassify_entry(e, "playbook:원제목", scope="repo", repo="alpha")
        self.assertNotIn("playbook:원제목", e)
        m = e[nk]
        self.assertEqual(m["scope"], "repo")
        self.assertEqual(m["repo"], "alpha")
        self.assertEqual(m["dest"], "repos/alpha.md")
        self.assertIsNotNone(m["anchor"])
        self.assertEqual(nk, "repo:alpha:원제목")


class CandidateTierTest(unittest.TestCase):
    def test_add_candidate_is_isolated_tier(self):
        e = {}
        k = LIB.add_candidate(e, "추정 지식", "코드에서 추정한 본문",
                              scope="repo", repo="alpha", summary="불확실", tags="guess")
        self.assertTrue(k.startswith("candidate:"))
        self.assertTrue(HK.is_candidate(e[k]))
        self.assertEqual(e[k]["summary"], "불확실")

    def test_candidate_key_does_not_collide_with_primary(self):
        e = {"repo:alpha:x": {"title": "x", "scope": "repo", "repo": "alpha",
                              "slug": "x", "dest": "repos/alpha.md", "anchor": "x",
                              "summary": "", "tags": "", "body": "1급",
                              "tier": "primary", "sources": []}}
        k = LIB.add_candidate(e, "x", "후보", scope="repo", repo="alpha")
        self.assertNotEqual(k, "repo:alpha:x")
        self.assertIn("repo:alpha:x", e)   # 기존 1급 보존

    def test_promote_candidate_to_primary(self):
        e = {}
        ck = LIB.add_candidate(e, "검증된 지식", "본문", scope="playbook")
        nk = LIB.promote_candidate(e, ck)
        self.assertNotIn(ck, e)
        self.assertFalse(HK.is_candidate(e[nk]))
        self.assertFalse(nk.startswith("candidate:"))

    def test_promote_collision_merges_sources(self):
        e = {"playbook:공통": {"title": "공통", "scope": "playbook", "repo": None,
                              "slug": "공통", "dest": "playbooks/공통.md", "anchor": None,
                              "summary": "", "tags": "", "body": "1급",
                              "tier": "primary", "sources": ["t1"]}}
        ck = LIB.add_candidate(e, "공통", "후보본문", scope="playbook", sources=["t2"])
        nk = LIB.promote_candidate(e, ck)
        self.assertEqual(nk, "playbook:공통")
        self.assertEqual(sorted(e[nk]["sources"]), ["t1", "t2"])
        self.assertNotIn(ck, e)

    def test_promote_non_candidate_raises(self):
        e = {"playbook:p": {"title": "p", "scope": "playbook", "repo": None,
                            "slug": "p", "tier": "primary", "sources": []}}
        with self.assertRaises(ValueError):
            LIB.promote_candidate(e, "playbook:p")


# ── Slack 보고 형식 ──────────────────────────────────────────────────────────
class ReportTest(unittest.TestCase):
    def test_report_format(self):
        self.assertEqual(LIB.format_report(2, 5, 1),
                         "정리: 병합 2 · 다듬음 5 · 후보 1(검토 요청)")


# ── flock 직렬화 ─────────────────────────────────────────────────────────────
class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_lock_is_exclusive(self):
        # ledger_lock 보유 중에는 같은 파일의 비차단 LOCK_EX 획득이 실패한다(상호배제).
        with HK.ledger_lock(self.root):
            other = open(HK._lock_path(self.root), "w")
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                other.close()

    def test_lock_released_after_block(self):
        with HK.ledger_lock(self.root):
            pass
        # 해제 후엔 재획득 가능.
        with HK.ledger_lock(self.root):
            pass


# ── CLI 통합 (flock + ledger 편집 + 재렌더, .md 직접수정 안 함) ──────────────
class CliIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "library"))

    def tearDown(self):
        self.tmp.cleanup()

    def _ledger(self):
        return HK.load_ledger(self.root)

    def _write_ledger(self, entries):
        HK.save_ledger(self.root, {"version": 1, "entries": entries})

    def _run(self, argv):
        with redirect_stdout(io.StringIO()):
            LIB.main(argv)

    def test_add_candidate_cli_renders_candidates_md_not_primary(self):
        self._run(["--root", self.root, "add-candidate", "--title", "후보 지식",
                  "--body", "코드에서 추정", "--scope", "playbook", "--summary", "불확실"])
        # candidates.md 에 나오고, playbooks/ 1급 파일은 안 생긴다.
        cand = os.path.join(self.root, "library", "candidates.md")
        self.assertTrue(os.path.exists(cand))
        with open(cand) as f:
            self.assertIn("후보 지식", f.read())
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "library", "playbooks", "후보-지식.md")))
        # index 의 candidates 섹션에 링크.
        with open(os.path.join(self.root, "library", "index.md")) as f:
            self.assertIn("candidates.md", f.read())

    def test_promote_cli_moves_to_primary_render(self):
        self._run(["--root", self.root, "add-candidate", "--title", "곧 승격",
                  "--body", "본문", "--scope", "playbook"])
        entries = self._ledger()["entries"]
        ck = [k for k in entries if k.startswith("candidate:")][0]
        self._run(["--root", self.root, "promote", ck])
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "library", "playbooks", "곧-승격.md")))

    def test_merge_cli(self):
        self._write_ledger({
            "playbook:a": {"title": "A", "scope": "playbook", "repo": None, "slug": "a",
                           "dest": "playbooks/a.md", "anchor": None, "summary": "sA",
                           "tags": "", "body": "BA", "tier": "primary", "sources": ["t1"]},
            "playbook:b": {"title": "B", "scope": "playbook", "repo": None, "slug": "b",
                           "dest": "playbooks/b.md", "anchor": None, "summary": "",
                           "tags": "", "body": "BB", "tier": "primary", "sources": ["t2"]},
        })
        self._run(["--root", self.root, "merge", "--into", "AB", "playbook:a", "playbook:b"])
        entries = self._ledger()["entries"]
        self.assertIn("playbook:ab", entries)
        self.assertNotIn("playbook:a", entries)


if __name__ == "__main__":
    unittest.main()
