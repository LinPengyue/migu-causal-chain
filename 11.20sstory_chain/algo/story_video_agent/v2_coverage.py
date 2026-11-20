"""Search coverage: requested vs sampled vs observed vs failed (Phase B)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


class SearchCoverage:
    def __init__(self, *, duration_sec: float, partition_sec: float = 600.0) -> None:
        self.duration_sec = float(duration_sec)
        self.partition_sec = float(partition_sec)
        self.records: List[Dict[str, Any]] = []

    def add(
        self,
        *,
        tool: str,
        requested_start: Optional[float],
        requested_end: Optional[float],
        sampled_times: Optional[Sequence[float]] = None,
        observed: bool = False,
        failed: bool = False,
        sparse_note: str = "",
        frame_ids: Optional[Sequence[str]] = None,
        error: Optional[str] = None,
    ) -> None:
        sampled = [float(t) for t in (sampled_times or [])]
        span = None
        if requested_start is not None and requested_end is not None:
            span = max(0.0, float(requested_end) - float(requested_start))
        density = None
        if span and span > 0 and sampled:
            density = len(sampled) / span
        self.records.append(
            {
                "tool": tool,
                "requested_start": requested_start,
                "requested_end": requested_end,
                "requested_span_sec": span,
                "sampled_media_times": sampled,
                "n_sampled": len(sampled),
                "frame_ids": list(frame_ids or []),
                "observed": bool(observed),
                "failed": bool(failed),
                "error": error,
                "sparse_note": sparse_note
                or (
                    "sparse_samples_do_not_mean_full_interval_was_watched"
                    if tool in ("global_overview", "overview", "partition_scan", "scan_interval")
                    else ""
                ),
                "sample_density_per_sec": density,
            }
        )

    def partition_plan(self) -> List[Dict[str, float]]:
        parts: List[Dict[str, float]] = []
        t = 0.0
        i = 0
        while t < self.duration_sec - 1e-6:
            end = min(self.duration_sec, t + self.partition_sec)
            parts.append({"index": i, "start": round(t, 3), "end": round(end, 3)})
            t = end
            i += 1
        return parts

    @staticmethod
    def _is_sparse_global(tool: str) -> bool:
        return tool in ("global_overview", "overview")

    def partition_coverage(self) -> List[Dict[str, Any]]:
        """Partition 'observed' requires a non-overview tool hit (scan/localize/verify).

        Sparse global overview may deposit samples inside a partition but must NOT mark
        the whole partition as fully observed.
        """
        parts = self.partition_plan()
        out = []
        for p in parts:
            hits = [
                r
                for r in self.records
                if r.get("requested_start") is not None
                and not (
                    float(r["requested_end"]) <= p["start"]
                    or float(r["requested_start"]) >= p["end"]
                )
            ]
            local_hits = [h for h in hits if not self._is_sparse_global(str(h.get("tool") or ""))]
            overview_hits = [h for h in hits if self._is_sparse_global(str(h.get("tool") or ""))]
            observed = any(h.get("observed") for h in local_hits)
            failed_only = bool(local_hits) and all(h.get("failed") for h in local_hits)
            sampled_n = sum(int(h.get("n_sampled") or 0) for h in local_hits)
            overview_samples_in = 0
            for h in overview_hits:
                for t in h.get("sampled_media_times") or []:
                    if p["start"] <= float(t) < p["end"]:
                        overview_samples_in += 1
            if observed:
                status = "observed"
            elif failed_only:
                status = "failed_only"
            elif local_hits:
                status = "requested"
            elif overview_samples_in:
                status = "overview_sparse_only"
            else:
                status = "untouched"
            out.append(
                {
                    **p,
                    "n_tool_hits": len(hits),
                    "n_local_tool_hits": len(local_hits),
                    "any_observed": observed,
                    "failed_only": failed_only,
                    "n_sampled_frames": sampled_n,
                    "overview_sparse_samples_in_partition": overview_samples_in,
                    "status": status,
                }
            )
        return out

    def summary(self) -> Dict[str, Any]:
        parts = self.partition_coverage()
        n = len(parts) or 1
        return {
            "schema": "v2_search_coverage_v1",
            "duration_sec": self.duration_sec,
            "partition_sec": self.partition_sec,
            "n_records": len(self.records),
            "n_partitions": len(parts),
            "partitions_observed": sum(1 for p in parts if p["status"] == "observed"),
            "partitions_untouched": sum(1 for p in parts if p["status"] == "untouched"),
            "partitions_overview_sparse_only": sum(
                1 for p in parts if p["status"] == "overview_sparse_only"
            ),
            "partitions_failed_only": sum(1 for p in parts if p["status"] == "failed_only"),
            "fraction_partitions_with_observation": round(
                sum(1 for p in parts if p["status"] == "observed") / n, 4
            ),
            "disclaimer": (
                "Sparse overview samples do not mark partitions as observed. "
                "Partition observation requires scan/localize/verify (or scoreboard) tools. "
                "Untouched partitions remain unknown."
            ),
            "records": self.records,
            "partitions": parts,
        }
