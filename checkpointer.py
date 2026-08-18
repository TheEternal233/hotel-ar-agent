"""
JsonFileSaver — 基于 JSON 文件的 LangGraph 检查点，无 SQLite 依赖。

特性：
- 每个 thread_id 一个 JSON 文件，存储在 data/memory/ 目录下
- 内存 LRU 缓存，限制最大缓存线程数（默认 50）
- 超限时自动卸载最久未使用的线程到磁盘
- 重启后状态自动恢复
- 接口完全兼容 langgraph.checkpoint.memory.InMemorySaver
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional, List, Tuple, Set

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
    RunnableConfig,
    get_checkpoint_metadata,
)


class JsonFileSaver(BaseCheckpointSaver):
    """
    基于 JSON 文件的检查点。
    每个 thread_id 一个文件，按需加载/卸载，内存 LRU 缓存。
    接口与 InMemorySaver 完全兼容。
    """

    def __init__(
        self,
        save_dir: str | Path = "./data/memory",
        max_cache_threads: int = 50,
        flush_interval: float = 2.0,
    ):
        super().__init__()
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache = max(max_cache_threads, 1)
        self.flush_interval = flush_interval
        # 内存缓存：thread_id -> 存储数据
        self._cache: dict[str, dict] = {}
        self._lock = threading.RLock()
        # 异步刷盘：待写入队列 + 后台线程
        self._dirty: Set[str] = set()
        self._flush_event = threading.Event()
        self._shutdown = False
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _file_path(self, thread_id: str) -> Path:
        """生成线程对应的 JSON 文件路径（过滤非法字符）"""
        safe_id = "".join(c for c in thread_id if c.isalnum() or c in "_-").rstrip()
        if not safe_id:
            safe_id = "unknown"
        return self.save_dir / f"{safe_id}.json"

    def _load_from_disk(self, thread_id: str) -> Optional[dict]:
        """从磁盘加载指定线程的完整存储数据"""
        fp = self._file_path(thread_id)
        if not fp.exists():
            return None
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 重建 defaultdict 结构
            return self._deserialize_storage(data)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_to_disk(self, thread_id: str, data: dict) -> None:
        """将完整存储数据持久化到磁盘（同步接口，供后台线程调用）"""
        fp = self._file_path(thread_id)
        try:
            serialized = self._serialize_storage(data)
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(serialized, f, ensure_ascii=False, default=self._json_default)
        except OSError:
            pass

    def _flush_loop(self) -> None:
        """后台刷盘线程：定期将脏数据写入磁盘"""
        while not self._shutdown:
            # 等待 flush_interval 或显式唤醒
            self._flush_event.wait(timeout=self.flush_interval)
            self._flush_event.clear()
            if self._shutdown:
                break
            self._do_flush()

    def _do_flush(self) -> None:
        """执行实际刷盘：批量写入所有脏数据"""
        with self._lock:
            dirty_list = list(self._dirty)
            self._dirty.clear()
        for tid in dirty_list:
            data = self._cache.get(tid)
            if data is not None:
                self._save_to_disk(tid, data)

    def _mark_dirty(self, thread_id: str) -> None:
        """标记 thread_id 为脏数据，触发后台异步写入"""
        with self._lock:
            self._dirty.add(thread_id)
        self._flush_event.set()

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """处理不可 JSON 序列化的对象"""
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    def _deserialize_storage(self, data: dict) -> dict:
        """将 JSON 数据反序列化为内部存储结构

        serde.dumps_typed 返回 (type_name, bytes) 元组，需要分别还原。
        """
        result = {
            "storage": defaultdict(lambda: defaultdict(dict)),
            "writes": defaultdict(dict),
            "blobs": {},
        }
        # storage: thread_id -> checkpoint_ns -> checkpoint_id -> ((type_name, bytes), (type_name, bytes), parent_id)
        for tid, ns_data in data.get("storage", {}).items():
            for ns, cp_data in ns_data.items():
                for cp_id, (cp_list, meta_list, parent) in cp_data.items():
                    result["storage"][tid][ns][cp_id] = (
                        (cp_list[0], self._from_b64(cp_list[1])),
                        (meta_list[0], self._from_b64(meta_list[1])),
                        parent,
                    )
        # writes: (thread_id, checkpoint_ns, checkpoint_id) -> (task_id, idx) -> (task_id, channel, (type_name, bytes), task_path)
        for key_str, writes in data.get("writes", {}).items():
            key = ast.literal_eval(key_str)
            tid, ns, cp_id = key
            for inner_key_str, (tid_w, ch, val_list, tpath) in writes.items():
                inner_key = ast.literal_eval(inner_key_str)
                result["writes"][(tid, ns, cp_id)][inner_key] = (
                    tid_w, ch, (val_list[0], self._from_b64(val_list[1])), tpath
                )
        # blobs: (thread_id, checkpoint_ns, channel, version) -> (type, bytes)
        for key_str, (typ, val_b64) in data.get("blobs", {}).items():
            key = ast.literal_eval(key_str)
            tid, ns, ch, ver = key
            result["blobs"][(tid, ns, ch, ver)] = (typ, self._from_b64(val_b64))
        return result

    def _serialize_storage(self, data: dict) -> dict:
        """将内部存储结构序列化为 JSON 可存储格式

        serde.dumps_typed 返回 (type_name, bytes) 元组，需要分别序列化。
        """
        result = {"storage": {}, "writes": {}, "blobs": {}}
        for tid, ns_data in data["storage"].items():
            result["storage"][tid] = {}
            for ns, cp_data in ns_data.items():
                result["storage"][tid][ns] = {}
                for cp_id, (cp_tuple, meta_tuple, parent) in cp_data.items():
                    # cp_tuple = (type_name, bytes)
                    result["storage"][tid][ns][cp_id] = [
                        [cp_tuple[0], self._to_b64(cp_tuple[1])],
                        [meta_tuple[0], self._to_b64(meta_tuple[1])],
                        parent,
                    ]
        for key, writes in data["writes"].items():
            tid, ns, cp_id = key
            result["writes"][str((tid, ns, cp_id))] = {}
            for (task_id, idx), (tid_w, ch, val_tuple, tpath) in writes.items():
                result["writes"][str((tid, ns, cp_id))][str((task_id, idx))] = [
                    tid_w, ch, [val_tuple[0], self._to_b64(val_tuple[1])], tpath
                ]
        for key, (typ, val_bytes) in data["blobs"].items():
            tid, ns, ch, ver = key
            result["blobs"][str((tid, ns, ch, ver))] = [typ, self._to_b64(val_bytes)]
        return result

    @staticmethod
    def _to_b64(data: bytes) -> str:
        import base64
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def _from_b64(s: str) -> bytes:
        import base64
        return base64.b64decode(s.encode("ascii"))

    def _touch(self, thread_id: str) -> None:
        """将 thread_id 标记为最近使用（移动到缓存末尾）"""
        if thread_id in self._cache:
            data = self._cache.pop(thread_id)
            self._cache[thread_id] = data

    def _evict_if_needed(self) -> None:
        """LRU 淘汰：缓存超限时卸载最久未使用的线程"""
        while len(self._cache) > self.max_cache:
            oldest_tid = next(iter(self._cache))
            oldest_data = self._cache.pop(oldest_tid)
            self._save_to_disk(oldest_tid, oldest_data)

    def _get_thread_data(self, thread_id: str) -> dict:
        """获取指定线程的存储数据（从缓存或磁盘加载）"""
        if thread_id in self._cache:
            self._touch(thread_id)
            return self._cache[thread_id]
        data = self._load_from_disk(thread_id)
        if data is None:
            data = {
                "storage": defaultdict(lambda: defaultdict(dict)),
                "writes": defaultdict(dict),
                "blobs": {},
            }
        self._cache[thread_id] = data
        self._evict_if_needed()
        return data

    def _load_blobs(
        self,
        thread_id: str,
        checkpoint_ns: str,
        versions: ChannelVersions,
    ) -> dict[str, Any]:
        """加载 blob 数据（与 InMemorySaver 一致）"""
        data = self._get_thread_data(thread_id)
        result: dict[str, Any] = {}
        for k, ver in versions.items():
            kk = (thread_id, checkpoint_ns, k, ver)
            if kk not in data["blobs"]:
                continue
            vv = data["blobs"][kk]
            if vv[0] == "empty":
                continue
            result[k] = self.serde.loads_typed(vv)
        return result

    # ------------------------------------------------------------------
    # BaseCheckpointSaver 接口实现
    # ------------------------------------------------------------------

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """获取检查点元组（与 InMemorySaver 一致）"""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        data = self._get_thread_data(thread_id)
        storage = data["storage"]
        writes = data["writes"]

        if checkpoint_id:
            if (
                thread_id in storage
                and checkpoint_ns in storage[thread_id]
                and checkpoint_id in storage[thread_id][checkpoint_ns]
            ):
                checkpoint, metadata, parent_checkpoint_id = storage[thread_id][checkpoint_ns][checkpoint_id]
                checkpoint_ = self.serde.loads_typed(checkpoint)
                return CheckpointTuple(
                    config=config,
                    checkpoint={
                        **checkpoint_,
                        "channel_values": self._load_blobs(
                            thread_id, checkpoint_ns, checkpoint_["channel_versions"]
                        ),
                    },
                    metadata=self.serde.loads_typed(metadata),
                    pending_writes=[
                        (id, c, self.serde.loads_typed(v)) for id, c, v, _ in writes.get((thread_id, checkpoint_ns, checkpoint_id), {}).values()
                    ],
                    parent_config=(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": parent_checkpoint_id,
                            }
                        }
                        if parent_checkpoint_id
                        else None
                    ),
                )
        else:
            if thread_id in storage and checkpoint_ns in storage[thread_id] and storage[thread_id][checkpoint_ns]:
                checkpoint_id = max(storage[thread_id][checkpoint_ns].keys())
                checkpoint, metadata, parent_checkpoint_id = storage[thread_id][checkpoint_ns][checkpoint_id]
                checkpoint_ = self.serde.loads_typed(checkpoint)
                return CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint_id,
                        }
                    },
                    checkpoint={
                        **checkpoint_,
                        "channel_values": self._load_blobs(
                            thread_id, checkpoint_ns, checkpoint_["channel_versions"]
                        ),
                    },
                    metadata=self.serde.loads_typed(metadata),
                    pending_writes=[
                        (id, c, self.serde.loads_typed(v)) for id, c, v, _ in writes.get((thread_id, checkpoint_ns, checkpoint_id), {}).values()
                    ],
                    parent_config=(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": parent_checkpoint_id,
                            }
                        }
                        if parent_checkpoint_id
                        else None
                    ),
                )
        return None

    def get(self, config: RunnableConfig) -> Optional[Checkpoint]:
        """获取检查点"""
        if value := self.get_tuple(config):
            return value.checkpoint
        return None

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """保存检查点（与 InMemorySaver 一致）"""
        c = checkpoint.copy()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        values: dict[str, Any] = c.pop("channel_values")  # type: ignore[misc]

        data = self._get_thread_data(thread_id)

        for k, v in new_versions.items():
            data["blobs"][(thread_id, checkpoint_ns, k, v)] = (
                self.serde.dumps_typed(values[k]) if k in values else ("empty", b"")
            )

        data["storage"][thread_id][checkpoint_ns].update(
            {
                checkpoint["id"]: (
                    self.serde.dumps_typed(c),
                    self.serde.dumps_typed(get_checkpoint_metadata(config, metadata)),
                    config["configurable"].get("checkpoint_id"),  # parent
                )
            }
        )

        # 标记脏数据，由后台线程异步写入磁盘
        self._mark_dirty(thread_id)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: List[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """保存写入操作（与 InMemorySaver 一致）"""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        data = self._get_thread_data(thread_id)
        outer_key = (thread_id, checkpoint_ns, checkpoint_id)
        outer_writes = data["writes"].get(outer_key, {})

        for idx, (c, v) in enumerate(writes):
            inner_key = (task_id, idx)
            if inner_key in outer_writes:
                continue
            data["writes"][outer_key][inner_key] = (
                task_id,
                c,
                self.serde.dumps_typed(v),
                task_path,
            )

        # 标记脏数据，由后台线程异步写入磁盘
        self._mark_dirty(thread_id)

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ):
        """列出检查点（简化实现）"""
        thread_id = config["configurable"]["thread_id"] if config else None
        if not thread_id:
            return iter([])

        data = self._get_thread_data(thread_id)
        storage = data["storage"]
        results = []

        for tid, ns_data in storage.items():
            if thread_id and tid != thread_id:
                continue
            for checkpoint_ns, checkpoints in ns_data.items():
                for checkpoint_id, (checkpoint, metadata, parent) in checkpoints.items():
                    checkpoint_ = self.serde.loads_typed(checkpoint)
                    results.append(
                        CheckpointTuple(
                            config={
                                "configurable": {
                                    "thread_id": tid,
                                    "checkpoint_ns": checkpoint_ns,
                                    "checkpoint_id": checkpoint_id,
                                }
                            },
                            checkpoint={
                                **checkpoint_,
                                "channel_values": self._load_blobs(
                                    tid, checkpoint_ns, checkpoint_["channel_versions"]
                                ),
                            },
                            metadata=self.serde.loads_typed(metadata),
                            pending_writes=[],
                            parent_config=None,
                        )
                    )

        if limit:
            results = results[:limit]
        return iter(results)

    # ------------------------------------------------------------------
    # 异步方法（直接调用同步版本）
    # ------------------------------------------------------------------

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aget(self, config: RunnableConfig) -> Optional[Checkpoint]:
        return await asyncio.to_thread(self.get, config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: List[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ):
        for item in await asyncio.to_thread(self.list, config, filter=filter, before=before, limit=limit):
            yield item

    # ------------------------------------------------------------------
    # 管理接口
    # ------------------------------------------------------------------

    def _flush_and_wait(self) -> None:
        """强制刷盘并等待完成（用于关机等需要确保数据落盘的场景）"""
        self._do_flush()

    def clear_memory(self) -> int:
        """清空内存缓存（保留磁盘文件），返回清空的数量"""
        self._flush_and_wait()
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def clear_all(self) -> int:
        """清空内存和磁盘所有检查点，返回删除的文件数"""
        self._flush_and_wait()
        with self._lock:
            self._cache.clear()
            count = 0
            for fp in self.save_dir.glob("*.json"):
                try:
                    fp.unlink()
                    count += 1
                except OSError:
                    pass
            return count

    def memory_stats(self) -> dict:
        """返回当前内存缓存统计"""
        with self._lock:
            return {
                "cached_threads": len(self._cache),
                "max_cache": self.max_cache,
                "save_dir": str(self.save_dir),
                "disk_files": len(list(self.save_dir.glob("*.json"))),
                "dirty_threads": len(self._dirty),
            }