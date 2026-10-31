# STORY_VA_V2 G0 — Match Matrix (inventory only; no inference)

**Checked:** 2026-10-31. Methods: `test -f` / `ls -lh` / `ffprobe` / JSON key inspection / adapter smoke on score trajectory. **No VLM, no 8.31 re-run, no render.**

## Summary

| ID | Match | MP4 | Raw events | Causal (FORBIDDEN as V2 input) | Gold dataset | V2 run status |
|----|-------|-----|------------|--------------------------------|--------------|---------------|
| M0 | 克罗地亚 vs 加拿大 | ✅ | ✅ repo `交付_out` | ✅ present | Croatia pipeline | R2.9 frozen `render_ready=false` |
| A | 阿联酋 vs 阿曼 | ✅ | ✅ | ✅ | gold only | **Not run (G0)** |
| B | 奥萨苏纳 vs 塞尔塔 | ✅ | ✅ | ✅ | gold only | **Not run (G0)** |
| C | 法国 vs 澳大利亚 | ✅ (now complete) | ✅ | ✅ | — | **G1 optional; not executed** |
| N | 卡塔尔 vs 阿联酋 | ❌ no MP4 | ✅ events | ✅ | — | **Cannot be video negative** |

Phase5 V1 packages under `reports/phase5/{uae_oman,osasuna_celta}/` = causal-era background only.

---

## M0 — Croatia vs Canada (regression reference only)

| Item | Path / note |
|------|-------------|
| MP4 | `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4` |
| Events | `10.27scasual_chain/data/交付_out/2022-11-28 克罗地亚vs加拿大.json` |
| Score path | `0:1→1:1→2:1→3:1→4:1` left protagonist + extend |
| V2 | R2.9 EDL/render exist; **blocked_source_corruption** on 3:1; do not “fix” for A/B |
| G1 role | Smoke that Croatia still fails closed; prove new CLI defaults do not break freeze |

---

## A — UAE vs Oman (primary G1 candidate)

| Item | Status |
|------|--------|
| MP4 | `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` — **5.7G**, duration **8149.48s**, exists |
| Events (raw) | Repo: `data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json` (also under `/data2/lpy1/causal-chain2/.../交付_out/`) — **749** events |
| Causal | `..._阿联酋VS阿曼_国语_causal.json` — **25** chains — **DO NOT FEED V2** |
| Dataset dir | `datasets/matches/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语/` — `strip_gold` / `highlight_gold*` / `timeline` / `meta` only (**no raw events.json**) |
| Typed Goal events | ~0 usable (`Goal_line_clearance` only) → missing-goal path required |
| Scoreboard path (from events via adapter) | `(0,0)→(0,1)→(1,1)→(2,1)` → `story_candidate`, **deficit left**, eq `(1,1)`, go-ahead `(2,1)` |
| Narrative shape | Mid-match deficit → equalize → lead; **3 goal steps**; no 4:1 extend |
| Historical 8.31 dumps | Present under causal-chain2 / 10.27 `strip_dump*` / `reels_dump*` — provenance for V2 **NOT_VERIFIED** |
| Phase5 V1 | `reports/phase5/uae_oman/` story_graph/EDL — causal-dependent |
| G1 test purpose | Prove N≠5 EDL + mid-match T01 + recovery without Goal types |
| G1 risk | Wrong Croatia default cache; forcing five beats; using causal times |

---

## B — Osasuna vs Celta (right last-arc stress)

| Item | Status |
|------|--------|
| MP4 | `/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4` — **5.1G**, duration **7676.06s**, exists |
| Events | `data/交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json` — **663** events |
| Causal | `..._causal.json` — **33** chains — forbidden |
| Dataset | gold/timeline only (same pattern as A) |
| Typed Goal | **0** |
| Scoreboard path | `(0,0)→(0,1)→(1,1)→(2,1)→(2,2)→(2,3)` (+ OCR noise token `1：！` seen in raw scan) |
| Adapter first-arc analysis | Marks left `story_candidate` at go-ahead `(2,1)` — **incorrect for intended T01 last arc** |
| Intended T01 | **Right (Celta)** last deficit: trail at 2:1 → 2:2 → 2:3 |
| Phase5 V1 | `reports/phase5/osasuna_celta/` |
| G1 test purpose | Last-deficit right protagonist; multi lead-change; OCR noise |
| G1 risk | P0-4 wrong protagonist; five-goal Croatia EDL; cache collision |

---

## C — France vs Australia (optional G1 reserve)

| Item | Status |
|------|--------|
| MP4 | `/mnt/data4/migu/2022年11月23日 法国vs澳大利亚.mp4` — **3.4G**, **now present** (phase5 inventory previously “uploading”) |
| Events / causal | `data/交付_out/2022年11月23日 法国vs澳大利亚{,_causal}.json` ✅ |
| G0 | Inventoried only — **not marked tested** |
| Use | Only after A (and preferably B) P0 fixes |

---

## N — Negative / no-comeback

| Candidate | Video | Events | Verdict |
|-----------|-------|--------|---------|
| 卡塔尔 vs 阿联酋 | **Missing** under `/mnt/data4/migu/*卡塔尔*` | `交付_out/10月15日_...卡塔尔VS阿联酋_国语.json` (145 events; scoreboard mostly `0:0` in quick scan) | **Cannot execute video N** |
| Need | Any match MP4 + events where one side leads throughout | — | Locate before claiming no_comeback gate |

---

## G1 suggested order (execution later)

1. Wire P0 isolation + generic EDL + last-arc API.  
2. Match A (3-goal left mid-comeback) dry pipeline, `render_ready=false`.  
3. Match B (right last-arc) dry pipeline.  
4. Optional C.  
5. Real N only when MP4+events both exist.
