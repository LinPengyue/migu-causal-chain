from story_video_agent_v3.story_phase10f_evaluation import evaluate_cases


def test_balanced_crossmatch_counts():
    cases = [
        {"case_id": "a1", "match_id": "A", "human_label": "NECESSARY", "risk_level": "HIGH_UNVERIFIED"},
        {"case_id": "a2", "match_id": "A", "human_label": "REDUNDANT", "risk_level": "HIGH_UNVERIFIED"},
        {"case_id": "b1", "match_id": "B", "human_label": "NECESSARY", "risk_level": "UNKNOWN"},
        {"case_id": "b2", "match_id": "B", "human_label": "REDUNDANT", "risk_level": "UNKNOWN"},
        {"case_id": "b3", "match_id": "B", "human_label": "UNCERTAIN", "risk_level": "ELEVATED_UNVERIFIED"},
    ]
    result = evaluate_cases(cases)
    assert result["high_risk_confusion"] == {"TP": 1, "FN": 1, "FP": 1, "TN": 1}
    assert result["necessary_recall"] == .5
    assert result["redundant_false_alarm_rate"] == .5
    assert result["uncertain_excluded"] == 1


def test_no_negative_controls_cannot_claim_balanced_evidence():
    result = evaluate_cases([
        {"case_id": "a1", "match_id": "A", "human_label": "NECESSARY", "risk_level": "HIGH_UNVERIFIED"},
        {"case_id": "b1", "match_id": "B", "human_label": "NECESSARY", "risk_level": "HIGH_UNVERIFIED"},
    ])
    assert result["redundant_false_alarm_rate"] is None
    assert result["conclusion"] == "INSUFFICIENT_BALANCED_CROSSMATCH_EVIDENCE"


def test_duplicate_case_rejected():
    case = {"case_id": "same", "match_id": "A", "human_label": "REDUNDANT", "risk_level": "UNKNOWN"}
    result = evaluate_cases([case, case])
    assert len(result["invalid_cases"]) == 1
    assert result["n_cases"] == 1
