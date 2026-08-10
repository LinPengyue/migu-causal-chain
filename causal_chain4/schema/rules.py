"""
chain4 骨架匹配与转移规则（完全基于 causal_chain4.schema.skeletons）。

匹配策略（贴近业务长链）：
1. 精确等于某条 skeleton sequence
2. 后缀匹配某条 sequence（前面为组织进攻前缀）
3. 有序子序列匹配（LCS 式）且长度在 [min_len, max_len]
4. 白名单 + 结局 + 关键节点软匹配
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from causal_chain4.schema.skeletons import CHAIN4_SKELETONS, canonical_sequences_map
from causal_chain4.schema.templates import ALL_TEMPLATE_IDS


def _transitions_from_sequences(seqs: List[List[str]]) -> Set[Tuple[str, str]]:
    out: Set[Tuple[str, str]] = set()
    for seq in seqs:
        for a, b in zip(seq, seq[1:]):
            out.add((a, b))
    return out


def _lcs_indices(seq: List[str], pattern: List[str]) -> List[int]:
    indices: List[int] = []
    j = 0
    for i, t in enumerate(seq):
        if j < len(pattern) and t == pattern[j]:
            indices.append(i)
            j += 1
    if j < len(pattern):
        return []
    return indices


def _whitelist_ok(types: List[str], whitelist: List[str]) -> bool:
    if not whitelist:
        return True
    allow = set(whitelist)
    return all(t in allow for t in types)


@dataclass
class RulesContext:
    mode: str = "annotation"  # annotation | strict
    overlays: Dict[str, Dict] = field(default_factory=dict)
    canonical_sequences: Dict[str, List[List[str]]] = field(default_factory=dict)
    allowed_transitions: Dict[str, Set[Tuple[str, str]]] = field(default_factory=dict)
    skeletons: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: Dict | None = None) -> "RulesContext":
        profile = profile or {}
        mode = str(profile.get("rules_mode", "annotation"))
        overlays = dict(profile.get("rules_overlays") or {})
        canonical = canonical_sequences_map()
        skeletons = {tid: dict(meta) for tid, meta in CHAIN4_SKELETONS.items()}

        for tid, ov in overlays.items():
            if tid not in canonical:
                canonical[tid] = []
            for seq in ov.get("canonical_extra") or []:
                if list(seq) not in canonical[tid]:
                    canonical[tid].append(list(seq))
            if tid in skeletons:
                if ov.get("max_len"):
                    skeletons[tid]["max_len"] = int(ov["max_len"])
                if ov.get("min_len"):
                    skeletons[tid]["min_len"] = int(ov["min_len"])
                if ov.get("prefix_allowed"):
                    wl = list(skeletons[tid].get("event_whitelist") or [])
                    for p in ov["prefix_allowed"]:
                        if p not in wl:
                            wl.append(p)
                    skeletons[tid]["event_whitelist"] = wl

        allowed = {
            tid: _transitions_from_sequences(canonical.get(tid, []))
            for tid in ALL_TEMPLATE_IDS
        }
        # 白名单内事件两两可转移（annotation 模式），贴近真实标注长链
        if mode == "annotation":
            for tid, meta in skeletons.items():
                wl = meta.get("event_whitelist") or []
                for a in wl:
                    for b in wl:
                        allowed.setdefault(tid, set()).add((a, b))

        return cls(
            mode=mode,
            overlays=overlays,
            canonical_sequences=canonical,
            allowed_transitions=allowed,
            skeletons=skeletons,
        )

    def length_ok(self, template_id: str, event_types: List[str]) -> bool:
        meta = self.skeletons.get(template_id) or {}
        n = len(event_types)
        mn = int(meta.get("min_len", 1))
        mx = int(meta.get("max_len", 20))
        return mn <= n <= mx

    def soft_match_score(self, template_id: str, event_types: List[str]) -> float:
        """0~1.5：骨架贴合度，供规则排序。"""
        if not event_types or template_id not in self.skeletons:
            return 0.0
        meta = self.skeletons[template_id]
        if not self.length_ok(template_id, event_types):
            # 略超长仍给低分，便于长链扑救等
            if len(event_types) > int(meta.get("max_len", 20)) + 3:
                return 0.0

        score = 0.0
        terminals = set(meta.get("terminal_events") or [])
        keys = set(meta.get("key_events") or [])
        whitelist = list(meta.get("event_whitelist") or [])

        if terminals and event_types[-1] in terminals:
            score += 0.35
        elif terminals and any(t in event_types for t in terminals):
            score += 0.15

        if keys and any(k in event_types for k in keys):
            score += 0.25

        if _whitelist_ok(event_types, whitelist):
            score += 0.1
        else:
            score -= 0.2

        best_cov = 0.0
        exact = False
        for seq in self.canonical_sequences.get(template_id, []):
            if event_types == seq:
                exact = True
                best_cov = 1.0
                break
            if len(event_types) >= len(seq) and event_types[-len(seq) :] == seq:
                best_cov = max(best_cov, 0.92)
                continue
            idx = _lcs_indices(event_types, seq)
            if idx:
                cov = len(idx) / max(len(seq), 1)
                # 惩罚抽取过稀
                dens = len(idx) / max(len(event_types), 1)
                best_cov = max(best_cov, 0.55 * cov + 0.25 * dens)

        score += best_cov
        if exact:
            score += 0.2

        # 长度落在推荐区间加分
        n = len(event_types)
        mn, mx = int(meta.get("min_len", 1)), int(meta.get("max_len", 20))
        if mn <= n <= mx:
            score += 0.08
        elif n > mx:
            score -= min(0.25, 0.03 * (n - mx))

        return max(0.0, min(1.6, score))

    def sequence_matches(self, template_id: str, event_types: List[str]) -> bool:
        if template_id not in self.canonical_sequences:
            return False
        if event_types in self.canonical_sequences[template_id]:
            return True
        if self.mode == "strict":
            return False
        # annotation：后缀或高覆盖 LCS
        for seq in self.canonical_sequences[template_id]:
            if len(event_types) >= len(seq) and event_types[-len(seq) :] == seq:
                return True
            idx = _lcs_indices(event_types, seq)
            if idx and len(idx) == len(seq) and len(event_types) <= int(
                (self.skeletons.get(template_id) or {}).get("max_len", 20)
            ) + 2:
                return True
        return False

    def consecutive_pairs_allowed(self, template_id: str, event_types: List[str]) -> bool:
        if len(event_types) < 2:
            return True
        meta = self.skeletons.get(template_id) or {}
        whitelist = list(meta.get("event_whitelist") or [])
        if self.mode == "annotation" and whitelist and _whitelist_ok(event_types, whitelist):
            return True
        return self._pairs_ok(template_id, event_types)

    def _pairs_ok(self, template_id: str, event_types: List[str]) -> bool:
        allowed = self.allowed_transitions.get(template_id, set())
        if not allowed:
            return True
        return all((a, b) in allowed for a, b in zip(event_types, event_types[1:]))

    def check_transitions(self, template_id: str, event_types: List[str]) -> Dict[str, Any]:
        ok = self.consecutive_pairs_allowed(template_id, event_types)
        illegal: List[str] = []
        allowed = self.allowed_transitions.get(template_id, set())
        if not ok:
            for a, b in zip(event_types, event_types[1:]):
                if (a, b) not in allowed:
                    illegal.append(f"{a}→{b}")
        return {
            "chain_template_id": template_id,
            "allowed": ok,
            "illegal_pairs": illegal,
            "exact_canonical_match": self.sequence_matches(template_id, event_types),
            "soft_score": round(self.soft_match_score(template_id, event_types), 4),
            "length_ok": self.length_ok(template_id, event_types),
        }

    def best_template(self, event_types: List[str], *, top_k: int = 5) -> List[Dict[str, Any]]:
        ranked: List[Dict[str, Any]] = []
        for tid in ALL_TEMPLATE_IDS:
            s = self.soft_match_score(tid, event_types)
            if s <= 0:
                continue
            check = self.check_transitions(tid, event_types)
            ranked.append(
                {
                    "chain_template_id": tid,
                    "soft_score": round(s, 4),
                    "critic_score": round(s + (0.1 if check["allowed"] else -0.15), 4),
                    "transitions_ok": check["allowed"],
                    "exact_canonical": check["exact_canonical_match"],
                    "length_ok": check["length_ok"],
                }
            )
        ranked.sort(key=lambda x: -x["critic_score"])
        return ranked[:top_k]
