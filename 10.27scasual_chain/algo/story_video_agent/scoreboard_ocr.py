"""Scoreboard ROI localization + local OCR (CPU / tesseract CLI).

Rejects match-clock patterns; does not invent scores from loose digit pairs.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from story_chain.score_path import parse_score

# Soccer score pair on ONE line; separators: : ： V v - | ｜
_SCORE_PAIR = re.compile(
    r"(?<!\d)([0-9])[ \t]*[:：Vv\-|｜][ \t]*([0-9])(?!\d)"
)
_SCORE_PAIR_LOOSE = re.compile(
    r"(?<!\d)([0-9]{1,2})[ \t]*[:：Vv\-|｜][ \t]*([0-9]{1,2})(?!\d)"
)
# MM:SS style clock (seconds always two digits 00-59)
_CLOCK = re.compile(r"(?<!\d)([0-5]?\d):([0-5]\d)(?!\d)")
# Stacked scores (Osasuna-like): two consecutive lines that are single digits
_STACKED = re.compile(r"(?m)^[ \t]*([0-9])[ \t]*$\n[ \t]*([0-9])[ \t]*$")
# CJK team ... digit ... digit ... CJK team (broadcast Chinese bugs)
_CJK_SCORE = re.compile(
    r"[\u4e00-\u9fff]{2,}.{0,8}?(?<!\d)([0-9])(?!\d).{0,12}?(?<!\d)([0-9])(?!\d).{0,8}?[\u4e00-\u9fff]{2,}"
)
# Latin TEAM DIGIT junk DIGIT TEAM
_LATIN_SCORE = re.compile(
    r"\b([A-Z]{3,})\s+([0-9])\b.{0,16}?\b([0-9])\s+([A-Z]{3,})\b"
)


@dataclass
class RoiBox:
    name: str
    x0: float  # normalized 0-1
    y0: float
    x1: float
    y1: float

    def crop(self, frame_bgr: np.ndarray) -> np.ndarray:
        h, w = frame_bgr.shape[:2]
        x0, x1 = int(self.x0 * w), int(self.x1 * w)
        y0, y1 = int(self.y0 * h), int(self.y1 * h)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, max(x0 + 1, x1)), min(h, max(y0 + 1, y1))
        return frame_bgr[y0:y1, x0:x1]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _require_tesseract() -> str:
    import shutil

    p = shutil.which("tesseract")
    if not p:
        raise RuntimeError("tesseract not found on PATH")
    return p


def candidate_roi_grid() -> List[RoiBox]:
    """Small-ish windows covering common scorebug placements (not whole top strip)."""
    boxes: List[RoiBox] = []
    # top band tiles
    for i, (x0, x1) in enumerate(
        [(0.0, 0.28), (0.0, 0.40), (0.30, 0.70), (0.55, 0.88), (0.70, 1.0)]
    ):
        boxes.append(RoiBox(f"top_{i}", x0, 0.0, x1, 0.14))
        boxes.append(RoiBox(f"topmid_{i}", x0, 0.02, x1, 0.18))
    # bottom banner center / sides (Croatia-style lower graphic)
    boxes.append(RoiBox("bot_c", 0.25, 0.78, 0.75, 0.98))
    boxes.append(RoiBox("bot_l", 0.05, 0.80, 0.45, 0.98))
    boxes.append(RoiBox("bot_r", 0.55, 0.80, 0.95, 0.98))
    return boxes


def classify_numeric_pair(a: int, b: int, *, raw: str, sep_hint: str = "") -> str:
    """Return 'score' | 'clock' | 'reject'."""
    if a > 15 or b > 15:
        return "reject"
    # Zero-padded or two-digit seconds → clock (04:12, 15:52, 44:46)
    if re.search(rf"(?<!\d){a}:([0-5]\d)(?!\d)", raw) and b >= 10:
        return "clock"
    if re.search(rf"(?<!\d)0?{a}:0?{b}(?!\d)", raw) and b >= 10:
        return "clock"
    m = _CLOCK.search(raw.replace("：", ":"))
    if m and int(m.group(1)) == a and int(m.group(2)) == b and b >= 10:
        return "clock"
    # Soccer scores almost always single-digit each side in these broadcasts
    if a <= 9 and b <= 9:
        # Ambiguous early clock like 4:2 without zero-pad: treat as score candidate
        # but caller must multi-frame confirm. Prefer V/- separators as score.
        if "V" in raw.upper() or "v" in raw or "－" in raw or "-" in raw:
            return "score"
        if b >= 10:
            return "clock"
        return "score"
    return "reject"


def parse_score_candidates(text: str) -> Dict[str, Any]:
    """Parse OCR text into score/clock/other; never invent."""
    raw = (text or "").strip()
    clocks: List[str] = []
    scores: List[Tuple[int, int]] = []
    rejected: List[str] = []
    norm = raw.replace("：", ":")
    for m in _CLOCK.finditer(norm):
        clocks.append(f"{m.group(1)}:{m.group(2)}")
    for rx in (_SCORE_PAIR, _SCORE_PAIR_LOOSE, _STACKED, _CJK_SCORE):
        for m in rx.finditer(raw):
            a, b = int(m.group(1)), int(m.group(2))
            kind = classify_numeric_pair(a, b, raw=m.group(0))
            if kind == "score":
                if (a, b) not in scores:
                    scores.append((a, b))
            elif kind == "clock":
                clocks.append(f"{a}:{b}")
            else:
                rejected.append(f"{a}:{b}")
    for m in _LATIN_SCORE.finditer(raw):
        a, b = int(m.group(2)), int(m.group(3))
        if a <= 9 and b <= 9 and (a, b) not in scores:
            scores.append((a, b))
    for m in re.finditer(r"(?<!\d)([0-9])[ \t]*[Vv][ \t]*([0-9])(?!\d)", raw):
        a, b = int(m.group(1)), int(m.group(2))
        if (a, b) not in scores and a <= 9 and b <= 9:
            scores.append((a, b))
    for line in raw.splitlines():
        line_n = line.strip().replace("V", ":").replace("v", ":").replace("|", ":").replace("｜", ":")
        if _CLOCK.fullmatch(line_n.replace("：", ":")):
            continue
        ps = parse_score(line_n)
        if ps and ps not in scores and ps[0] <= 9 and ps[1] <= 9:
            scores.append(ps)
    if clocks and scores:
        scores = [s for s in scores if f"{s[0]}:{s[1]}" not in clocks]
    return {"raw": raw[:120], "scores": scores, "clocks": clocks, "rejected": rejected[:8]}


_OCR_STATS = {"calls": 0, "sec": 0.0}


def ocr_stats_reset() -> None:
    _OCR_STATS["calls"] = 0
    _OCR_STATS["sec"] = 0.0


def ocr_stats() -> Dict[str, Any]:
    return dict(_OCR_STATS)


def ocr_tesseract_once(
    img: np.ndarray,
    *,
    psm: str = "7",
    lang: str = "eng+chi_sim",
    whitelist: Optional[str] = None,
) -> str:
    """Single tesseract invocation."""
    import cv2

    tess = _require_tesseract()
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    if max(gray.shape) < 400:
        gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="sb_ocr_") as td:
        png = Path(td) / "roi.png"
        cv2.imwrite(str(png), gray)
        cmd = [tess, str(png), "stdout", "-l", lang, "--psm", psm, "--dpi", "200"]
        if whitelist:
            cmd.extend(["-c", f"tessedit_char_whitelist={whitelist}"])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=20)
        if proc.returncode != 0 and "Error" in (proc.stderr or "") and lang != "eng":
            cmd[4] = "eng"
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=20)
        _OCR_STATS["calls"] += 1
        _OCR_STATS["sec"] += time.time() - t0
        return (proc.stdout or "").strip()


def ocr_digits_only(crop_bgr: np.ndarray) -> str:
    import cv2

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    return ocr_tesseract_once(up, psm="6", lang="eng", whitelist="0123456789:Vv-| ")


def find_digit_pair_blobs(crop_bgr: np.ndarray) -> Optional[Tuple[int, int]]:
    """Find two similar-sized high-contrast digit-like blobs (score boxes)."""
    import cv2

    if crop_bgr.size == 0:
        return None
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # try both polarities
    for inv in (False, True):
        g = 255 - gray if inv else gray
        _, thr = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(thr, connectivity=8)
        cands = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < 20 or bw < 3 or bh < 8:
                continue
            aspect = bh / max(1, bw)
            if aspect < 1.0 or aspect > 4.5:
                continue
            if bw > w * 0.35 or bh > h * 0.85:
                continue
            # digit-like: taller than wide
            roi = g[y : y + bh, x : x + bw]
            # OCR single blob
            text = ocr_tesseract_once(roi, psm="10")
            m = re.search(r"([0-9])", text or "")
            if not m:
                continue
            cands.append((x, y, bw, bh, int(m.group(1))))
        # pair horizontally close, similar height
        cands.sort(key=lambda c: c[0])
        best = None
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                a, b = cands[i], cands[j]
                if abs(a[3] - b[3]) > max(a[3], b[3]) * 0.45:
                    continue
                gap = b[0] - (a[0] + a[2])
                if gap < -5 or gap > max(a[2], b[2]) * 4:
                    continue
                if abs(a[1] - b[1]) > max(a[3], b[3]) * 0.6:
                    continue
                best = (a[4], b[4])
                break
            if best:
                break
        if best and best[0] <= 9 and best[1] <= 9:
            return best
    return None


def _prep_variants(crop_bgr: np.ndarray) -> List[np.ndarray]:
    import cv2

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return [up, 255 - up]


def scoreboard_presence_score(crop_bgr: np.ndarray) -> float:
    """Heuristic: graphics overlays tend to have flat color + sharp edges."""
    import cv2

    if crop_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 150)
    edge_dens = float(edges.mean()) / 255.0
    # color flatness in HSV V channel variance (lower = flatter panel)
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    v_std = float(hsv[:, :, 2].std()) / 255.0
    # prefer moderate edges + not too noisy
    return round(edge_dens * 2.0 - abs(v_std - 0.25), 4)


def read_roi(
    frame_bgr: np.ndarray,
    roi: RoiBox,
    *,
    save_crop_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """OCR one ROI; one observation (variants merged, not counted separately)."""
    crop = roi.crop(frame_bgr)
    if save_crop_path is not None:
        import cv2

        save_crop_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(save_crop_path), crop)
    presence = scoreboard_presence_score(crop)
    texts: List[str] = []
    all_scores: Counter = Counter()
    clocks: List[str] = []
    variants = _prep_variants(crop)
    # Try psm 6 (block) then 7; both polarities; stop when a score appears.
    for var in variants:
        for psm in ("6", "7"):
            text = ocr_tesseract_once(var, psm=psm)
            if not text:
                continue
            texts.append(text)
            parsed = parse_score_candidates(text)
            for sc in parsed["scores"]:
                all_scores[sc] += 1
            clocks.extend(parsed["clocks"])
            if all_scores:
                break
        if all_scores:
            break
    # Bottom banners: digits-only middle strip only if text looks like TEAM..TEAM without scores.
    joined = "\n".join(texts)
    if (
        not all_scores
        and roi.name.startswith("bot")
        and re.search(r"[A-Z]{3,}", joined)
        and re.search(r"[A-Z]{3,}", joined[joined.find(re.findall(r"[A-Z]{3,}", joined)[0]) + 3 :])
    ):
        h, w = crop.shape[:2]
        mid = crop[int(h * 0.15) : int(h * 0.70), int(w * 0.35) : int(w * 0.65)]
        digit_txt = ocr_digits_only(mid)
        texts.append(f"digits:{digit_txt}")
        parsed = parse_score_candidates(digit_txt)
        for sc in parsed["scores"]:
            all_scores[sc] += 1
        # accept ONLY clean two-digit-only strings (no jersey times)
        if not all_scores and digit_txt and re.fullmatch(r"[\s:Vv\-|]*\d[\s:Vv\-|]+\d[\s:Vv\-|]*", digit_txt.strip()):
            ds = re.findall(r"\d", digit_txt)
            if len(ds) == 2:
                a, b = int(ds[0]), int(ds[1])
                if a <= 9 and b <= 9:
                    all_scores[(a, b)] += 1
    status = "unknown"
    score = None
    score_tuple = None
    conf = 0.0
    if len(all_scores) >= 2:
        status = "conflict"
    elif len(all_scores) == 1:
        (best, n) = all_scores.most_common(1)[0]
        score_tuple = best
        score = f"{best[0]}:{best[1]}"
        conf = 0.55 if n >= 1 else 0.0
        status = "ok" if conf >= 0.5 else "weak"
    elif clocks and not all_scores:
        status = "clock_only"
    return {
        "roi": roi.to_dict(),
        "presence": presence,
        "status": status,
        "score": score,
        "score_tuple": score_tuple,
        "confidence": conf,
        "raw_texts": [t[:80] for t in texts[:3]],
        "clocks": clocks[:4],
        "votes": {f"{a}:{b}": c for (a, b), c in all_scores.items()},
        "crop_path": str(save_crop_path) if save_crop_path else None,
    }


def detect_and_read_scoreboard(
    frame_bgr: np.ndarray,
    *,
    tracked_roi: Optional[RoiBox] = None,
    evidence_dir: Optional[Path] = None,
    t_sec: float = 0.0,
    max_rois: int = 4,
) -> Dict[str, Any]:
    """Locate scoreboard candidates and read score once per frame.

    Multiple preprocess variants on the same ROI merge into ONE observation.
    """
    rois: List[RoiBox] = []
    if tracked_roi is not None:
        rois.append(tracked_roi)
        # slight neighborhood expansion
        r = tracked_roi
        pad = 0.02
        rois.append(
            RoiBox(
                "track_pad",
                max(0.0, r.x0 - pad),
                max(0.0, r.y0 - pad),
                min(1.0, r.x1 + pad),
                min(1.0, r.y1 + pad),
            )
        )
    # If tracking: only search tracked + pad (fast path). Else rank grid.
    if tracked_roi is not None and len(rois) >= 1:
        search_rois = rois[:2]
    else:
        ranked: List[Tuple[float, RoiBox]] = []
        for box in candidate_roi_grid():
            ranked.append((scoreboard_presence_score(box.crop(frame_bgr)), box))
        ranked.sort(key=lambda x: x[0], reverse=True)
        search_rois = list(rois)
        for _, box in ranked[:max_rois]:
            if all(box.name != r.name for r in search_rois):
                search_rois.append(box)

    readings: List[Dict[str, Any]] = []
    for i, roi in enumerate(search_rois[: max_rois + 2]):
        crop_path = None
        if evidence_dir is not None and i < 3:
            crop_path = evidence_dir / f"t{t_sec:08.1f}_{roi.name}.jpg"
        readings.append(read_roi(frame_bgr, roi, save_crop_path=crop_path))
        # early stop once a high-presence ROI yields a clean score
        if readings[-1]["status"] in ("ok", "weak") and (readings[-1].get("presence") or 0) > 0.05:
            if tracked_roi is not None or i >= 2:
                break

    score_hits = [r for r in readings if r["status"] in ("ok", "weak")]
    conflict_hits = [r for r in readings if r["status"] == "conflict"]
    best_roi = None
    if score_hits:
        score_hits.sort(key=lambda r: (r.get("confidence") or 0, r.get("presence") or 0), reverse=True)
        chosen = score_hits[0]
        best_roi = RoiBox(**chosen["roi"])
        uniq = {r["score"] for r in score_hits if r.get("score")}
        if len(uniq) > 1:
            return {
                "status": "conflict",
                "score": None,
                "score_tuple": None,
                "confidence": 0.0,
                "tracked_roi": best_roi.to_dict() if best_roi else None,
                "scoreboard_detected": True,
                "readings": readings,
                "candidates": sorted(uniq),
            }
        return {
            "status": chosen["status"],
            "score": chosen["score"],
            "score_tuple": chosen["score_tuple"],
            "confidence": chosen["confidence"],
            "tracked_roi": best_roi.to_dict(),
            "scoreboard_detected": True,
            "readings": readings,
            "raw_texts": chosen.get("raw_texts"),
        }
    if conflict_hits:
        return {
            "status": "conflict",
            "score": None,
            "score_tuple": None,
            "confidence": 0.0,
            "tracked_roi": None,
            "scoreboard_detected": True,
            "readings": readings,
        }
    clock_only = any(r["status"] == "clock_only" for r in readings)
    return {
        "status": "clock_only" if clock_only else "unknown",
        "score": None,
        "score_tuple": None,
        "confidence": 0.0,
        "tracked_roi": tracked_roi.to_dict() if tracked_roi else None,
        "scoreboard_detected": any((r.get("presence") or 0) > 0.08 for r in readings),
        "readings": readings,
    }


def update_tracked_roi(
    history: Sequence[Dict[str, Any]],
    *,
    min_hits: int = 3,
) -> Optional[RoiBox]:
    """Pick ROI that most often produced ok scores."""
    votes: Counter = Counter()
    boxes: Dict[str, RoiBox] = {}
    for obs in history:
        if obs.get("status") not in ("ok", "weak"):
            continue
        tr = obs.get("tracked_roi")
        if not tr:
            continue
        key = f"{tr['x0']:.2f}_{tr['y0']:.2f}_{tr['x1']:.2f}_{tr['y1']:.2f}"
        votes[key] += 1
        boxes[key] = RoiBox(tr.get("name") or "tracked", tr["x0"], tr["y0"], tr["x1"], tr["y1"])
    if not votes:
        return None
    key, n = votes.most_common(1)[0]
    if n < min_hits:
        return None
    return boxes[key]
