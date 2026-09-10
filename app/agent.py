import csv
import io
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .models import RunRequest, Step
from .providers import enhance_result

MAX_FILE_BYTES = 2 * 1024 * 1024
REQUIRED = {"review_id", "rating", "title", "body", "country", "date", "verified"}
THEMES = {
    "battery": ["battery", "charge", "charging", "电池", "续航"],
    "comfort": ["comfort", "comfortable", "fit", "舒适", "佩戴"],
    "quality": ["quality", "broke", "broken", "durable", "质量", "损坏"],
    "sound": ["sound", "audio", "noise", "音质", "噪音"],
    "delivery": ["delivery", "shipping", "package", "物流", "包装"],
    "value": ["price", "value", "worth", "价格", "性价比"],
}
IMPROVEMENTS = {
    "battery": "提升续航并明确充电时间与电量提示。",
    "comfort": "优化尺寸与接触材质，补充佩戴尺寸说明。",
    "quality": "加强高频损坏部位并增加出厂检查。",
    "sound": "校准音频表现并说明适用环境。",
    "delivery": "加强运输包装并检查承运商异常。",
    "value": "强化价值证明，避免超出功能证据的定价。",
    "other": "补充样本并人工复核未归类反馈。",
}


def _source(request: RunRequest, base_dir: Path) -> tuple[str, str]:
    if request.example:
        path = base_dir / "samples" / request.example
        if not path.is_file():
            raise ValueError("样例不存在。")
        return path.name, path.read_text(encoding="utf-8-sig")
    if not request.file_name or request.file_content is None:
        raise ValueError("请上传 CSV 或选择内置样例。")
    if not request.file_name.lower().endswith(".csv"):
        raise ValueError("评论洞察仅接受 CSV 文件。")
    if len(request.file_content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("文件超过 2 MB 限制。")
    return request.file_name, request.file_content


def run(request: RunRequest, base_dir: Path) -> dict[str, Any]:
    file_name, content = _source(request, base_dir)
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or not REQUIRED.issubset(set(reader.fieldnames)):
        missing = sorted(REQUIRED - set(reader.fieldnames or []))
        raise ValueError(f"CSV 缺少字段：{', '.join(missing)}")

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, row in enumerate(reader, start=2):
        try:
            rating = int(row["rating"])
            if rating < 1 or rating > 5:
                raise ValueError
        except ValueError:
            warnings.append(f"第 {index} 行评分无效，已跳过。")
            continue
        row["rating"] = rating
        rows.append(row)
    if not rows:
        raise ValueError("没有可分析的有效评论。")

    theme_counts: Counter[str] = Counter()
    pain_counts: Counter[str] = Counter()
    motivation_counts: Counter[str] = Counter()
    quotes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rating_distribution: Counter[int] = Counter()

    for row in rows:
        rating_distribution[row["rating"]] += 1
        text = f"{row['title']} {row['body']}".lower()
        matched = [theme for theme, words in THEMES.items() if any(word in text for word in words)] or ["other"]
        for theme in matched:
            theme_counts[theme] += 1
            if row["rating"] <= 3:
                pain_counts[theme] += 1
            if row["rating"] >= 4:
                motivation_counts[theme] += 1
            if len(quotes[theme]) < 2:
                quotes[theme].append(
                    {"review_id": row["review_id"], "rating": row["rating"], "quote": row["body"][:180]}
                )

    themes = []
    for theme, count in theme_counts.most_common():
        themes.append(
            {
                "theme": theme,
                "mentions": count,
                "pain_mentions": pain_counts[theme],
                "positive_mentions": motivation_counts[theme],
                "evidence": quotes[theme],
            }
        )
    priority = [
        {"theme": theme, "priority": count, "recommendation": IMPROVEMENTS[theme]}
        for theme, count in pain_counts.most_common()
    ]
    positive = [theme for theme, _ in motivation_counts.most_common(3)]
    result = {
        "review_count": len(rows),
        "average_rating": round(sum(row["rating"] for row in rows) / len(rows), 2),
        "rating_distribution": {str(score): rating_distribution[score] for score in range(1, 6)},
        "themes": themes,
        "priority_improvements": priority,
        "listing_angles": [f"Use verified customer interest in {theme} as a listing angle." for theme in positive],
    }
    result, provider, provider_warnings = enhance_result("review insight", result)
    warnings.extend(provider_warnings)
    review_reasons = []
    if len(rows) < 10:
        review_reasons.append("样本少于 10 条，洞察代表性有限。")
    if "other" in theme_counts:
        review_reasons.append("存在未归类主题，建议人工阅读原文。")
    return {
        "input_summary": f"{file_name}：{len(rows)} 条有效评论",
        "steps": [
            Step(name="数据校验", detail=f"读取 {len(rows)} 条有效评论，跳过 {len(warnings) - len(provider_warnings)} 条。"),
            Step(name="主题归类", detail=f"识别 {len(theme_counts)} 个主题。"),
            Step(name="洞察生成", detail="已生成痛点、购买动机和产品建议。"),
        ],
        "evidence": [{"source": file_name, "type": "uploaded_or_sample_csv", "rows": len(rows)}],
        "result": result,
        "warnings": warnings,
        "confidence": round(min(0.95, 0.55 + len(rows) / 100), 2),
        "needs_human_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "model_provider": provider,
    }

