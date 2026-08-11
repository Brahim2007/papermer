from experiments.analyze_citation_graph import analyze_graph


def test_analyze_graph_reports_internal_and_coupling_coverage(tmp_path):
    graph = tmp_path / "graph.tsv"
    graph.write_text(
        "citing_document_id\tcited_reference_key\tcited_document_id\tsource\n"
        "a\topenalex:W1\tb\topenalex\n"
        "b\topenalex:W1\t\topenalex\n"
        "c\topenalex:W2\t\topenalex\n",
        encoding="utf-8",
    )
    metrics = analyze_graph(graph, document_count=3)

    assert metrics["resolved_internal_edge_count"] == 1
    assert metrics["internal_incident_document_count"] == 2
    assert metrics["largest_weak_component_size"] == 2
    assert metrics["shared_reference_count"] == 1
    assert metrics["bibliographic_coupling_document_count"] == 2
