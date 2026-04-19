import csv
import json

CTR_WEIGHT = 0.6
CVR_WEIGHT = 0.4
RECOMMEND_THRESHOLD = 0.75

REQUIRED_FIELDS = {"prompt_asset_id", "ctr", "cvr"}


def import_performance_data(file_path: str, format: str = "csv") -> list[dict]:
    if format == "json":
        with open(file_path, "r") as f:
            data = json.load(f)
        for row in data:
            _validate_row(row)
            row["prompt_asset_id"] = int(row["prompt_asset_id"])
            row["ctr"] = float(row["ctr"])
            row["cvr"] = float(row["cvr"])
        return data

    with open(file_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        data = []
        for row in reader:
            _validate_row(row)
            data.append(
                {
                    "prompt_asset_id": int(row["prompt_asset_id"]),
                    "ctr": float(row["ctr"]),
                    "cvr": float(row["cvr"]),
                }
            )
    return data


def _validate_row(row: dict) -> None:
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise ValueError(f"缺少必要字段: {missing}")


def calculate_performance_score(ctr: float, cvr: float) -> float:
    return CTR_WEIGHT * ctr + CVR_WEIGHT * cvr


def apply_attribution(session, data: list[dict]) -> int:
    from pipeline.models.prompt_asset import PromptAsset
    from sqlalchemy import text

    count = 0
    for row in data:
        asset_id = row["prompt_asset_id"]
        asset = session.query(PromptAsset).get(asset_id)
        if asset is None:
            continue
        score = calculate_performance_score(row["ctr"], row["cvr"])
        session.execute(
            text(
                "UPDATE prompt_assets SET performance_score = :score, "
                "is_recommended = :rec WHERE id = :id"
            ),
            {
                "score": score,
                "rec": 1 if score >= RECOMMEND_THRESHOLD else 0,
                "id": asset_id,
            },
        )
        count += 1
    session.commit()
    return count
