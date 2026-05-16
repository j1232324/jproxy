"""
模型池管理器 — 优先级队列 + 配额追踪 + 冷却降级 + 每日重置。

核心改进:
  - 429 分为"频率超限"和"每日配额耗尽"两种
  - 频率超限 → 冷却一段时间后自动恢复（高优模型可以切回来）
  - 连续 429 ≥ 3 次 → 判定每日额度已用完，今日不再使用
  - 成功调用一次 → 重置频率计数，恢复最高优先级
"""

import json
import os
import time
from datetime import date
from typing import Optional


STATE_FILE = ".model_quota_state.json"
REVIEW_FILE = ".model_review"

# 冷却策略
INITIAL_COOLDOWN = 30          # 首次 429 冷却 30 秒
MAX_COOLDOWN = 300             # 最长冷却 5 分钟
CONSECUTIVE_429_LIMIT = 3      # 连续几次 429 判定为每日配额耗尽


class ModelManager:
    """模型池管理器。"""

    def __init__(self, config: dict):
        self.config = config
        self.models = list(config.get("models", []))
        self.settings = config.get("settings", {})

        # 按优先级升序排列
        self.models.sort(key=lambda m: m.get("priority", 999))

        # 每个模型的每日限额不一定相同，也不一定知道具体值。
        # daily_limit 留空 = 不限（靠 429 响应自动判断）
        # 建议用户按实际上游额度配置
        for m in self.models:
            m.setdefault("daily_limit", 0)

        # ── 持久状态（跨进程存活） ──
        self.state = self._load_state()
        self._check_daily_reset()

        # ── 内存状态（仅本次运行有效） ──
        self._cooldowns: dict[str, float] = {}        # model_name → 冷却到期时间戳
        self._consecutive_429: dict[str, int] = {}    # model_name → 连续 429 次数

    # ═══════════════════════════════════════════════════════
    # 公共接口
    # ═══════════════════════════════════════════════════════

    def select_model(self) -> Optional[str]:
        """选择当前可用的最高优先级模型。

        跳过:
          - 已标记每日配额耗尽的
          - 设置了 daily_limit 且今日已达上限的
          - 处于频率冷却中的

        Returns:
            模型名称，或 None（全部不可用）
        """
        now = time.time()

        for model in self.models:
            name = model["name"]
            daily_limit = model.get("daily_limit", 0) or 0  # 0 = 不限
            info = self.state["models"].get(name, {})

            # ── 每日配额检查 ──
            if info.get("daily_exhausted", False):
                continue
            if daily_limit > 0 and info.get("used_today", 0) >= daily_limit:
                continue

            # ── 频率限制冷却检查 ──
            cooldown_until = self._cooldowns.get(name, 0)
            if cooldown_until > now:
                continue

            return name

        return None

    def record_usage(self, model_name: str):
        """记录一次成功的调用。

        - 成功计数 +1
        - 清除该模型的频率限制状态（冷却 + 连续 429 计数）
        - 持久化到磁盘
        """
        self._ensure_model_entry(model_name)
        self.state["models"][model_name]["used_today"] += 1
        self.state["last_updated"] = date.today().isoformat()

        # 成功调用 = 模型正常，清除频率限制状态
        self._cooldowns.pop(model_name, None)
        self._consecutive_429.pop(model_name, None)

        self._save_state()

    def handle_429(self, model_name: str):
        """处理 429 响应（频率超限或配额耗尽）。

        策略:
          第 1 次 429 → 冷却 30 秒，之后可恢复
          第 2 次 429 → 冷却 60 秒
          第 3 次 429 → 判定每日配额已耗尽，今日不再使用
        """
        self._ensure_model_entry(model_name)

        # 累加连续 429 次数
        count = self._consecutive_429.get(model_name, 0) + 1
        self._consecutive_429[model_name] = count

        if count >= CONSECUTIVE_429_LIMIT:
            # 连续多次 429 → 大概率每日配额用完了
            self._mark_daily_exhausted(model_name)
            # 清理冷却状态（反正也用不上了）
            self._cooldowns.pop(model_name, None)
        else:
            # 频率超限 → 冷却一段时间
            cooldown = min(
                INITIAL_COOLDOWN * (2 ** (count - 1)),
                MAX_COOLDOWN,
            )
            self._cooldowns[model_name] = time.time() + cooldown

    def get_usage_summary(self) -> list:
        """返回所有已配置模型的配额使用和状态。"""
        now = time.time()
        summary = []

        for model in self.models:
            name = model["name"]
            daily_limit = model.get("daily_limit", 0) or 0  # 0 = 不限
            info = self.state["models"].get(name, {})

            used = info.get("used_today", 0)
            daily_exhausted = info.get("daily_exhausted", False)
            cooldown_until = self._cooldowns.get(name, 0)

            limit_exceeded = daily_limit > 0 and used >= daily_limit

            # 当前状态
            status = "✓ 可用"
            if daily_exhausted or limit_exceeded:
                status = "✗ 每日配额耗尽"
            elif cooldown_until > now:
                remain_sec = int(cooldown_until - now)
                status = f"⏳ 冷却中 ({remain_sec}s)"
            elif daily_limit == 0:
                status = f"✓ 已用 {used} 次（无限额）"

            summary.append({
                "name": name,
                "priority": model.get("priority", 999),
                "used_today": used,
                "daily_limit": daily_limit if daily_limit > 0 else None,
                "status": status,
                "available": not daily_exhausted and not limit_exceeded and cooldown_until <= now,
                "cooldown_remaining_sec": max(0, int(cooldown_until - now)) if cooldown_until > now else 0,
            })

        return summary

    # ─── 模型列表审查提醒 ─────────────────────────────────

    def needs_review(self) -> bool:
        interval = self.settings.get("model_review_interval_days", 30)
        review_date = self._load_review_date()
        if review_date is None:
            return True
        delta = date.today() - review_date
        return delta.days >= interval

    def mark_reviewed(self):
        self._save_review_date(date.today())

    # ═══════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════

    def _ensure_model_entry(self, name: str):
        if name not in self.state["models"]:
            self.state["models"][name] = {
                "used_today": 0,
                "daily_exhausted": False,
            }

    def _get_model_limit(self, name: str) -> int:
        for m in self.models:
            if m["name"] == name:
                return m.get("daily_limit", 0)
        return 0

    def _mark_daily_exhausted(self, model_name: str):
        """将模型标记为今日配额已耗尽。"""
        self._ensure_model_entry(model_name)
        daily_limit = self._get_model_limit(model_name)
        self.state["models"][model_name]["used_today"] = daily_limit
        self.state["models"][model_name]["daily_exhausted"] = True
        self.state["last_updated"] = date.today().isoformat()
        self._save_state()

    def _check_daily_reset(self):
        """跨日自动重置所有模型配额。"""
        today = date.today().isoformat()
        last_reset = self.state.get("last_reset", "")

        if last_reset != today:
            for name in self.state["models"]:
                self.state["models"][name] = {
                    "used_today": 0,
                    "daily_exhausted": False,
                }
            self.state["last_reset"] = today
            # 同时清理内存中的冷却状态
            self._cooldowns.clear()
            self._consecutive_429.clear()
            self._save_state()

    # ─── 持久化 ───────────────────────────────────────────

    def _load_state(self) -> dict:
        default = {
            "models": {},
            "last_reset": date.today().isoformat(),
            "last_updated": date.today().isoformat(),
        }
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return default

    def _save_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=2)
        except IOError:
        # 持久化状态文件，静默失败
            pass

    def _load_review_date(self) -> Optional[date]:
        if os.path.exists(REVIEW_FILE):
            try:
                with open(REVIEW_FILE, "r") as f:
                    return date.fromisoformat(f.read().strip())
            except (ValueError, IOError):
                pass
        return None

    def _save_review_date(self, d: date):
        try:
            with open(REVIEW_FILE, "w") as f:
                f.write(d.isoformat())
        except IOError:
            pass
