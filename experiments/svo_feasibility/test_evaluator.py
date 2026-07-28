from experiments.svo_feasibility.evaluator import evaluate_predictions, evaluate_sample_files


def test_evaluate_predictions_penalizes_wrong_relation_and_missing_evidence():
    gold = [
        {
            "subject": "RAG",
            "rel_type": "RETRIEVES",
            "object": "source passages",
            "evidence_doc_id": "doc1",
            "evidence_sentence_ids": ["s1"],
        },
        {
            "subject": "GraphRAG",
            "rel_type": "RETURNS_EVIDENCE",
            "object": "source text",
            "evidence_doc_id": "doc1",
            "evidence_sentence_ids": ["s2"],
        },
    ]
    predicted = [
        {
            "subject": "RAG",
            "rel_type": "RETRIEVES",
            "object": "source passages",
            "evidence_doc_id": "doc1",
            "evidence_sentence_ids": ["s1"],
        },
        {
            "subject": "GraphRAG",
            "rel_type": "RETRIEVES",
            "object": "source text",
            "evidence_doc_id": "doc1",
            "evidence_sentence_ids": ["s2"],
        },
    ]

    score = evaluate_predictions(gold, predicted, system_name="candidate")

    assert score.true_positive == 1
    assert score.false_positive == 1
    assert score.false_negative == 1
    assert score.precision == 0.5
    assert score.recall == 0.5
    assert score.f1 == 0.5
    assert score.traceability == 1.0


def test_sample_files_show_verified_svo_as_best_structured_result():
    scores = {score.system: score for score in evaluate_sample_files()}

    assert scores["pure_rag_proxy"].f1 == 0.0
    assert scores["unverified_svo"].f1 < scores["verified_svo"].f1
    assert scores["unverified_svo"].traceability < scores["verified_svo"].traceability
    assert scores["verified_svo"].precision == 1.0
    assert scores["verified_svo"].recall == 1.0
    assert scores["verified_svo"].traceability == 1.0
