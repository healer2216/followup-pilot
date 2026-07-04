"""
指标趋势分析引擎

功能：
1. 5 类趋势方向识别（改善/稳定/恶化/波动/数据不足）
2. 5 条升级规则（连续恶化、突破阈值、波动加大等）
3. 线性外推预测（预测下一次指标值）
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from app.models import TrendDirection, AlertLevel


# ============================================================================
# 指标元数据（正常范围、理想方向）
# ============================================================================

METRIC_META = {
    "fasting_glucose": {
        "label": "空腹血糖",
        "unit": "mmol/L",
        "normal_low": 4.4,
        "normal_high": 7.0,
        "danger_high": 13.9,
        "danger_low": 3.9,
        "ideal_direction": "decreasing",   # 高时希望下降
    },
    "postprandial_glucose": {
        "label": "餐后血糖",
        "unit": "mmol/L",
        "normal_low": 4.4,
        "normal_high": 10.0,
        "danger_high": 16.7,
        "danger_low": 3.9,
        "ideal_direction": "decreasing",
    },
    "blood_pressure_systolic": {
        "label": "收缩压",
        "unit": "mmHg",
        "normal_low": 90,
        "normal_high": 140,
        "danger_high": 180,
        "danger_low": 80,
        "ideal_direction": "decreasing",
    },
    "blood_pressure_diastolic": {
        "label": "舒张压",
        "unit": "mmHg",
        "normal_low": 60,
        "normal_high": 90,
        "danger_high": 110,
        "danger_low": 50,
        "ideal_direction": "decreasing",
    },
    "heart_rate": {
        "label": "心率",
        "unit": "次/分",
        "normal_low": 60,
        "normal_high": 100,
        "danger_high": 130,
        "danger_low": 50,
        "ideal_direction": "stable",
    },
    "weight": {
        "label": "体重",
        "unit": "kg",
        "normal_low": 40,
        "normal_high": 120,
        "danger_high": 200,
        "danger_low": 30,
        "ideal_direction": "stable",
    },
    "temperature": {
        "label": "体温",
        "unit": "℃",
        "normal_low": 36.0,
        "normal_high": 37.3,
        "danger_high": 39.0,
        "danger_low": 35.0,
        "ideal_direction": "stable",
    },
}


# ============================================================================
# 趋势分析结果
# ============================================================================

class TrendResult:
    """单个指标的趋势分析结果"""

    def __init__(self, metric_key: str):
        meta = METRIC_META.get(metric_key, {})
        self.metric_key = metric_key
        self.label = meta.get("label", metric_key)
        self.unit = meta.get("unit", "")
        self.values: list[float] = []
        self.timestamps: list[str] = []
        self.direction: TrendDirection = TrendDirection.INSUFFICIENT
        self.slope: float = 0.0          # 线性斜率（每天变化量）
        self.predicted_next: Optional[float] = None  # 线性外推预测值
        self.in_normal_range: bool = True
        self.upgrade_alert: bool = False   # 是否触发升级预警
        self.upgrade_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "metric_key": self.metric_key,
            "label": self.label,
            "unit": self.unit,
            "values": self.values,
            "timestamps": self.timestamps,
            "direction": self.direction.value,
            "slope": round(self.slope, 4),
            "predicted_next": round(self.predicted_next, 2) if self.predicted_next is not None else None,
            "in_normal_range": self.in_normal_range,
            "upgrade_alert": self.upgrade_alert,
            "upgrade_reason": self.upgrade_reason,
        }


# ============================================================================
# 趋势分析引擎
# ============================================================================

class TrendAnalyzer:
    """
    指标趋势分析引擎

    使用方式：
        analyzer = TrendAnalyzer()
        # vital_records 格式：[{"date": "2025-07-01", "fasting_glucose": 6.8, ...}, ...]
        results = analyzer.analyze(vital_records)
    """

    # 升级规则
    ESCALATION_RULES = [
        {
            "name": "连续恶化",
            "check": lambda vals, meta: len(vals) >= 3 and all(
                TrendAnalyzer._is_abnormal(vals[i], meta, direction="bad")
                for i in range(-3, 0)
            ),
            "reason": "连续 3 次指标异常且持续恶化",
            "alert": AlertLevel.YELLOW,
        },
        {
            "name": "突破危险阈值",
            "check": lambda vals, meta: len(vals) >= 1 and (
                vals[-1] >= meta.get("danger_high", float("inf")) or
                vals[-1] <= meta.get("danger_low", 0)
            ),
            "reason": "最新指标突破危险阈值",
            "alert": AlertLevel.RED,
        },
        {
            "name": "波动加大",
            "check": lambda vals, meta: len(vals) >= 4 and TrendAnalyzer._is_increasing_variance(vals),
            "reason": "指标波动明显加大，控制不稳定",
            "alert": AlertLevel.YELLOW,
        },
        {
            "name": "线性外推超标",
            "check": lambda vals, meta, pred: (
                pred is not None and (
                    pred >= meta.get("danger_high", float("inf")) or
                    pred <= meta.get("danger_low", 0)
                )
            ),
            "reason": "按当前趋势预测下次指标将超出危险范围",
            "alert": AlertLevel.YELLOW,
        },
        {
            "name": "持续正常",
            "check": lambda vals, meta: len(vals) >= 3 and all(
                meta.get("normal_low", 0) <= v <= meta.get("normal_high", float("inf"))
                for v in vals[-3:]
            ),
            "reason": "连续 3 次指标正常，控制良好",
            "alert": None,  # 正向，不升级
        },
    ]

    def analyze(self, vital_records: list[dict]) -> list[TrendResult]:
        """
        分析所有指标的趋势。

        Args:
            vital_records: [{"date": "2025-07-01", "fasting_glucose": 6.8, ...}, ...]

        Returns:
            list[TrendResult]
        """
        if not vital_records:
            return []

        # 按日期排序
        sorted_records = sorted(vital_records, key=lambda r: r.get("date", ""))

        # 按指标聚合
        metric_series: dict[str, list[tuple[str, float]]] = {}
        for record in sorted_records:
            record_date = record.get("date", "")
            for key in METRIC_META:
                val = record.get(key)
                if val is not None and isinstance(val, (int, float)):
                    metric_series.setdefault(key, []).append((record_date, val))

        results = []
        for metric_key, series in metric_series.items():
            result = self._analyze_single(metric_key, series)
            results.append(result)

        return results

    def _analyze_single(self, metric_key: str, series: list[tuple[str, float]]) -> TrendResult:
        """分析单个指标的趋势"""
        result = TrendResult(metric_key)
        meta = METRIC_META.get(metric_key, {})

        result.timestamps = [s[0] for s in series]
        result.values = [s[1] for s in series]

        if len(result.values) < 2:
            result.direction = TrendDirection.INSUFFICIENT
            return result

        # 1. 线性回归（最小二乘法）
        n = len(result.values)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(result.values) / n

        numerator = sum((x[i] - x_mean) * (result.values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            result.slope = 0.0
        else:
            result.slope = numerator / denominator

        # 2. 趋势方向判定
        result.direction = self._classify_direction(result.values, result.slope, meta)

        # 3. 线性外推预测
        if result.slope != 0:
            result.predicted_next = result.values[-1] + result.slope

        # 4. 当前值是否在正常范围
        last_val = result.values[-1]
        result.in_normal_range = (
            meta.get("normal_low", 0) <= last_val <= meta.get("normal_high", float("inf"))
        )

        # 5. 升级规则检查
        self._check_escalation_rules(result, meta)

        return result

    def _classify_direction(self, values: list[float], slope: float, meta: dict) -> TrendDirection:
        """分类趋势方向"""
        if len(values) < 3:
            return TrendDirection.INSUFFICIENT

        recent = values[-3:]
        ideal = meta.get("ideal_direction", "stable")

        # 计算变异系数（波动程度）
        mean_val = sum(recent) / len(recent)
        if mean_val != 0:
            cv = (max(recent) - min(recent)) / abs(mean_val)
        else:
            cv = 0

        # 波动大
        if cv > 0.15:
            return TrendDirection.FLUCTUATING

        # 斜率分析
        abs_slope = abs(slope)
        threshold = mean_val * 0.02  # 2% 变化视为有意义

        if abs_slope < threshold:
            return TrendDirection.STABLE

        # 有显著变化
        if slope > 0:
            # 上升中
            if ideal == "decreasing":
                return TrendDirection.WORSENING
            elif ideal == "stable":
                return TrendDirection.WORSENING if slope > threshold * 2 else TrendDirection.STABLE
            else:
                return TrendDirection.IMPROVING
        else:
            # 下降中
            if ideal == "decreasing":
                return TrendDirection.IMPROVING
            elif ideal == "stable":
                return TrendDirection.WORSENING if abs(slope) > threshold * 2 else TrendDirection.STABLE
            else:
                return TrendDirection.IMPROVING

    def _check_escalation_rules(self, result: TrendResult, meta: dict):
        """检查升级规则"""
        vals = result.values

        # 规则 1: 连续恶化
        if len(vals) >= 3:
            all_bad = all(self._is_abnormal(v, meta, "bad") for v in vals[-3:])
            if all_bad:
                result.upgrade_alert = True
                result.upgrade_reason = "连续 3 次指标异常且持续恶化"
                return

        # 规则 2: 突破危险阈值
        if len(vals) >= 1:
            last = vals[-1]
            if last >= meta.get("danger_high", float("inf")) or last <= meta.get("danger_low", 0):
                result.upgrade_alert = True
                result.upgrade_reason = f"最新值 {last} {meta.get('unit','')} 突破危险阈值"
                return

        # 规则 3: 波动加大
        if len(vals) >= 4 and self._is_increasing_variance(vals):
            result.upgrade_alert = True
            result.upgrade_reason = "指标波动明显加大，控制不稳定"
            return

        # 规则 4: 线性外推超标
        if result.predicted_next is not None:
            pred = result.predicted_next
            if pred >= meta.get("danger_high", float("inf")) or pred <= meta.get("danger_low", 0):
                result.upgrade_alert = True
                result.upgrade_reason = f"按当前趋势预测下次指标将超出危险范围（预测值 {pred:.1f}）"
                return

    @staticmethod
    def _is_abnormal(value: float, meta: dict, direction: str = "bad") -> bool:
        """判断值是否异常"""
        low = meta.get("normal_low", 0)
        high = meta.get("normal_high", float("inf"))
        if direction == "bad":
            return value > high or value < low
        return low <= value <= high

    @staticmethod
    def _is_increasing_variance(values: list[float]) -> bool:
        """判断波动是否加大（比较前半段和后半段的极差）"""
        mid = len(values) // 2
        if mid < 2:
            return False
        first_half = values[:mid]
        second_half = values[mid:]
        range1 = max(first_half) - min(first_half)
        range2 = max(second_half) - min(second_half)
        return range2 > range1 * 1.5  # 后半段波动超过前半段 1.5 倍

    def get_summary(self, results: list[TrendResult]) -> dict:
        """
        生成趋势摘要（供 LLM 上下文使用）
        """
        if not results:
            return {"summary": "暂无足够的指标历史数据用于趋势分析。"}

        lines = ["## 指标趋势分析"]
        upgrade_count = 0

        for r in results:
            direction_emoji = {
                TrendDirection.IMPROVING: "📈✅",
                TrendDirection.STABLE: "➡️",
                TrendDirection.WORSENING: "📉⚠️",
                TrendDirection.FLUCTUATING: "📊⚠️",
                TrendDirection.INSUFFICIENT: "❓",
            }
            emoji = direction_emoji.get(r.direction, "❓")
            status = "正常" if r.in_normal_range else "异常"

            line = f"- {r.label}：最新 {r.values[-1]} {r.unit}（{status}），趋势 {r.direction.value} {emoji}"
            if r.predicted_next is not None:
                line += f"，预测下次 ≈ {r.predicted_next:.1f}"
            lines.append(line)

            if r.upgrade_alert:
                upgrade_count += 1
                lines.append(f"  ⚠️ {r.upgrade_reason}")

        if upgrade_count > 0:
            lines.append(f"\n共 {upgrade_count} 项指标触发升级预警，建议关注。")
        else:
            lines.append("\n所有指标趋势平稳，无明显异常。")

        return {"summary": "\n".join(lines), "upgrade_count": upgrade_count}
