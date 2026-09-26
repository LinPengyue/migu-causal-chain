#!/usr/bin/env python3
"""从交付_out 构建拆条/集锦测试集（63 场；剔回放、空类别）。

输出仅写入 9.31causal_chain/datasets/，不修改仓库其他目录。
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]  # 9.31causal_chain
REPO = ROOT.parent
# 优先本包 data/（可独立上传服务器）；否则回退仓库交付_out
_SRC_LOCAL = ROOT / "data" / "交付_out"
_SRC_REPO = REPO / "causal_chain" / "examples" / "交付_out"
SRC = _SRC_LOCAL if _SRC_LOCAL.is_dir() else _SRC_REPO
OUT = ROOT / "datasets"
ALGO = ROOT / "algo"

# 供 select_moments 与 build_highlights 同源选片
import sys

if str(ALGO) not in sys.path:
    sys.path.insert(0, str(ALGO))

HALF_MS = 45 * 60 * 1000
SLOT_MS = 15 * 60 * 1000
MERGE_GAP_MS = 2000
NEAR_DUP_MS = 5000

# 与 causal_chain8.select_moments.WINDOW_MS 对齐（集锦 gold 短窗）
HL_WINDOW_MS = {
    "T0": (12_000, 4_000),
    "T1": (8_000, 5_000),
    "T2": (6_000, 4_000),
}

CAT_ZH_TO_EN = {
    "结果链": "outcome",
    "修正链": "correction",
    "险情链": "danger",
    "特殊链": "special",
}

# 交付 type_en / 中文 → 评测归一化 type
TYPE_NORM = {
    "shot": "shot",
    "goal": "goal",
    "header_goal": "goal",
    "save": "keeper_save",
    "keeper_save": "keeper_save",
    "pass": "pass",
    "assist": "assist",
    "corner_kick": "corner",
    "corner": "corner",
    "free_kick": "free_kick",
    "penalty_": "penalty",
    "penalty": "penalty",
    "throw_in": "throw_in",
    "dribble_past": "dribble_past",
    "dribble_breakthrough": "dribble_breakthrough",
    "ball_possession": "pass",
    "goal_line_clearance": "goal_line_clearance",
    "win_an_aerial_duel": "aerial_won",
    "defensive_action": "successful_tackle",
    "successful_tackle": "successful_tackle",
    "interception": "interception",
    "video_assistant_referee": "var",
    "var": "var",
    "foul_being_fouled": "foul",
    "foul": "foul",
    "red_card": "red_card",
    "second_yellow_red": "second_yellow_red",
    "yellow_card": "yellow_card",
    "substitution": "substitution",
    "referees_decision": "controversy",
    "referee_decision": "controversy",
    "possession_lost": "possession_lost",
    "cross": "cross",
    "header_shot": "header_shot",
    "players_enter_the_pitch": "player_entrance",
    "kick_off": "match_start",
    "aerial_won": "aerial_won",
    # 中文
    "射门": "shot",
    "进球": "goal",
    "头球进球": "goal",
    "扑救": "keeper_save",
    "传球": "pass",
    "助攻": "assist",
    "角球": "corner",
    "任意球": "free_kick",
    "点球": "penalty",
    "界外球": "throw_in",
    "过人": "dribble_past",
    "盘带突破": "dribble_breakthrough",
    "控球": "pass",
    "门线救险": "goal_line_clearance",
    "争顶成功": "aerial_won",
    "头球": "header_shot",
    "防守动作": "successful_tackle",
    "抢断成功": "successful_tackle",
    "拦截": "interception",
    "犯规/被犯规": "foul",
    "红牌": "red_card",
    "两黄变一红": "second_yellow_red",
    "黄牌": "yellow_card",
    "队员入场": "player_entrance",
    "开球": "match_start",
    "裁判判罚": "controversy",
}


def norm_type(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    key = s.lower().replace(" ", "_")
    if key in TYPE_NORM:
        return TYPE_NORM[key]
    if s in TYPE_NORM:
        return TYPE_NORM[s]
    return key


def parse_segment_time_video(s: str) -> Optional[Tuple[int, int]]:
    """'8:37-8:46' or '12：54-13:04' → (t0_ms, t1_ms)."""
    if not s or not str(s).strip():
        return None
    text = str(s).strip().replace("：", ":")
    m = re.match(r"^\s*(\d+):(\d+)\s*-\s*(\d+):(\d+)\s*$", text)
    if not m:
        return None
    a = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
    b = (int(m.group(3)) * 60 + int(m.group(4))) * 1000
    if b < a:
        a, b = b, a
    return a, b


def chain_time_span(
    ch: Dict[str, Any],
    *,
    pad_ms: int = 2_000,
    max_span_ms: int = 90_000,
) -> Tuple[int, int]:
    """因果链评测时间窗：只用事件 t_ms 的 min/max。

    不再与 segment_time_video 取并集（比赛分钟钟点常与 t_ms 错位，会拉成数十分钟假长窗，
    导致集锦短窗几乎无法严格配对）。
    """
    times = []
    for e in ch.get("events") or []:
        if e.get("t_ms") is not None:
            times.append(int(float(e["t_ms"])))
    if not times:
        # 无事件时才回退 segment（极少见）
        seg = parse_segment_time_video(ch.get("segment_time_video") or "")
        if seg:
            return seg
        return 0, 0

    t0, t1 = min(times), max(times)
    if t1 < t0:
        t0, t1 = t1, t0
    # 极短链略扩边，便于与 PDF 短窗相交
    if t1 - t0 < 1_000:
        t0 = max(0, t0 - pad_ms)
        t1 = t1 + pad_ms
    else:
        t0 = max(0, t0 - pad_ms)
        t1 = t1 + pad_ms
    # 防御：异常超长（脏数据）按锚点截断
    if t1 - t0 > max_span_ms:
        # 优先终局事件
        anchor = t1 - pad_ms
        for e in ch.get("events") or []:
            typ = norm_type(e.get("type_en") or e.get("type"))
            if typ in ("goal", "header_goal", "penalty", "red_card", "second_yellow_red", "keeper_save", "shot"):
                if e.get("t_ms") is not None:
                    anchor = int(float(e["t_ms"]))
        # 与 build_highlights T0/T1 短窗量级对齐
        t0 = max(0, anchor - 12_000)
        t1 = anchor + 5_000
    return t0, t1


def normalize_chain_events(ch: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for i, e in enumerate(ch.get("events") or []):
        t_ms = e.get("t_ms")
        if t_ms is None:
            t_ms = 0
        typ = norm_type(e.get("type_en") or e.get("type"))
        out.append(
            {
                "order": int(e.get("order", i)),
                "type": typ,
                "type_raw": e.get("type_en") or e.get("type") or "",
                "t_ms": int(float(t_ms)),
                "event_id": e.get("event_id") or f"e{i:04d}",
            }
        )
    out.sort(key=lambda x: (x["t_ms"], x["order"]))
    return out


def full_events_to_timeline(full: Dict[str, Any]) -> List[Dict[str, Any]]:
    """完整场次 events → 算法可用 timeline 事件列表。"""
    out: List[Dict[str, Any]] = []
    for i, e in enumerate(full.get("events") or []):
        media = e.get("media_time") or {}
        t_sec = media.get("event_time_sec")
        if t_sec is None:
            t_sec = media.get("start_time_sec")
        if t_sec is None:
            continue
        typ = norm_type(e.get("event_type") or e.get("event_type_zh") or e.get("comment_label"))
        if not typ:
            continue
        t_ms = int(float(t_sec) * 1000)
        t0 = media.get("start_time_sec")
        t1 = media.get("end_time_sec")
        out.append(
            {
                "event_id": e.get("event_id") or f"e{i:04d}",
                "type": typ,
                "t_ms": t_ms,
                "t0_ms": int(float(t0) * 1000) if t0 is not None else t_ms,
                "t1_ms": int(float(t1) * 1000) if t1 is not None else t_ms,
                "order": i,
            }
        )
    out.sort(key=lambda x: x["t_ms"])
    return out


def tag_chain_tier(events: Sequence[Dict[str, Any]], subtype: str) -> Tuple[str, str]:
    """返回 (tier, reason)。基于链内事件 + subtype。"""
    types = [e["type"] for e in events]
    sub = subtype or ""
    if any(t in ("goal",) for t in types) or "进球" in sub or sub in (
        "点球命中链",
        "角球传中进球链",
        "抢断/反击/失误后直接进球链",
        "射门被扑后补射进球链",
    ):
        if "点球" in sub or "penalty" in types:
            return "T0", "t0_penalty_goal"
        if any(t in ("red_card", "second_yellow_red") for t in types) or "红牌" in sub:
            return "T0", "t0_red"
        if "goal" in types or "进球" in sub:
            return "T0", "t0_goal"
    if any(t in ("red_card", "second_yellow_red") for t in types) or "红牌" in sub:
        return "T0", "t0_red"
    if "penalty" in types and "goal" in types:
        return "T0", "t0_penalty_goal"

    # T1 高价值：用链内邻接近似 PDF 邻域
    if "keeper_save" in types and ("shot" in types or "corner" in types):
        return "T1", "save_with_shot_or_corner"
    if "shot" in types and ("keeper_save" in types or "corner" in types):
        return "T1", "shot_then_save_or_corner"
    if "free_kick" in types and ("shot" in types or "keeper_save" in types or "corner" in types):
        return "T1", "fk_threat"
    if sub in ("射门扑救链", "射中门柱/横梁链", "门线极限救险链"):
        return "T1", f"subtype:{sub}"

    # T2
    if "header_shot" in types and ("keeper_save" in types or "corner" in types or "shot" in types):
        return "T2", "header_threat"
    if any(t in ("dribble_past", "dribble_breakthrough", "ball_possession") for t in types) and any(
        t in ("shot", "free_kick", "corner", "pass") for t in types
    ):
        return "T2", "dribble_threat"
    if any(t in ("successful_tackle", "interception", "corner", "throw_in") for t in types) and any(
        t in ("shot", "free_kick", "keeper_save", "pass", "cross") for t in types
    ):
        return "T2", "def_or_corner_threat"
    if sub in ("手抛球发动进攻链", "快发定位球链", "乌龙球致因链"):
        return "T2", f"subtype:{sub}"
    # 险情/特殊但未进 T1 的，降为 T2 候选（仅 with_t2 池用）
    if sub in ("门线极限救险链",) or "throw_in" in types:
        return "T2", "fallback_special_or_throw"
    return "TX", "not_highlight"


def _half_slot(t_ms: int, half_ms: int = HALF_MS) -> Tuple[int, int]:
    if t_ms < half_ms:
        return 1, min(2, max(0, t_ms // SLOT_MS))
    rel = t_ms - half_ms
    return 2, min(2, max(0, rel // SLOT_MS))


def _weight(tier: str, reason: str, types: Sequence[str]) -> int:
    if tier == "T0":
        return 100
    if "shot" in types:
        return 30
    if "keeper_save" in types:
        return 20
    if "free_kick" in types:
        return 10
    if "header_shot" in types:
        return 5
    if any(t in ("dribble_past", "dribble_breakthrough") for t in types):
        return 4
    if "interception" in types:
        return 3
    if "successful_tackle" in types:
        return 2
    if "corner" in types:
        return 1
    return 0


def select_highlight_chains(
    candidates: List[Dict[str, Any]],
    *,
    mode: str = "no_t2",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """对已打 tier 的 gold 链做 PDF 规则筛选。

    mode:
      - no_t2: 仅 T0/T1（规则四也不用 T2）
      - with_t2: PDF 全规则；若仍无 T2 入选且池中有 T2，强制按槽位补入 T2
    """
    t0 = [c for c in candidates if c["tier"] == "T0"]
    t1 = [c for c in candidates if c["tier"] == "T1"]
    t2 = [c for c in candidates if c["tier"] == "T2"] if mode == "with_t2" else []
    t0.sort(key=lambda c: c["t0_ms"])
    t1.sort(key=lambda c: c["t0_ms"])
    t2.sort(key=lambda c: c["t0_ms"])

    has_goal = any(c["tier_reason"] == "t0_goal" for c in t0)
    has_pen = any(c["tier_reason"] == "t0_penalty_goal" for c in t0)
    has_red = any(c["tier_reason"] == "t0_red" for c in t0)

    def half_of(c):
        return _half_slot(c["anchor_t_ms"])[0]

    def pick_slots(pool: List[Dict[str, Any]], per_half: int = 3) -> List[Dict[str, Any]]:
        picked: List[Dict[str, Any]] = []
        for half in (1, 2):
            half_pool = [c for c in pool if half_of(c) == half]
            slot_picks: List[Dict[str, Any]] = []
            for slot in range(3):
                cand = [c for c in half_pool if _half_slot(c["anchor_t_ms"])[1] == slot]
                if not cand:
                    continue
                center = (0 if half == 1 else HALF_MS) + slot * SLOT_MS + SLOT_MS // 2
                cand.sort(
                    key=lambda c: (
                        -_weight(c["tier"], c["tier_reason"], [e["type"] for e in c["events"]]),
                        abs(c["anchor_t_ms"] - center),
                    )
                )
                slot_picks.append(cand[0])
            if len(slot_picks) < per_half:
                used = {id(x) for x in slot_picks}
                rest = [c for c in half_pool if id(c) not in used]
                rest.sort(
                    key=lambda c: (
                        -_weight(c["tier"], c["tier_reason"], [e["type"] for e in c["events"]]),
                        c["anchor_t_ms"],
                    )
                )
                for c in rest:
                    if len(slot_picks) >= per_half:
                        break
                    slot_picks.append(c)
            picked.extend(slot_picks[:per_half])
        picked.sort(key=lambda c: c["t0_ms"])
        return picked

    def dedupe_near(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not items:
            return []
        items = sorted(items, key=lambda c: c["anchor_t_ms"])
        kept = [items[0]]
        for c in items[1:]:
            prev = kept[-1]
            if c["anchor_t_ms"] - prev["anchor_t_ms"] < NEAR_DUP_MS:
                w_c = _weight(c["tier"], c["tier_reason"], [e["type"] for e in c["events"]])
                w_p = _weight(prev["tier"], prev["tier_reason"], [e["type"] for e in prev["events"]])
                if w_c > w_p:
                    kept[-1] = c
                continue
            kept.append(c)
        return kept

    def merge_overlap(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not items:
            return []
        items = sorted(items, key=lambda c: c["t0_ms"])
        out = [items[0]]
        for c in items[1:]:
            prev = out[-1]
            if c["t0_ms"] <= prev["t1_ms"] + MERGE_GAP_MS:
                # 合并区间，保留更高 tier / 更早锚点
                prefer = c if c["tier"] < prev["tier"] else prev  # T0 < T1 lex? use rank
                rank = {"T0": 3, "T1": 2, "T2": 1, "TX": 0}
                prefer = c if rank.get(c["tier"], 0) > rank.get(prev["tier"], 0) else prev
                if rank.get(c["tier"], 0) == rank.get(prev["tier"], 0):
                    prefer = prev if prev["anchor_t_ms"] <= c["anchor_t_ms"] else c
                merged = dict(prefer)
                merged["t0_ms"] = min(prev["t0_ms"], c["t0_ms"])
                merged["t1_ms"] = max(prev["t1_ms"], c["t1_ms"])
                merged["merged_from"] = [prev.get("annotation_id"), c.get("annotation_id")]
                out[-1] = merged
            else:
                out.append(c)
        return out

    rule = ""
    selected: List[Dict[str, Any]] = []

    if has_goal and has_pen and has_red:
        rule = "rule1_t0_only"
        selected = list(t0)
    elif len(t0) == 0:
        rule = "rule2_t1_only"
        selected = dedupe_near(pick_slots(t1, 3))
        if mode == "with_t2" and len(selected) < 4:
            rule = "rule4_t1_plus_t2"
            need = 6 - len(selected)
            used_t = {c["anchor_t_ms"] for c in selected}
            extra = []
            for c in pick_slots(t2, 3):
                if c["anchor_t_ms"] in used_t:
                    continue
                if any(abs(c["anchor_t_ms"] - s["anchor_t_ms"]) < NEAR_DUP_MS for s in selected):
                    continue
                extra.append(c)
                if len(extra) >= need:
                    break
            selected = sorted(selected + extra, key=lambda c: c["t0_ms"])
    elif 1 <= len(t0) <= 5:
        rule = f"rule3_t0_{len(t0)}_fill_t1"
        n = len(t0)
        h1 = [c for c in t0 if half_of(c) == 1]
        h2 = [c for c in t0 if half_of(c) == 2]
        n1, n2 = len(h1), len(h2)
        need1 = need2 = 0
        if n == 1:
            need1, need2 = (2, 3) if n1 == 1 else (3, 2)
        elif n == 2:
            if n1 == 2:
                need1, need2 = 1, 3
            elif n2 == 2:
                need1, need2 = 3, 1
            else:
                need1, need2 = 2, 2
        elif n == 3:
            if n1 == 3:
                need1, need2 = 0, 3
            elif n2 == 3:
                need1, need2 = 3, 0
            elif n1 == 2:
                need1, need2 = 1, 2
            else:
                need1, need2 = 2, 1
        elif n == 4:
            if n1 >= 3:
                need1, need2 = 0, 2
            elif n2 >= 3:
                need1, need2 = 2, 0
            elif n1 == 2 and n2 == 2:
                need1, need2 = 1, 1
            elif n1 == 3 and n2 == 1:
                need1, need2 = 0, 2
            elif n1 == 1 and n2 == 3:
                need1, need2 = 2, 0
            else:
                need1, need2 = max(0, 3 - n1), max(0, 3 - n2)
        elif n == 5:
            if n1 == 5:
                need1, need2 = 0, 1
            elif n2 == 5:
                need1, need2 = 1, 0
            else:
                need1, need2 = 0, 0

        def fill(half: int, need: int) -> List[Dict[str, Any]]:
            if need <= 0:
                return []
            pool = [c for c in t1 if half_of(c) == half]
            t0t = {c["anchor_t_ms"] for c in t0}
            pool = [c for c in pool if all(abs(c["anchor_t_ms"] - t) >= NEAR_DUP_MS for t in t0t)]
            pool.sort(
                key=lambda c: (
                    -_weight(c["tier"], c["tier_reason"], [e["type"] for e in c["events"]]),
                    c["anchor_t_ms"],
                )
            )
            return pool[:need]

        selected = sorted(t0 + fill(1, need1) + fill(2, need2), key=lambda c: c["t0_ms"])
        selected = dedupe_near(selected)
        # 确保 T0 仍在
        have = {c["annotation_id"] for c in selected if c["tier"] == "T0"}
        for c in t0:
            if c["annotation_id"] not in have:
                selected.append(c)
        selected.sort(key=lambda c: c["t0_ms"])
    else:
        rule = "rule_t0_many"
        selected = list(t0)

    selected = merge_overlap(selected)

    # with_t2：并入全部 T2 标注链（按 annotation_id 去重；允许时间重叠，因是独立标注用例）
    if mode == "with_t2":
        t2_all = [c for c in candidates if c["tier"] == "T2"]
        have = {c.get("annotation_id") for c in selected}
        extra = []
        for c in sorted(t2_all, key=lambda x: x["anchor_t_ms"]):
            aid = c.get("annotation_id")
            if aid in have:
                continue
            extra.append(c)
            have.add(aid)
        if extra:
            selected = sorted(selected + extra, key=lambda c: c["t0_ms"])
            rule = (rule or "pdf") + f"|union_t2_x{len(extra)}"

    stats = {
        "rule": rule,
        "mode": mode,
        "n_t0_pool": len([c for c in candidates if c["tier"] == "T0"]),
        "n_t1_pool": len([c for c in candidates if c["tier"] == "T1"]),
        "n_t2_pool": len([c for c in candidates if c["tier"] == "T2"]),
        "n_selected": len(selected),
        "n_t0_selected": sum(1 for c in selected if c["tier"] == "T0"),
        "n_t1_selected": sum(1 for c in selected if c["tier"] == "T1"),
        "n_t2_selected": sum(1 for c in selected if c["tier"] == "T2"),
        "has_goal": has_goal,
        "has_penalty_goal": has_pen,
        "has_red": has_red,
    }
    return selected, stats


def apply_highlight_pdf_window(c: Dict[str, Any]) -> Dict[str, Any]:
    """集锦 gold：按 tier 用与 build_highlights 相同的短窗，并以锚点居中。

    首末事件改为落在该短窗内的事件（与短窗抽链可比）；类别仍用标注大类。
    """
    out = dict(c)
    tier = out.get("tier") or "T1"
    pre, post = HL_WINDOW_MS.get(tier, (8_000, 5_000))
    anchor = int(out.get("anchor_t_ms") or out.get("t0_ms") or 0)
    t0 = max(0, anchor - pre)
    t1 = anchor + post
    out["t0_ms"] = t0
    out["t1_ms"] = t1
    evs = [e for e in (out.get("events") or []) if t0 <= int(e.get("t_ms") or 0) <= t1]
    if not evs:
        evs = list(out.get("events") or [])
    if evs:
        out["first_event"] = evs[0]["type"]
        out["last_event"] = evs[-1]["type"]
        out["events_in_window"] = evs
    out["window_aligned"] = "pdf_select_moments"
    return out


def apply_highlight_windows(chains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [apply_highlight_pdf_window(c) for c in chains]


def _label_score(moment_t: int, t0: int, t1: int, ann: Dict[str, Any], *, moment_type: str = "") -> float:
    """标注链与 select_moments 片的匹配分（允许分钟级钟差）。"""
    anchor = int(ann.get("anchor_t_ms") or 0)
    da = abs(anchor - moment_t)
    # 交付标注与检测时间轴常有偏移，放宽到 ~3min
    if da > 180_000:
        base = 0.0
    else:
        base = 200.0 - da / 1000.0
    score = base
    if t0 <= anchor <= t1:
        score += 50.0
    types = {e.get("type") for e in (ann.get("events") or [])}
    if moment_type and moment_type in types:
        score += 40.0
    if moment_type in ("goal", "penalty") and ann.get("chain_category") == "outcome":
        score += 30.0
    if moment_type in ("red_card", "second_yellow_red") and ann.get("chain_category") == "special":
        score += 30.0
    for e in ann.get("events") or []:
        et = int(e.get("t_ms") or -1)
        if t0 <= et <= t1:
            score += 25.0
        elif abs(et - moment_t) <= 90_000:
            score += 8.0
    return score


def _cat_from_moment_type(event_type: str, tier: str) -> str:
    if event_type in ("goal", "penalty") or (tier == "T0" and "goal" in (event_type or "")):
        return "outcome"
    if event_type in ("red_card", "second_yellow_red", "yellow_card"):
        return "special"
    if event_type in ("keeper_save", "shot", "header_shot", "free_kick", "corner"):
        return "danger"
    return "danger"


def build_highlight_gold_from_select(
    timeline: List[Dict[str, Any]],
    ann_pool: List[Dict[str, Any]],
    *,
    mode: str = "no_t2",
    match_id: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """集锦 gold = causal_chain8.select_moments 选片窗 + 邻近标注补大类/首末。

    与 build_highlights 层 A 同源，避免「标注链选片」与「timeline 选片」时间轴错位
    导致严格完整率接近 0。
    """
    from causal_chain8.select_moments import select_moments

    moments, stats = select_moments(timeline)
    if mode == "no_t2":
        moments = [m for m in moments if m.tier != "T2"]
        stats = dict(stats)
        stats["mode"] = "no_t2"
        stats["n_selected_after_drop_t2"] = len(moments)
    else:
        stats = dict(stats)
        stats["mode"] = "with_t2"

    golds: List[Dict[str, Any]] = []
    labeled = 0
    for m in moments:
        md = m.to_dict() if hasattr(m, "to_dict") else dict(m)
        t0 = int(md["t0_ms"])
        t1 = int(md["t1_ms"])
        ta = int(md["t_ms"])
        tier = md.get("tier") or "T1"
        mtype = str(md.get("event_type") or "")

        best = None
        best_sc = -1.0
        for ann in ann_pool:
            sc = _label_score(ta, t0, t1, ann, moment_type=mtype)
            if sc > best_sc:
                best_sc = sc
                best = ann

        if best is not None and best_sc >= 20.0:
            labeled += 1
            cat = best["chain_category"]
            ann_id = best.get("annotation_id")
            # 大类用标注；首末用短窗内 timeline（与 build_highlights 抽链同一观测）
            tevs = [e for e in timeline if t0 <= int(e.get("t_ms") or -1) <= t1]
            if tevs:
                first = tevs[0]["type"]
                last = tevs[-1]["type"]
                evs = tevs
            else:
                evs = list(best.get("events") or [])
                first = evs[0]["type"] if evs else ""
                last = evs[-1]["type"] if evs else ""
            label_src = "annotation"
        else:
            tevs = [e for e in timeline if t0 <= int(e.get("t_ms") or -1) <= t1]
            first = tevs[0]["type"] if tevs else mtype
            last = tevs[-1]["type"] if tevs else mtype
            cat = _cat_from_moment_type(mtype, tier)
            ann_id = None
            label_src = "timeline_heuristic"
            evs = tevs

        golds.append(
            {
                "annotation_id": ann_id or f"select:{match_id}:{ta}:{tier}",
                "match_id": match_id,
                "chain_category": cat,
                "t0_ms": t0,
                "t1_ms": t1,
                "anchor_t_ms": ta,
                "first_event": first,
                "last_event": last,
                "events": evs,
                "tier": tier,
                "tier_reason": md.get("reason") or "",
                "window_aligned": "select_moments",
                "label_source": label_src,
                "label_score": round(best_sc, 2) if best is not None else 0.0,
                "task": f"highlight_{mode}",
                "highlight_mode": mode,
            }
        )

    stats["n_labeled_by_annotation"] = labeled
    stats["n_heuristic"] = len(golds) - labeled
    stats["n_t0_selected"] = sum(1 for g in golds if g["tier"] == "T0")
    stats["n_t1_selected"] = sum(1 for g in golds if g["tier"] == "T1")
    stats["n_t2_selected"] = sum(1 for g in golds if g["tier"] == "T2")
    return golds, stats


def build_one(stem: str, full_path: Path, cau_path: Path) -> Dict[str, Any]:
    full = json.loads(full_path.read_text(encoding="utf-8"))
    cau = json.loads(cau_path.read_text(encoding="utf-8"))
    timeline = full_events_to_timeline(full)
    match_id = str(cau.get("match_id") or full.get("match_id") or stem)

    strip_gold: List[Dict[str, Any]] = []
    highlight_cands: List[Dict[str, Any]] = []
    skipped = Counter()

    for ch in cau.get("causal_chains") or []:
        if ch.get("is_replay"):
            skipped["replay"] += 1
            continue
        cat_zh = (ch.get("chain_category") or "").strip()
        if not cat_zh or cat_zh not in CAT_ZH_TO_EN:
            skipped["empty_or_unknown_cat"] += 1
            continue
        events = normalize_chain_events(ch)
        if len(events) < 1:
            skipped["no_events"] += 1
            continue
        t0, t1 = chain_time_span(ch)
        rec = {
            "annotation_id": ch.get("annotation_id") or ch.get("bz_id"),
            "match_id": match_id,
            "chain_category": CAT_ZH_TO_EN[cat_zh],
            "chain_category_zh": cat_zh,
            "chain_subtype": ch.get("causal_chain_subtype") or "",
            "t0_ms": t0,
            "t1_ms": t1,
            "first_event": events[0]["type"],
            "last_event": events[-1]["type"],
            "events": events,
            "task": "strip",
        }
        strip_gold.append(rec)

        tier, reason = tag_chain_tier(events, rec["chain_subtype"])
        anchor = events[-1]["t_ms"] if events else t0
        for e in events:
            if e["type"] in ("goal", "penalty", "red_card", "second_yellow_red"):
                anchor = e["t_ms"]
                break
        hc = dict(rec)
        hc.update(
            {
                "tier": tier,
                "tier_reason": reason,
                "anchor_t_ms": anchor,
                "task": "highlight_cand",
            }
        )
        if tier in ("T0", "T1", "T2"):
            highlight_cands.append(hc)

    # 集锦 gold：与 build_highlights 同源 select_moments，再用标注补标签
    hl_no_t2, stats_no = build_highlight_gold_from_select(
        timeline, highlight_cands, mode="no_t2", match_id=match_id
    )
    hl_with_t2, stats_with = build_highlight_gold_from_select(
        timeline, highlight_cands, mode="with_t2", match_id=match_id
    )

    return {
        "stem": stem,
        "match_id": match_id,
        "n_timeline_events": len(timeline),
        "skipped": dict(skipped),
        "timeline": timeline,
        "strip_gold": strip_gold,
        "highlight_gold_no_t2": hl_no_t2,
        "highlight_gold_with_t2": hl_with_t2,
        "highlight_stats_no_t2": stats_no,
        "highlight_stats_with_t2": stats_with,
        "source_full": str(Path("data") / "交付_out" / full_path.name),
        "source_causal": str(Path("data") / "交付_out" / cau_path.name),
    }


def main() -> None:
    if not SRC.is_dir():
        raise SystemExit(f"missing source data: {SRC}")
    print(f"SRC={SRC}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "matches").mkdir(exist_ok=True)

    pairs = []
    for cau in sorted(SRC.glob("*_causal.json")):
        stem = cau.name[: -len("_causal.json")]
        full = SRC / f"{stem}.json"
        if full.exists():
            pairs.append((stem, full, cau))

    strip_all: List[Dict[str, Any]] = []
    hl_no_all: List[Dict[str, Any]] = []
    hl_with_all: List[Dict[str, Any]] = []
    index: List[Dict[str, Any]] = []

    for stem, full, cau in pairs:
        built = build_one(stem, full, cau)
        # 每场落盘（timeline + gold）
        safe = re.sub(r"[^\w\-.]+", "_", stem)[:80]
        match_dir = OUT / "matches" / safe
        match_dir.mkdir(parents=True, exist_ok=True)
        (match_dir / "timeline.json").write_text(
            json.dumps(
                {
                    "match_id": built["match_id"],
                    "events": built["timeline"],
                    "source_full": built["source_full"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (match_dir / "strip_gold.json").write_text(
            json.dumps(built["strip_gold"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (match_dir / "highlight_gold_no_t2.json").write_text(
            json.dumps(
                {
                    "stats": built["highlight_stats_no_t2"],
                    "chains": built["highlight_gold_no_t2"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (match_dir / "highlight_gold_with_t2.json").write_text(
            json.dumps(
                {
                    "stats": built["highlight_stats_with_t2"],
                    "chains": built["highlight_gold_with_t2"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        # 兼容旧文件名：默认指向 no_t2
        (match_dir / "highlight_gold.json").write_text(
            json.dumps(
                {
                    "stats": built["highlight_stats_no_t2"],
                    "chains": built["highlight_gold_no_t2"],
                    "note": "alias of highlight_gold_no_t2",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        meta = {
            "stem": stem,
            "safe_id": safe,
            "match_id": built["match_id"],
            "n_timeline_events": built["n_timeline_events"],
            "n_strip_gold": len(built["strip_gold"]),
            "n_highlight_gold_no_t2": len(built["highlight_gold_no_t2"]),
            "n_highlight_gold_with_t2": len(built["highlight_gold_with_t2"]),
            "highlight_rule_no_t2": built["highlight_stats_no_t2"].get("rule"),
            "highlight_rule_with_t2": built["highlight_stats_with_t2"].get("rule"),
            "n_t2_in_with": built["highlight_stats_with_t2"].get("n_t2_selected", 0),
            "skipped": built["skipped"],
            "dir": str(match_dir.relative_to(ROOT)),
        }
        (match_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        index.append(meta)
        strip_all.extend(built["strip_gold"])
        hl_no_all.extend(built["highlight_gold_no_t2"])
        hl_with_all.extend(built["highlight_gold_with_t2"])

    summary = {
        "n_matches": len(index),
        "n_strip_cases": len(strip_all),
        "n_highlight_cases_no_t2": len(hl_no_all),
        "n_highlight_cases_with_t2": len(hl_with_all),
        # 填表口径：只计拆条 + 集锦(无T2)；with_t2 仅存档对照
        "n_highlight_cases": len(hl_no_all),
        "highlight_mode": "no_t2_only",
        "n_total_cases": len(strip_all) + len(hl_no_all),
        "category_hist_strip": dict(Counter(x["chain_category"] for x in strip_all)),
        "tier_hist_highlight_no_t2": dict(Counter(x.get("tier", "") for x in hl_no_all)),
        "tier_hist_highlight_with_t2": dict(Counter(x.get("tier", "") for x in hl_with_all)),
        "exclude_replay": True,
        "exclude_empty_category": True,
        "gpu_idle_hint": "CUDA_VISIBLE_DEVICES=2",
        "case_count_note": "计划总用例 = 拆条 + 集锦(无T2)；集锦gold=select_moments窗+标注标签",
        "highlight_gold_window": "select_moments",
    }
    (OUT / "index.json").write_text(
        json.dumps({"summary": summary, "matches": index}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (OUT / "strip_gold.jsonl").open("w", encoding="utf-8") as f:
        for r in strip_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT / "highlight_gold_no_t2.jsonl").open("w", encoding="utf-8") as f:
        for r in hl_no_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT / "highlight_gold_with_t2.jsonl").open("w", encoding="utf-8") as f:
        for r in hl_with_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # 兼容
    with (OUT / "highlight_gold.jsonl").open("w", encoding="utf-8") as f:
        for r in hl_no_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
