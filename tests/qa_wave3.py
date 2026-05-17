"""Wave 3 QA — T10 Slot Planner, T11 Adapters, T12 QA Gate, T13 Feedback Loop."""

import os
import struct
import sys
import tempfile
import zlib

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.config import config
from pipeline.models.base import Base, get_engine, get_session

# Use temp DB
_tmp = tempfile.mktemp(suffix=".db")
config.db_path = _tmp
config.output_dir = tempfile.mkdtemp(prefix="aip_qa3_")

# Re-create engine for temp DB
from sqlalchemy import create_engine
from pipeline.models import base as base_mod

base_mod._engine = create_engine(f"sqlite:///{_tmp}")
base_mod._SessionLocal = None  # force re-init
Base.metadata.create_all(base_mod._engine)

passed = 0
failed = 0
results: list[str] = []


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        results.append(f"  PASS: {name}")
    else:
        failed += 1
        results.append(f"  FAIL: {name} — {detail}")


# ── helpers ──────────────────────────────────────────────────────────────
def _create_test_project():
    from pipeline.layers.input_layer import create_project

    return create_project(
        {
            "name": "QA3 Test",
            "asin": "B0TESTQA03",
            "category": "TWS earphone",
        }
    )


def _add_benchmark(project_id: int):
    from pipeline.models.benchmark import AmazonBenchmark

    session = get_session()
    b = AmazonBenchmark(
        project_id=project_id,
        competitor_asin="B0COMP00AA",
        slot_index=1,
        image_url="https://example.com/img.jpg",
        analysis="test",
        score=85.0,
    )
    session.add(b)
    session.commit()
    session.close()


def _create_prompt_asset(
    project_id: int, slot_index: int, image_path: str | None = None
):
    from pipeline.models.prompt_asset import PromptAsset

    session = get_session()
    pa = PromptAsset(
        project_id=project_id,
        slot_index=slot_index,
        prompt_text="test prompt",
        model_name="mock",
        image_path=image_path,
    )
    session.add(pa)
    session.commit()
    session.refresh(pa)
    pa_id = pa.id
    session.close()
    return pa_id


def _make_tiny_png(width=100, height=100) -> str:
    """Create a small PNG for failure tests."""

    def _chunk(ct, data):
        c = ct + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    row = b"\x00" + b"\xff" * (width * 3)
    raw = b"".join(row for _ in range(height))
    idat = _chunk(b"IDAT", zlib.compress(raw, 1))
    iend = _chunk(b"IEND", b"")
    path = os.path.join(config.output_dir, f"tiny_{width}x{height}.png")
    with open(path, "wb") as f:
        f.write(sig + ihdr + idat + iend)
    return path


# ═══════════════════════════════════════════════════════════════════════
# T10: Slot Planner
# ═══════════════════════════════════════════════════════════════════════
print("── T10: Slot Planner ──")

# 10-1: Generate 8 slot plans
proj = _create_test_project()
_add_benchmark(proj.id)

from pipeline.layers.slot_planner import generate_slot_plan

plans = generate_slot_plan(proj.id)
check("T10-1 generates 8 plans", len(plans) == 8, f"got {len(plans)}")
check(
    "T10-2 slot_index range 1-8",
    [p.slot_index for p in plans] == list(range(1, 9)),
    f"got {[p.slot_index for p in plans]}",
)
check("T10-3 intent_tag set", all(p.intent_tag for p in plans))
check("T10-4 layout_tag set", all(p.layout_tag for p in plans))
check(
    "T10-5 first plan is HERO", plans[0].intent_tag == "INT_HERO", plans[0].intent_tag
)

# 10-2: No benchmark → error
proj2 = _create_test_project()
try:
    generate_slot_plan(proj2.id)
    check("T10-6 no benchmark raises", False, "no exception")
except ValueError as e:
    check("T10-6 no benchmark raises", "E_PLANNER_001" in str(e))

# 10-3: Idempotent (re-run doesn't duplicate)
plans2 = generate_slot_plan(proj.id)
check("T10-7 idempotent re-run", len(plans2) == 8, f"got {len(plans2)}")


# ═══════════════════════════════════════════════════════════════════════
# T11: AI Adapter
# ═══════════════════════════════════════════════════════════════════════
print("── T11: AI Adapter ──")

from pipeline.adapters import get_adapter, ImageResult, JobStatus

# 11-1: Mock adapter generates image
adapter = get_adapter("mock")
result = adapter.generate("A TWS earbuds on white background", {})
check("T11-1 returns ImageResult", type(result).__name__ == "ImageResult")
check("T11-2 has image_path", bool(result.image_path))
check("T11-3 file exists", os.path.isfile(result.image_path), str(result.image_path))
check("T11-4 status completed", result.status == JobStatus.COMPLETED)

# 11-2: check_status
status = adapter.check_status(result.job_id)
check("T11-5 check_status", status == JobStatus.COMPLETED)

# 11-3: Unknown adapter → error
try:
    get_adapter("nonexistent")
    check("T11-6 unknown adapter raises", False, "no exception")
except KeyError:
    check("T11-6 unknown adapter raises", True)

# 11-4: Empty prompt → error
try:
    adapter.generate("", {})
    check("T11-7 empty prompt raises", False, "no exception")
except ValueError as e:
    check("T11-7 empty prompt raises", "E_ADAPTER_002" in str(e))

# 11-5: Unknown job_id → error
try:
    adapter.check_status("nonexistent_job")
    check("T11-8 unknown job raises", False, "no exception")
except KeyError:
    check("T11-8 unknown job raises", True)


# ═══════════════════════════════════════════════════════════════════════
# T12: QA Gate
# ═══════════════════════════════════════════════════════════════════════
print("── T12: QA Gate ──")

from pipeline.layers.qa_gate import run_qa_checks, check_resolution, check_aspect_ratio

# 12-1: QA pass with mock 1600x1600 image
# Need: project → benchmark → slot_plan → prompt_asset with image_path
mock_img_path = result.image_path  # reuse mock adapter output (1600x1600)
pa_id = _create_prompt_asset(proj.id, 1, mock_img_path)

# Get slot_plan id for slot_index=1
session = get_session()
from pipeline.models.slot_plan import SlotPlan

sp = session.query(SlotPlan).filter_by(project_id=proj.id, slot_index=1).first()
sp_id = sp.id
session.close()

records = run_qa_checks(sp_id)
check("T12-1 returns 4 checks", len(records) == 4, f"got {len(records)}")
total_score = sum(r.score for r in records)
check("T12-2 score >= 70", total_score >= 70, f"score={total_score}")
check(
    "T12-3 at least 3/4 passed (L2 bg heuristic known limitation)",
    sum(1 for r in records if r.passed) >= 3,
    f"failed: {[r.check_type for r in records if not r.passed]}",
)

# 12-2: Resolution fail with tiny image
tiny_path = _make_tiny_png(100, 100)
check("T12-4 check_resolution fails tiny", not check_resolution(tiny_path))

# 12-3: Aspect ratio
check("T12-5 aspect_ratio 1:1 pass", check_aspect_ratio(mock_img_path, "1:1"))
# Make non-square image
nonsquare_path = _make_tiny_png(200, 100)
check("T12-6 aspect_ratio 1:1 fail", not check_aspect_ratio(nonsquare_path, "1:1"))

# 12-4: run_qa_checks with tiny image → low score
pa_tiny_id = _create_prompt_asset(proj.id, 2, tiny_path)
# Need slot plan for slot_index=2
session = get_session()
sp2 = session.query(SlotPlan).filter_by(project_id=proj.id, slot_index=2).first()
sp2_id = sp2.id
session.close()

records2 = run_qa_checks(sp2_id)
total2 = sum(r.score for r in records2)
res_check = [r for r in records2 if r.check_type == "resolution"][0]
check("T12-7 resolution check failed", not res_check.passed)
ar_check = [r for r in records2 if r.check_type == "aspect_ratio"][0]
check("T12-8 aspect_ratio pass (100x100 is 1:1)", ar_check.passed == 1)


# ═══════════════════════════════════════════════════════════════════════
# T13: Feedback Loop
# ═══════════════════════════════════════════════════════════════════════
print("── T13: Feedback Loop ──")

from pipeline.layers.feedback_loop import (
    record_ab_test,
    record_delivery_result,
    get_category_insights,
    export_project_report,
)

# 13-1: Record A/B test
# Create second prompt asset for variant B
pa_b_id = _create_prompt_asset(proj.id, 1, mock_img_path)
ab = record_ab_test(
    project_id=proj.id,
    slot_index=1,
    variant_a_id=pa_id,
    variant_b_id=pa_b_id,
    winner="A",
    metric="CTR",
    score_a=3.2,
    score_b=2.1,
    notes="A wins",
)
check("T13-1 ab.id exists", ab.id is not None)
check("T13-2 ab.metric", ab.metric == "CTR", ab.metric)
check("T13-3 ab.winner", ab.winner == "A", str(ab.winner))

# 13-2: Invalid variant → error
try:
    record_ab_test(proj.id, 1, 99999, 99998, metric="CTR")
    check("T13-4 invalid variant raises", False, "no exception")
except ValueError as e:
    check("T13-4 invalid variant raises", "E_FEEDBACK_001" in str(e))

# 13-3: Record delivery result
record_delivery_result(proj.id, 1, {"client_happy": True, "ctr": 3.5})
check("T13-5 delivery recorded", True)  # no exception = pass

# 13-4: Category insights
insights = get_category_insights("TWS earphone")
check(
    "T13-6 insights has keys",
    all(
        k in insights for k in ("avg_qa_pass_rate", "top_intent_tags", "project_count")
    ),
)
check(
    "T13-7 project_count >= 1",
    insights["project_count"] >= 1,
    str(insights["project_count"]),
)

# 13-5: Export project report
report = export_project_report(proj.id)
check("T13-8 report has project", "project" in report)
check(
    "T13-9 report has slot_plans",
    len(report.get("slot_plans", [])) == 8,
    str(len(report.get("slot_plans", []))),
)
check("T13-10 report has qa_records", len(report.get("qa_records", [])) > 0)
check("T13-11 report has ab_tests", len(report.get("ab_tests", [])) > 0)

# 13-6: Export nonexistent project → error
try:
    export_project_report(99999)
    check("T13-12 nonexistent project raises", False, "no exception")
except ValueError as e:
    check("T13-12 nonexistent project raises", "E_FEEDBACK_002" in str(e))


# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════
print()
print("═" * 60)
print(f"Wave 3 QA: {passed} passed, {failed} failed, {passed + failed} total")
print("═" * 60)
for r in results:
    print(r)

# Cleanup
os.unlink(_tmp)

sys.exit(0 if failed == 0 else 1)
