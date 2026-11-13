import json
import pytest
from story_video_agent_v3.expb_offline_evidence_review import extract_complete_objects, review, sha256_file


def test_truncated_json_preserves_complete_duplicates_without_repair():
    s = '{"observations":[{"phase":"IMMEDIATE_CELEBRATION","frame_id":"a"},' \
        '{"phase":"IMMEDIATE_CELEBRATION","frame_id":"b"},' \
        '{"phase":"LATER_SAME_ACTION_REPLAY","visible_cue":"unfinished'
    rows = extract_complete_objects(s)
    assert len(rows) == 2
    assert [x["frame_id"] for x in rows] == ["a", "b"]


def test_no_observations_or_partial_first_object():
    assert extract_complete_objects("not json") == []
    assert extract_complete_objects('{"observations":[{"phase":') == []


def test_offline_review_preserves_model_only_and_zero_http(tmp_path):
    from PIL import Image
    img = tmp_path / "a.jpg"
    Image.new("RGB", (32, 32), "white").save(img)
    manifest = tmp_path / "frames.json"
    manifest.write_text(json.dumps({
        "source_sha256": "source",
        "image_frames": [{
            "frame_id": "a", "path": str(img), "sha256": sha256_file(img),
            "actual_media_sec": 12.3,
        }],
    }))
    response = tmp_path / "raw.txt"
    response.write_text('{"observations":[{"phase":"ACTIVE_PLAY_BEFORE","frame_id":"a",'
                        '"source_pts_sec":12.3,"visible_cue":"Players moving on pitch"},'
                        '{"phase":"LATER_SAME_ACTION_REPLAY","frame_id":"a"')
    result = review(response=response, frames_manifest=manifest, source_sha="source",
                    out_dir=tmp_path / "out")
    assert result["n_complete_observations"] == 1
    assert result["observations"][0]["citation_valid"]
    assert result["observations"][0]["visual_truth_verified"] is False
    assert result["first_live_verified"] is False
    assert result["api_calls"] == 0
    assert (tmp_path / "out" / "contact_sheet.jpg").exists()


def test_rejects_changed_frame(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"wrong")
    manifest = tmp_path / "frames.json"
    manifest.write_text(json.dumps({"source_sha256": "source", "image_frames": [
        {"frame_id": "a", "path": str(img), "sha256": "0" * 64,
         "actual_media_sec": 12.3}]}))
    response = tmp_path / "raw.txt"
    response.write_text('{"observations":[]}')
    with pytest.raises(ValueError, match="changed_frame"):
        review(response=response, frames_manifest=manifest, source_sha="source",
               out_dir=tmp_path / "out")
