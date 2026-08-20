"""智能任务调度引擎 —— 自动发现、排序、并行执行"""

import os
import asyncio
import logging
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, Awaitable
from dataclasses import dataclass, field

from enums.paths import BASE_DIR, UPLOAD_DIR
from deps import logger

logger = logging.getLogger(__name__)

# 默认线程池大小：CPU 核心数 + 2，避免 Excel 等 IO 密集型任务耗尽资源
DEFAULT_EXECUTOR_MAX_WORKERS = min(os.cpu_count() or 4, 8)

@dataclass
class TaskResult:
    name: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0
    status: str = ""          # success / failed / skipped
    run_id: str = ""          # 所属调度批次ID
    skipped_reason: str = ""  # 被跳过原因
    confidence: float = 0.0   # 置信度评分 0.0 ~ 1.0
    needs_review: bool = False  # 是否需要人工复核

@dataclass
class TaskDef:
    name: str
    func: Callable[..., Awaitable[str]] | Callable[..., str]
    # 自动发现：检查这些路径存在才执行
    required_paths: list[str] = field(default_factory=list)
    # 依赖：必须先完成的其他任务名
    depends_on: list[str] = field(default_factory=list)
    # 优先级：数字越小越优先
    priority: int = 99
    # 是否可并行
    parallel: bool = True
    # 超时时间（秒），默认5分钟
    timeout: int = 300
    # 失败重试次数，默认2次
    retries: int = 2
    # 依赖失败时是否跳过（默认True，即上游失败则跳过）
    skip_on_upstream_failure: bool = True

class TaskEngine:
    """智能任务发现 + 拓扑排序 + 并行执行"""

    def __init__(self, run_id: str = "", max_workers: int = None):
        self.tasks: dict[str, TaskDef] = {}
        self.results: dict[str, TaskResult] = {}
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        # 有界线程池，避免默认线程池无界导致资源耗尽
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers or DEFAULT_EXECUTOR_MAX_WORKERS,
            thread_name_prefix="task_engine"
        )


    def register(self, task: TaskDef):
        self.tasks[task.name] = task

    def discover(self) -> list[str]:
        """自动发现当前可执行的任务列表"""
        available = []
        for name, task in self.tasks.items():
            paths_ok = all(os.path.exists(p) for p in task.required_paths)
            if paths_ok:
                available.append(name)
        return available

    def _any_upstream_failed(self, task_name: str) -> tuple[bool, str]:
        """检查任务的上游依赖是否有失败/跳过的，返回 (是否失败, 原因)"""
        task = self.tasks.get(task_name)
        if not task:
            return False, ""
        for dep in task.depends_on:
            dep_result = self.results.get(dep)
            if dep_result and not dep_result.success:
                return True, f"上游任务 [{dep}] 失败: {dep_result.error}"
            if dep_result and dep_result.status == "skipped":
                return True, f"上游任务 [{dep}] 被跳过: {dep_result.skipped_reason}"
        return False, ""

    def sort_tasks(self, task_names: list[str]) -> list[list[str]]:
        """拓扑排序 + 优先级，返回按批次分组的任务（同批次可并行）"""
        pending = set(task_names)
        batches = []

        while pending:
            ready = [
                n for n in pending
                if all(d not in pending for d in self.tasks[n].depends_on)
            ]
            if not ready:
                ready = list(pending)
                logger.warning(f"检测到循环依赖，强制执行: {ready}")

            ready.sort(key=lambda n: self.tasks[n].priority)

            batch = []
            for n in ready:
                batch.append(n)
                pending.remove(n)

            batches.append(batch)

        return batches

    async def _run_one(self, name: str) -> TaskResult:
        """执行单个任务"""
        task = self.tasks[name]
        start = datetime.now()
        last_error=""

        # 循环执行，初始1次+重试retries次
        for attempt in range(task.retries+1):
            try:
                # 执行任务，带超时控制
                if asyncio.iscoroutinefunction(task.func):
                    if task.timeout>0:
                        output=await asyncio.wait_for(task.func(), timeout=task.timeout)
                    else:
                        output=task.func()
                else:
                    # 轻量级同步任务直接执行，避免线程切换开销
                    if task.timeout>0:
                        output=await asyncio.wait_for(
                            asyncio.to_thread(task.func),
                            timeout=task.timeout
                        )
                    else:
                        output=task.func()

                # 成功，返回结果
                duration=int((datetime.now() - start).total_seconds() * 1000)
                retry_info=f"(重试{attempt}次后成功)" if attempt>0 else ""

                # 计算置信度
                output_str = str(output) + retry_info
                confidence = self._calculate_confidence(name, output_str, True)
                needs_review = confidence < 0.8

                return TaskResult(
                    name=name, success=True, status="success",
                    output=output_str, duration_ms=duration,
                    run_id=self.run_id, confidence=confidence,
                    needs_review=needs_review
                )

            except asyncio.TimeoutError:
                # 超时，记录错误，等待后重试
                last_error = f"第{attempt + 1}次执行超时（>{task.timeout}秒）"
                logger.warning(f"任务 {name} {last_error}")
                if attempt<task.retries:
                    await asyncio.sleep(1*(attempt+1))
            except Exception as e:
                # 异常，记录错误，等待后重试
                last_error=str(e)
                logger.exception(f"任务 {name} 第{attempt + 1}次执行失败")
                if attempt < task.retries:
                    await asyncio.sleep(1 * (attempt + 1))

        # 全部重试用完：返回失败
        duration = int((datetime.now() - start).total_seconds() * 1000)
        error_msg=f"{last_error} (已重试{task.retries}次，全部失败)"

        # 计算失败时的置信度（总是0，需要复核）
        confidence = 0.0
        needs_review = True

        # 写入失败日志，供前端提示人工处理
        try:
            failed_log=os.path.join(BASE_DIR,"data","failed_tasks.jsonl")
            os.makedirs(os.path.dirname(failed_log), exist_ok=True)
            with open(failed_log,"a",encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp":datetime.now().isoformat(),
                    "task":name,
                    "error":error_msg,
                    "status":"pending_review",
                    "confidence": confidence,
                    "needs_review": needs_review,
                },ensure_ascii=False)+"\n")
        except Exception:
            pass

        return TaskResult(
            name=name, success=False,status="failed",
            error=error_msg,
            duration_ms=duration,
            run_id=self.run_id,
            confidence=confidence,
            needs_review=needs_review,
        )



    async def run(self) -> list[TaskResult]:
        """完整调度流程：发现 → 排序 → 并行执行"""
        discovered = self.discover()
        if not discovered:
            return [TaskResult(name="调度器", success=False, status="failed", error="未检测到可执行的任务，请检查数据文件", run_id=self.run_id)]

        batches = self.sort_tasks(discovered)
        all_results = []

        for batch in batches:
            # 前置检查：本批次中是否有任务因上游失败需要跳过
            to_run = []
            skipped_in_batch = []
            for name in batch:
                failed, reason = self._any_upstream_failed(name)
                task_def = self.tasks.get(name)
                if failed and task_def and task_def.skip_on_upstream_failure:
                    skip_result = TaskResult(
                        name=name, success=False, status="skipped",
                        error=reason, skipped_reason=reason,
                        duration_ms=0, run_id=self.run_id,
                    )
                    self.results[name] = skip_result
                    skipped_in_batch.append(skip_result)
                else:
                    to_run.append(name)

            all_results.extend(skipped_in_batch)

            # 执行实际需要运行的任务
            if len(to_run) == 1:
                results = [await self._run_one(to_run[0])]
            elif len(to_run) > 1:
                results = await asyncio.gather(
                    *[self._run_one(name) for name in to_run],
                    return_exceptions=True
                )
                results = [
                    r if isinstance(r, TaskResult) else TaskResult(
                        name=to_run[i], success=False, status="failed", error=str(r), run_id=self.run_id
                    )
                    for i, r in enumerate(results)
                ]
            else:
                results = []

            for r in results:
                self.results[r.name] = r
                all_results.append(r)

        return all_results

    @staticmethod
    def _calculate_confidence(task_name: str, output: str, success: bool) -> float:
        """计算任务执行结果的置信度"""
        if not success:
            return 0.0

        # 检查输出中的关键词
        error_keywords = ["错误", "失败", "异常", "❌"]
        warning_keywords = ["差异", "未匹配", "跳过", "⚠️"]
        success_keywords = ["成功", "完成", "✅", "对平"]

        if any(kw in output for kw in error_keywords):
            return 0.3
        if any(kw in output for kw in warning_keywords):
            return 0.6
        if any(kw in output for kw in success_keywords):
            return 1.0

        return 0.7

    def shutdown(self):
        """关闭线程池，释放资源"""
        self._executor.shutdown(wait=True)