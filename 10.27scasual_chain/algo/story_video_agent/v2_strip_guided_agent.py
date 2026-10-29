"""Strip-Guided planner — DeepSeek selects predicted strips; Qwen verifies video."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider
from story_video_agent.tools import ToolArgumentError
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PLANNER_SYSTEM = """You are Story Video Agent V2 Strip-Guided mode.
You receive ALGORITHM-PREDICTED strip causal chains (causal_chain6) plus optional score anchors.
These strips are NOT human gold and NOT video-verified.

Target story TYPE: T01 comeback (either side trails then later leads) if evidence supports it.

Return ONE JSON per turn:
A) {"type":"tool","tool":"list_strips"|"select_strip"|"reject_strip"|"observe_strip"|"finish_story",
    "arguments":{...}}
B) observe_strip args: {"strip_chain_id":"...","start":sec,"end":sec,"purpose":"dense|coarse|live_replay"}
C) finish_story / answer:
 {"type":"answer","answer":"story_candidate|partial_story|no_comeback|unresolved","reason":"...",
  "story_candidates":[{"candidate_id":"t01","strip_chain_ids":[],"note":""}],
  "beats":{"setup":{"strip_chain_ids":[],"event_ids":[],"media_in":null,"media_out":null,"note":""},
           "buildup":{...},"turning":{...},"climax":{...},"resolution":{...}},
  "relations":[{"source_chain_id":"...","target_chain_id":"...",
    "relation_type":"temporal|narrative|causal|correction",
    "explanation":"...","supporting_event_ids":[],"supporting_evidence_ids":[],
    "verification_status":"proposed"}]}

Rules:
1. Prefer verifying danger/outcome/correction strips near score changes — but do not invent goals.
2. observe_strip windows should start from strip t0/t1; refine boundaries, do not invent far-away times.
3. Causal inter-chain links need supporting_evidence_ids; score-order alone → temporal/narrative only.
4. One tool/answer per turn; compact JSON.
"""

META = {"list_strips", "select_strip", "reject_strip"}
VIDEO = {"observe_strip"}


class V2StripGuidedAgent:
    def __init__(
        self,
        *,
        duration: float,
        tools: V2PhaseC1Toolbox,
        api: ApiProvider,
        use_llm_planner: bool = True,
        planner_temperature: float = 0.1,
    ) -> None:
        self.duration = float(duration)
        self.tools = tools
        self.api = api
        self.use_llm_planner = bool(use_llm_planner)
        self.planner_temperature = float(planner_temperature)
        self.decision_attempts: List[Dict[str, Any]] = []
        self.planner_mode_log: List[str] = []

    def decide(self, memory: Any, step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = []
        remaining = max_steps - step
        rule = self._rule_policy(memory, remaining)
        want_llm = bool(self.use_llm_planner)
        for attempt in range(2):
            raw = rule
            parse_mode = "rule_policy"
            if want_llm:
                try:
                    llm = self._propose_llm(memory, remaining, step=step, max_steps=max_steps)
                    if isinstance(llm, dict) and "type" in llm:
                        if remaining <= 1 and llm.get("type") != "answer":
                            raw = self.finish_from_memory(memory, reason="last_step_force_answer")
                            parse_mode = "rule_terminal_forced"
                            self.planner_mode_log.append("llm_non_terminal_forced")
                        else:
                            raw = llm
                            parse_mode = "llm_api"
                            self.planner_mode_log.append(
                                "llm_mid" if remaining > 1 else "llm_terminal"
                            )
                    else:
                        self.planner_mode_log.append("llm_fallback_rule")
                except Exception:  # noqa: BLE001
                    self.planner_mode_log.append("llm_error_fallback_rule")
                    raw = rule
            else:
                self.planner_mode_log.append("rule_baseline")

            record = {"attempt": attempt, "raw_response": raw, "parse_mode": parse_mode}
            self.decision_attempts.append(record)
            try:
                decision = self._normalize(raw, remaining)
                record.update(status="accepted", decision=decision)
                memory.decisions.append(
                    {
                        "step": step,
                        "parse_mode": parse_mode,
                        "tool": decision.get("tool"),
                        "type": decision.get("type"),
                        "used_llm": parse_mode == "llm_api",
                    }
                )
                return decision
            except (ValueError, TypeError, ToolArgumentError) as exc:
                record.update(status="rejected", error=str(exc))
                if remaining <= 1 or attempt:
                    term = self.finish_from_memory(memory, reason=f"fallback:{exc}")
                    record.update(status="accepted_terminal", decision=term)
                    return term
                continue
        raise ValueError("invalid_decision")

    def finish_from_memory(self, memory: Any, *, reason: str) -> Dict[str, Any]:
        anchors = memory.event_digest.get("score_anchors") or []
        pairs = []
        for a in anchors:
            if a.get("kind") == "initial_score" and a.get("score_pair"):
                pairs.append(tuple(a["score_pair"]))
            if a.get("kind") == "score_change" and a.get("score_after"):
                pairs.append(tuple(a["score_after"]))
        status = "unresolved"
        if len(pairs) >= 2:
            first, later = pairs[0], pairs[-1]
            if (first[0] < first[1] and later[0] > later[1]) or (
                first[1] < first[0] and later[1] > later[0]
            ):
                status = "story_candidate"
            else:
                status = "partial_story"
        elif memory.verifications:
            status = "partial_story"

        # Map verified / high-priority strips into beats by time order
        strips = sorted(
            memory.chain_states.values(),
            key=lambda c: float(c.get("t0_sec") or 0),
        )
        interesting = [
            c
            for c in strips
            if c.get("predicted_category") in ("danger", "outcome", "correction")
            or c.get("status") == "verified"
            or (c.get("confidence") or 0) >= 0.5
        ]
        if not interesting:
            interesting = strips[:8]

        def beat(ids: List[str], note: str) -> Dict[str, Any]:
            media = []
            for sid in ids:
                c = memory.chain_states.get(sid) or {}
                mi = c.get("refined_media_in") or c.get("t0_sec")
                mo = c.get("refined_media_out") or c.get("t1_sec")
                if mi is not None:
                    media.append((float(mi), float(mo or mi)))
            return {
                "strip_chain_ids": ids,
                "event_ids": [],
                "media_in": min((m[0] for m in media), default=None),
                "media_out": max((m[1] for m in media), default=None),
                "note": note,
            }

        ids = [c["strip_chain_id"] for c in interesting]
        n = len(ids)
        beats = {
            "setup": beat(ids[:1], "earliest priority strip / deficit context"),
            "buildup": beat(ids[1:2] if n > 1 else [], "buildup strip if any"),
            "turning": beat(ids[2:3] if n > 2 else (ids[1:2] if n > 1 else []), "turning"),
            "climax": beat(ids[3:4] if n > 3 else (ids[-2:-1] if n > 1 else []), "climax"),
            "resolution": beat(ids[-1:] if n else [], "resolution"),
        }
        relations: List[Dict[str, Any]] = []
        for i in range(len(ids) - 1):
            relations.append(
                {
                    "source_chain_id": ids[i],
                    "target_chain_id": ids[i + 1],
                    "relation_type": "temporal",
                    "explanation": "time-ordered priority strips along score path",
                    "supporting_event_ids": [],
                    "supporting_evidence_ids": [],
                    "verification_status": "proposed",
                }
            )
            relations.append(
                {
                    "source_chain_id": ids[i],
                    "target_chain_id": ids[i + 1],
                    "relation_type": "narrative",
                    "explanation": "same T01 score-path narrative candidate (not causal proof)",
                    "supporting_event_ids": [],
                    "supporting_evidence_ids": [],
                    "verification_status": "proposed",
                }
            )
        return {
            "type": "answer",
            "answer": status,
            "reason": reason,
            "story_candidates": [
                {
                    "candidate_id": "t01",
                    "strip_chain_ids": ids[:6],
                    "note": "assembled from predicted strips + score anchors",
                }
            ],
            "beats": beats,
            "relations": relations,
        }

    def _rule_policy(self, memory: Any, remaining: int) -> Dict[str, Any]:
        if remaining <= 1:
            return self.finish_from_memory(memory, reason="budget_or_last_step")
        # Verify unverified danger/outcome/correction near score changes first
        anchors = [
            a
            for a in (memory.event_digest.get("score_anchors") or [])
            if a.get("kind") in ("score_change", "initial_score")
        ]
        anchor_times = [float(a["event_time_sec"]) for a in anchors if a.get("event_time_sec") is not None]

        def near_anchor(c: Dict[str, Any]) -> bool:
            if not anchor_times:
                return True
            mid = 0.5 * (float(c.get("t0_sec") or 0) + float(c.get("t1_sec") or 0))
            return any(abs(mid - t) <= 180.0 for t in anchor_times)

        cands = [
            c
            for c in memory.chain_states.values()
            if c.get("status") in ("open", "selected", "observing")
            and (
                c.get("predicted_category") in ("danger", "outcome", "correction")
                or near_anchor(c)
            )
        ]
        cands.sort(
            key=lambda c: (
                0 if c.get("predicted_category") in ("outcome", "danger") else 1,
                -float(c.get("confidence") or 0),
                float(c.get("t0_sec") or 0),
            )
        )
        for c in cands:
            sid = c["strip_chain_id"]
            n_obs = len(c.get("verifications") or [])
            if n_obs == 0:
                start = max(0.0, float(c["t0_sec"]))
                end = min(self.duration, max(start + 2.0, float(c["t1_sec"])))
                # shrink to dense max ~12s around center of strip
                mid = 0.5 * (start + end)
                start = max(0.0, mid - 5.0)
                end = min(self.duration, start + 10.0)
                return {
                    "type": "tool",
                    "tool": "observe_strip",
                    "arguments": {
                        "strip_chain_id": sid,
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "purpose": "dense",
                    },
                }
            if n_obs == 1:
                # refine toward start of strip (often action before end)
                start = max(0.0, float(c["t0_sec"]))
                end = min(self.duration, start + 10.0)
                return {
                    "type": "tool",
                    "tool": "observe_strip",
                    "arguments": {
                        "strip_chain_id": sid,
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "purpose": "live_replay",
                    },
                }
            if n_obs >= 2 and c.get("status") != "verified":
                return {
                    "type": "tool",
                    "tool": "reject_strip",
                    "arguments": {
                        "strip_chain_id": sid,
                        "reason": "no_frame_bound_action_after_two_looks",
                    },
                }
        return self.finish_from_memory(memory, reason="strips_exhausted")

    def _propose_llm(self, memory: Any, remaining: int, *, step: int, max_steps: int):
        user = {
            "step": step,
            "max_steps": max_steps,
            "remaining": remaining,
            "tools": sorted(META | VIDEO | {"finish_story"}),
            "facts": memory.facts_for_planner(remaining=remaining),
        }
        mock = json.dumps(self._rule_policy(memory, remaining), ensure_ascii=False)
        raw = self.api.chat(
            role="planner",
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            temperature=self.planner_temperature,
            mock_content=mock,
        )
        text = str((raw or {}).get("content") or "")
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        m = _JSON_OBJ.search(text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    def _normalize(self, raw: Dict[str, Any], remaining: int) -> Dict[str, Any]:
        if not isinstance(raw, dict) or "type" not in raw:
            raise ValueError("bad decision")
        if raw["type"] == "tool":
            if remaining <= 1:
                raise ValueError("last step must answer")
            name = str(raw.get("tool") or "")
            args = raw.get("arguments") or {}
            if name == "finish_story":
                return self._normalize(
                    {"type": "answer", **{k: v for k, v in raw.items() if k != "type"}},
                    remaining,
                )
            if name not in META | VIDEO:
                raise ValueError(f"unknown tool {name}")
            return {"type": "tool", "tool": name, "arguments": args if isinstance(args, dict) else {}}
        if raw["type"] == "answer":
            ans = str(raw.get("answer") or "unresolved")
            if ans not in {"story_candidate", "partial_story", "no_comeback", "unresolved"}:
                ans = "unresolved"
            return {
                "type": "answer",
                "answer": ans,
                "reason": str(raw.get("reason") or ""),
                "story_candidates": raw.get("story_candidates")
                if isinstance(raw.get("story_candidates"), list)
                else [],
                "beats": raw.get("beats") if isinstance(raw.get("beats"), dict) else {},
                "relations": raw.get("relations") if isinstance(raw.get("relations"), list) else [],
            }
        raise ValueError(f"bad type {raw['type']}")
