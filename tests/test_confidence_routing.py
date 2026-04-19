"""置信度评分路由测试 — TDD RED→GREEN→REFACTOR"""

from pipeline.orchestrator import _route_by_confidence


class TestRouteByConfidence:
    """三段路由：高≥80→pass，50≤score<80→retry_alt_prompt，<50→human_review"""

    # --- 典型值 ---
    def test_high_score_pass(self):
        assert _route_by_confidence(85) == "pass"

    def test_mid_score_retry(self):
        assert _route_by_confidence(65) == "retry_alt_prompt"

    def test_low_score_human_review(self):
        assert _route_by_confidence(30) == "human_review"

    # --- 边界值 ---
    def test_boundary_80_pass(self):
        assert _route_by_confidence(80.0) == "pass"

    def test_boundary_79_9_retry(self):
        assert _route_by_confidence(79.9) == "retry_alt_prompt"

    def test_boundary_50_retry(self):
        assert _route_by_confidence(50.0) == "retry_alt_prompt"

    def test_boundary_49_9_human_review(self):
        assert _route_by_confidence(49.9) == "human_review"

    # --- 极端值 ---
    def test_score_100(self):
        assert _route_by_confidence(100) == "pass"

    def test_score_0(self):
        assert _route_by_confidence(0) == "human_review"
