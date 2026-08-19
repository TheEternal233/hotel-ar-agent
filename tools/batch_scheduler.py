"""批量智能调度工具 —— 让AI对话可以调用TaskEngine的任务编排能力

封装 task_engine.py 的核心能力：
- 自动发现当前可执行的任务（基于文件存在性）
- 拓扑排序 + 优先级
- 并行执行
- 失败隔离 + 重试

AI 使用场景：
  "帮我跑今天的对账" → batch_scheduler(mode="daily")
  "帮我跑月度结算"  → batch_scheduler(mode="monthly")
  "帮我跑全部任务"  → batch_scheduler(mode="all")
"""

import asyncio
import os
from langchain.tools import tool


@tool
def batch_scheduler(mode: str = "daily") -> str:
    """批量智能调度：自动发现、排序、并行执行多个对账/分析任务。

    根据 mode 自动判断当前该跑哪些功能：
    - "daily":   日清任务（信用卡对账等）
    - "monthly": 月度任务（OTA对账、账龄分析、携程佣金等）
    - "all":     全部可执行任务

    系统会自动检查数据文件是否存在，只执行有数据的任务，
    多个无依赖的任务会并行处理，失败的任务会跳过并提示人工处理。
    """
    if mode not in ("daily", "monthly", "all"):
        return f"错误：不支持的调度模式 '{mode}'，可选: daily, monthly, all"

    # 延迟导入，避免循环导入（deps -> graph -> agent -> batch_scheduler -> task_engine -> deps）
    from orchestrator.task_engine import TaskEngine, TaskDef
    from deps import BASE_DIR, UPLOAD_DIR

    engine = TaskEngine(run_id=f"ai_{mode}")

    # ---------- 注册所有可能的任务 ----------

    # 1. 信用卡对账（日清+周清）
    def _run_card():
        mod = __import__("tools.credit_card_recon.credit_card_recon", fromlist=["batch_card_recon"])
        return mod.batch_card_recon(os.path.join(BASE_DIR, "data", "清远", "信用卡对账"))
    engine.register(TaskDef(
        name="credit_card_recon",
        func=_run_card,
        required_paths=[os.path.join(BASE_DIR, "data", "清远", "信用卡对账")],
        priority=1,
        parallel=True,
    ))

    # 2. OTA批量对账（月度）
    def _run_ota():
        mod = __import__("tools.ar_recon.batch_runner", fromlist=["batch_ota_recon"])
        return mod.batch_ota_recon(str(UPLOAD_DIR), cleanup=False)
    engine.register(TaskDef(
        name="ota_recon",
        func=_run_ota,
        required_paths=[str(UPLOAD_DIR)],
        priority=2,
        parallel=True,
    ))

    # 3. 账龄分析（月度）
    def _run_aging():
        aging_file = None
        for f in os.listdir(UPLOAD_DIR):
            if f.endswith(".xlsx") and ("应收" in f or "aging" in f.lower()):
                aging_file = os.path.join(UPLOAD_DIR, f)
                break
        if not aging_file:
            return "未找到应收账龄分析文件"
        mod = __import__("tools.protocol_settlement.aging_pms", fromlist=["aging_analysis"])
        return mod.aging_analysis(receivable_path=aging_file)
    engine.register(TaskDef(
        name="aging_analysis",
        func=_run_aging,
        required_paths=[str(UPLOAD_DIR)],
        priority=3,
        parallel=True,
    ))

    # 4. 携程佣金（月度）
    def _run_ctrip():
        mod = __import__("tools.ctrip_commission_reconcile.ctrip_commission", fromlist=["ctrip_commission"])
        ctrip_file = None
        for f in os.listdir(UPLOAD_DIR):
            if f.endswith(".xls") and "携程" in f:
                ctrip_file = f
                break
        if not ctrip_file:
            return "未找到携程佣金文件"
        return mod.ctrip_commission(ctrip_filename=ctrip_file)
    engine.register(TaskDef(
        name="ctrip_commission",
        func=_run_ctrip,
        required_paths=[str(UPLOAD_DIR)],
        priority=4,
        parallel=True,
    ))

    # 5. 每日应收处理（日清）
    def _run_daily_ar():
        mod = __import__("tools.daily_ar", fromlist=["daily_ar_processing"])
        return mod.daily_ar_processing()
    engine.register(TaskDef(
        name="daily_ar_processing",
        func=_run_daily_ar,
        required_paths=[],
        priority=5,
        parallel=True,
    ))

    # ---------- 根据 mode 过滤任务 ----------
    mode_tasks = {
        "daily": ["credit_card_recon", "daily_ar_processing"],
        "monthly": ["ota_recon", "aging_analysis", "ctrip_commission"],
        "all": list(engine.tasks.keys()),
    }
    allowed = set(mode_tasks.get(mode, []))

    for name in list(engine.tasks.keys()):
        if name not in allowed:
            del engine.tasks[name]

    # ---------- 执行 ----------
    if not engine.tasks:
        return f"当前模式 '{mode}' 没有注册任何任务"

    results = asyncio.run(engine.run())

    # ---------- 格式化输出 ----------
    lines = [
        f"=== 批量调度完成 [{mode}] ===",
        f"任务总数: {len(results)}",
        f"成功: {sum(1 for r in results if r.success)}",
        f"失败: {sum(1 for r in results if not r.success)}",
        f"需人工复核: {sum(1 for r in results if r.needs_review)}",
        "",
        "各任务详情:",
    ]
    for r in results:
        status = "✅" if r.success else "❌"
        if r.status == "skipped":
            status = "⏭️"
        review_mark = " [待复核]" if r.needs_review else ""
        detail = r.output if r.success else r.error
        lines.append(f"  [{r.name}] {status}{review_mark} 置信度:{r.confidence:.0%} {detail[:100]}")

    return "\n".join(lines)