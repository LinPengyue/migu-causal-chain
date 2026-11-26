"""Actual video backend using the frozen V3-A native-video and paid API tools.

No model call or decoding occurs at import. Preview rendering is silent
5fps/360p for reasoning, not delivery. Full comparison exceeding the native
payload cap is an explicit limitation, not silently sampled or accepted.
"""
import hashlib
import json
import subprocess
from pathlib import Path
from template_graph import check, number

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

class NativeBackend:
    real_visual=True
    def __init__(self,source,source_manifest,evidence,*,max_calls,max_cost_usd):
        from story_video_agent_v3.story_paid_eval import build_capped_provider
        from story_video_agent_v3.native_broadcast_observer import MAX_CONTEXT_SEC,MAX_VIDEO_BYTES
        from story_video_agent.media import probe_video
        self.source=Path(source).resolve()
        check(source_manifest["video_id"]==evidence["video_id"],"video source mapping mismatch")
        self.source_sha=sha(self.source)
        check(self.source_sha==source_manifest["sha256"],"source video hash mismatch")
        # ffprobe directly checks duration; the historical probe additionally
        # checks that the source is a usable video.
        probe_video(self.source)
        d=subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",str(self.source)],text=True,timeout=30)
        check(abs(float(d)-evidence["duration_sec"])<=2,"source duration differs from evidence")
        self.max_clip_sec=min(40.0,float(MAX_CONTEXT_SEC))
        self.max_bytes=MAX_VIDEO_BYTES
        self.api=build_capped_provider(max_calls=max_calls,max_cost_usd=max_cost_usd,max_completion_tokens=2400)
        self.max_calls=max_calls
    def calls_left(self):
        from story_video_agent_v3.story_first_search import story_first_calls_left
        return story_first_calls_left(self.api)
    def usage(self):
        from story_video_agent_v3.story_paid_eval import provider_usage
        return provider_usage(self.api)
    def query(self,stage,prompt,directory,clips=()):
        from story_video_agent_v3.story_first_p3 import _request
        directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
        check(self.calls_left()>0,"API budget exhausted")
        check(sum(Path(c["path"]).stat().st_size for c in clips)<=self.max_bytes,
              "combined native video payload exceeds cap")
        response=_request(self.api,"vision" if clips else "planner",stage,prompt,directory,
                          clips,stats_prefix="sports_general_agent")
        check(response.get("error") is None and isinstance(response.get("parsed"),dict),
              "model response failed: "+str(response.get("error")))
        return response["parsed"]
    def observe_clip(self,w,out,clip_id):
        from story_video_agent_v3.native_broadcast_observer import _source_context_video
        r=_source_context_video(source_mp4=self.source,begin=w[0],end=w[1],output=Path(out))
        check(r.get("ok"),"native clip extraction failed: "+str(r.get("reason")))
        return {"clip_id":clip_id,"path":r["path"],"sha256":r["sha256"],
                "source_window":list(w),"story_range_sec":list(w),"source_sha256":self.source_sha,
                "method":"single_continuous_source_interval_transcoded_5fps"}
    def render_preview(self,rows,out,clip_id):
        out=Path(out); out.parent.mkdir(parents=True,exist_ok=True)
        d=out.parent/(out.stem+"_parts"); d.mkdir(exist_ok=False)
        parts=[]
        for r in rows:
            lo,hi=r["media_in"],r["media_out"]
            while lo<hi:
                end=min(hi,lo+self.max_clip_sec)
                parts.append(self.observe_clip([lo,end],d/("%04d.mp4"%len(parts)),"part:"+str(len(parts))))
                lo=end
        # All parts use the existing native extractor's identical codec,
        # resolution and fps. Concat list uses generated safe relative names.
        listing=d/"concat.txt"
        listing.write_text("".join("file '%s'\n"%Path(x["path"]).name for x in parts),encoding="utf-8")
        run=subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat",
            "-safe","1","-i",str(listing),"-c","copy","-movflags","+faststart",str(out)],
            capture_output=True,text=True,timeout=180)
        check(run.returncode==0 and out.is_file(),"preview concat failed")
        check(out.stat().st_size<=self.max_bytes,"complete preview exceeds native video cap")
        duration=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",str(out)],text=True,timeout=30))
        expected=sum(r["media_out"]-r["media_in"] for r in rows)
        check(abs(duration-expected)<=max(0.5,0.25*len(parts)),"preview duration mismatch")
        return {"clip_id":clip_id,"path":str(out),"sha256":sha(out),"source_sha256":self.source_sha,
                "story_range_sec":[0,duration],"source_parts":parts,"expected_duration":expected,
                "method":"complete_silent_5fps_preview_not_delivery"}
