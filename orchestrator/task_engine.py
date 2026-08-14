"""智能任务调度引擎 —— 自动发现、排序、并行执行"""

import os
import asyncio
import logging
from datetime import datetime
from typing import Callable, Awaitable
from dataclasses import dataclass, field

from enums.paths import BASE_DIR, UPLOAD_DIR
from deps import logger

logger = logging.getLogger(__name__)

@dataclass
class TaskResult:
    name: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0

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

class TaskEngine:
    """智能任务发现 + 拓扑排序 + 并行执行"""

    def __init__(self):
        self.tasks: dict[str, TaskDef] = {}
        self.results: dict[str, TaskResult] = {}

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
        try:
            if asyncio.iscoroutinefunction(task.func):
                output = await task.func()
            else:
                loop = asyncio.get_event_loop()
                output = await loop.run_in_executor(None, task.func)
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return TaskResult(name=name, success=True, output=str(output), duration_ms=duration)
        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            logger.exception(f"任务 {name} 执行失败")
            return TaskResult(name=name, success=False, error=str(e), duration_ms=duration)

    async def run(self) -> list[TaskResult]:
        """完整调度流程：发现 → 排序 → 并行执行"""
        discovered = self.discover()
        if not discovered:
            return [TaskResult(name="调度器", success=False, error="未检测到可执行的任务，请检查数据文件")]

        batches = self.sort_tasks(discovered)
        all_results = []

        for batch in batches:
            if len(batch) == 1:
                results = [await self._run_one(batch[0])]
            else:
                results = await asyncio.gather(
                    *[self._run_one(name) for name in batch],
                    return_exceptions=True
                )
                results = [
                    r if isinstance(r, TaskResult) else TaskResult(
                        name=batch[i], success=False, error=str(r)
                    )
                    for i, r in enumerate(results)
                ]

            for r in results:
                self.results[r.name] = r
                all_results.append(r)

        return all_results
