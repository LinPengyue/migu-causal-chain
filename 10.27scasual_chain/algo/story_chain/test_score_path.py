"""比分轨迹与逆风翻盘弧的结构测试。"""

from __future__ import annotations

import unittest

from story_chain.comeback import build_comeback_story
from story_chain.end_to_end import ALGORITHM_ID, run
from story_chain.score_path import build_score_path, find_comeback_arc


def _event(event_id: str, t_sec: float, zh: str, score: str, *, replay: bool = False, shot: str = "") -> dict:
    attributes = {}
    if shot:
        attributes["Shot_Result"] = [shot]
    return {
        "event_id": event_id,
        "event_type_zh": zh,
        "event_type": zh,
        "bz_id": f"bz-{event_id}",
        "media_time": {"event_time_sec": t_sec},
        "video_context": {"is_replay": replay},
        "scores": {"score_recognition": score, "overall_score": 3, "criticality_score": 3},
        "attributes": attributes,
    }


def _hold(start_id: int, t0: float, zh: str, score: str, n: int = 3) -> list:
    return [_event(f"e{start_id+i}", t0 + i * 10, zh, score) for i in range(n)]


def _goal_chain(annotation_id: str, t_sec: float, events: list) -> dict:
    rows = []
    for order, (zh, offset) in enumerate(events):
        rows.append(
            {
                "event_id": f"{annotation_id}_{order}",
                "order": order,
                "type": zh,
                "type_en": zh,
                "t_ms": (t_sec + offset) * 1000,
                "bz_id": f"chain-{annotation_id}-{order}",
            }
        )
    return {
        "annotation_id": annotation_id,
        "chain_category": "结果链",
        "causal_chain_subtype": "其他",
        "is_replay": False,
        "events": rows,
    }


class ScorePathTests(unittest.TestCase):
    def test_flicker_does_not_invent_two_goal_jump(self) -> None:
        events = []
        for index in range(8):
            score = "2:0" if index % 2 else "0:0"
            events.append(_event(f"f{index}", 100 + index * 5, "传球", score))
        path = build_score_path(events)
        self.assertEqual([node.score for node in path], [(0, 0)])

    def test_plus_one_confirms(self) -> None:
        events = []
        events.extend(_hold(1, 10, "传球", "0:0"))
        events.extend(_hold(10, 200, "争顶成功", "0:1"))
        events.extend(_hold(20, 400, "射门", "1:1"))
        events.extend(_hold(30, 700, "控球", "2:1"))
        path = build_score_path(events)
        self.assertEqual([node.score for node in path], [(0, 0), (0, 1), (1, 1), (2, 1)])
        self.assertEqual([node.delta_side for node in path[1:]], ["right", "left", "left"])

    def test_comeback_arc_uses_last_deficit(self) -> None:
        events = []
        events.extend(_hold(1, 10, "传球", "0:0"))
        events.extend(_hold(10, 100, "传球", "0:1"))
        events.extend(_hold(20, 200, "传球", "1:1"))
        events.extend(_hold(30, 300, "传球", "1:2"))
        events.extend(_hold(40, 500, "传球", "2:2"))
        events.extend(_hold(50, 800, "传球", "3:2"))
        path = build_score_path(events)
        arc = find_comeback_arc(path)
        self.assertIsNotNone(arc)
        assert arc is not None
        self.assertEqual(arc["protagonist_side"], "left")
        self.assertEqual(arc["equalizer"].score, (2, 2))
        self.assertEqual(arc["go_ahead"].score, (3, 2))
        self.assertEqual(arc["spell"][-1].score, (1, 2))

    def test_story_events_follow_chain_order(self) -> None:
        events = []
        events.extend(_hold(1, 10, "传球", "0:0"))
        events.extend(_hold(10, 300, "争顶成功", "0:1"))
        events.append(_event("save", 420, "扑救", "0:1"))
        events.append(_event("miss", 450, "任意球", "0:1"))
        events.append(_event("miss2", 480, "射门", "0:1", shot="Shot_Wide"))
        events.extend(_hold(20, 600, "射门", "1:1"))
        events.extend(_hold(30, 900, "控球", "2:1"))
        events.append(_event("end", 1200, "比赛结束", "2:1"))
        chains = [
            _goal_chain("ann_concede", 280, [("射门", 0), ("进球", 5)]),
            {
                "annotation_id": "ann_save",
                "chain_category": "险情链",
                "causal_chain_subtype": "射门扑救链",
                "is_replay": False,
                "events": [
                    {
                        "event_id": "ann_save_0",
                        "order": 0,
                        "type": "射门",
                        "type_en": "shot",
                        "t_ms": 410000,
                        "bz_id": "s0",
                    },
                    {
                        "event_id": "ann_save_1",
                        "order": 1,
                        "type": "扑救",
                        "type_en": "keeper_save",
                        "t_ms": 418000,
                        "bz_id": "s1",
                    },
                ],
            },
            _goal_chain("ann_eq", 580, [("传球", 0), ("进球", 4)]),
            _goal_chain("ann_ahead", 880, [("助攻", 0), ("进球", 6)]),
        ]
        story = build_comeback_story(events, chains, match_meta={"match_id": "m1"})
        self.assertTrue(story["has_story"])
        self.assertEqual(story["causal_chain_subtype"], "逆风翻盘")
        self.assertEqual(story["protagonist_side"], "left")
        roles = [row["story_role"] for row in story["events"]]
        self.assertIn("铺垫", roles)
        self.assertIn("蓄力", roles)
        self.assertIn("转折", roles)
        self.assertIn("高潮", roles)
        self.assertIn("收尾", roles)
        self.assertLess(roles.index("转折"), roles.index("高潮"))
        self.assertEqual(roles[-1], "收尾")
        times = [row["t_ms"] for row in story["events"]]
        self.assertEqual(times, sorted(times))
        types = [row["type"] for row in story["events"]]
        self.assertLess(types.index("射门"), types.index("进球"))
        self.assertEqual(story["events"][-1]["type"], "比赛结束")
        orders = [row["order"] for row in story["events"]]
        self.assertEqual(orders, list(range(len(orders))))

    def test_chain_stops_at_first_goal_and_ignores_early_whistle(self) -> None:
        events = []
        events.extend(_hold(1, 10, "传球", "0:0"))
        events.extend(_hold(10, 200, "传球", "0:1"))
        events.append(_event("save", 280, "扑救", "0:1"))
        events.append(_event("att1", 340, "角球", "0:1"))
        events.append(_event("att2", 400, "射门", "0:1", shot="Hit_Frame"))
        events.extend(_hold(20, 500, "传球", "1:1"))
        events.extend(_hold(30, 800, "传球", "2:1"))
        events.append(_event("half", 600, "比赛结束", "1:1"))
        events.append(_event("full", 1100, "比赛结束", "2:1"))
        chains = [
            _goal_chain("ann_c", 180, [("射门", 0), ("进球", 2), ("射门", 4), ("进球", 6)]),
            _goal_chain("ann_e", 480, [("进球", 0)]),
            _goal_chain("ann_a", 780, [("进球", 0)]),
        ]
        story = build_comeback_story(events, chains, match_meta={"match_id": "m2"})
        concede = [row for row in story["events"] if row["source_annotation_id"] == "ann_c"]
        self.assertEqual([row["type"] for row in concede], ["射门", "进球"])
        self.assertEqual(story["events"][-1]["event_id"], "full")
        self.assertEqual(story["events"][-1]["story_role"], "收尾")

    def test_score_flip_without_timeline_beats_is_candidate(self) -> None:
        events = []
        events.extend(_hold(1, 10, "传球", "0:0"))
        events.extend(_hold(10, 200, "界外球", "0:1"))
        events.extend(_hold(20, 500, "界外球", "1:1"))
        events.extend(_hold(30, 800, "界外球", "2:1"))
        story = build_comeback_story(events, [], match_meta={"match_id": "bare"})
        self.assertFalse(story["has_story"])
        self.assertTrue(story["is_candidate"])
        self.assertEqual(story["story_tier"], "candidate")
        self.assertEqual(story["story_label_zh"], "逆风翻盘候选")
        self.assertFalse(story["recognition"]["present"])
        self.assertTrue(story["recognition"]["is_candidate"])
        self.assertEqual(story["no_story_reason"], "missing_buildup")
        roles = [row["story_role"] for row in story["events"]]
        self.assertIn("转折", roles)
        self.assertIn("高潮", roles)

    def test_end_to_end_emits_candidate_when_beats_incomplete(self) -> None:
        events = []
        events.extend(_hold(1, 10, "传球", "0:0"))
        events.extend(_hold(10, 200, "界外球", "0:1"))
        events.extend(_hold(20, 500, "界外球", "1:1"))
        events.extend(_hold(30, 800, "界外球", "2:1"))
        story = run({"match_id": "bare", "events": events}, {"causal_chains": [_goal_chain("ann", 190, [("进球", 0)])]})
        self.assertEqual(story["algorithm"], ALGORITHM_ID)
        self.assertEqual(story["stages"], ["recognize_timeline", "emit_candidate_chain"])
        self.assertTrue(story["is_candidate"])
        self.assertGreater(len(story["events"]), 0)

    def test_opening_deficit_carrier_is_setup_not_skipped(self) -> None:
        """开场即 0:1 时 opening 失球 carrier 必须进入铺垫，不得再标 missing_setup。"""
        events = []
        events.extend(_hold(1, 10, "界外球", "0:1"))
        events.extend(_hold(10, 200, "界外球", "1:1"))
        events.extend(_hold(20, 500, "界外球", "2:1"))
        events.extend(_hold(30, 800, "界外球", "3:1"))
        story = build_comeback_story(events, [], match_meta={"match_id": "croatia_like"})
        self.assertFalse(story["has_story"])
        self.assertTrue(story["is_candidate"])
        # 有 opening carrier 后缺的是蓄力，不再是 missing_setup
        self.assertEqual(story["no_story_reason"], "missing_buildup")
        self.assertTrue(story["recognition"]["beats"].get("铺垫"))

    def test_opening_deficit_matches_causal_goal_with_long_board_lag(self) -> None:
        """记分牌滞后 ~99s 仍应匹配对手开场进球因果链（铺垫必须含进球动作）。"""
        events = []
        # 无 0:0；开场记分牌直接 0:1（对齐克罗地亚），carrier 为界外球非进球
        events.extend(_hold(1, 1079, "界外球", "0:1"))
        events.append(_event("att1", 2000, "角球", "0:1"))
        events.append(_event("att2", 2500, "射门", "0:1", shot="Shot_Wide"))
        events.extend(_hold(10, 3145, "界外球", "1:1"))
        events.extend(_hold(20, 3697, "界外球", "2:1"))
        events.append(_event("end", 7940, "比赛结束", "2:1"))
        chains = [
            _goal_chain("ann_opener", 980.0, [("传球", -2.0), ("传球", -1.0), ("进球", 0.0)]),
            _goal_chain("ann_eq", 3065.0, [("进球", 0.0)]),
            _goal_chain("ann_ahead", 3525.0, [("进球", 0.0)]),
        ]
        story = build_comeback_story(events, chains, match_meta={"match_id": "croatia_opener"})
        setup_goals = [
            row
            for row in story["events"]
            if row.get("story_role") == "铺垫" and row.get("type") == "进球"
        ]
        self.assertTrue(setup_goals, msg="opening deficit must emit opponent goal into 铺垫")
        self.assertAlmostEqual(setup_goals[0]["t_ms"] / 1000.0, 980.0, places=1)
        self.assertEqual(setup_goals[0].get("source_annotation_id"), "ann_opener")


if __name__ == "__main__":
    unittest.main()
