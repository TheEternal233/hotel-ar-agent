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
        max_checkpoints_per_thread: int = 100,
        flush_interval: float = 2.0,
        max_file_age_days: int = 7,
    ):
        super().__init__()
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache = max(max_cache_threads, 1)
        self.max_checkpoints = max(max_checkpoints_per_thread, 10)
        self.flush_interval = flush_interval
        self.max_file_age_days = max(max_file_age_days, 1)
        # 内存缓存：thread_id -> 存储数据
        self._cache: dict[str, dict] = {}
        self._lock = threading.RLock()
        # 异步刷盘：待写入队列 + 后台线程
        self._dirty: Set[str] = set()
        # 增量保存：记录每个线程变更的键
        self._changed_keys: dict[str, set] = defaultdict(set)
        self._flush_event = threading.Event()
        self._shutdown = False
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        # 启动磁盘清理线程：定期删除长期不活跃的 thread 文件
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

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

    def _save_incremental_to_disk(self, thread_id: str, data: dict, changed_keys: set) -> None:
        """增量保存：只序列化变更的键，减少 CPU 和内存开销。

        如果磁盘文件不存在或变更范围过大（>30%），回退到全量保存。
        """
        fp = self._file_path(thread_id)
        try:
            total_keys = len(data.get("storage", {}).get(thread_id, {})) + \
                        len(data.get("writes", {})) + len(data.get("blobs", {}))
            # 变更比例过高时回退全量保存
            if not fp.exists() or not changed_keys or (total_keys > 0 and len(changed_keys) / total_keys > 0.3):
                self._save_to_disk(thread_id, data)
                return

            # 读取现有文件
            with open(fp, "r", encoding="utf-8") as f:
                existing = json.load(f)

            # 增量更新：只覆盖变更的部分
            for key in changed_keys:
                if key.startswith("storage:"):
                    _, tid, ns, cp_id = key.split(":", 3)
                    existing.setdefault("storage", {}).setdefault(tid, {}).setdefault(ns, {})[cp_id] = \
                        self._serialize_checkpoint(data["storage"][tid][ns][cp_id])
                elif key.startswith("writes:"):
                    _, wkey = key.split(":", 1)
                    existing["writes"][wkey] = self._serialize_writes(data["writes"][self._unpack_key(wkey)])
                elif key.startswith("blobs:"):
                    _, bkey = key.split(":", 1)
                    existing["blobs"][bkey] = self._serialize_blob(data["blobs"][self._unpack_key(bkey)])

            with open(fp, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, default=self._json_default)
        except (OSError, json.JSONDecodeError, KeyError):
            # 增量失败时回退到全量保存
            self._save_to_disk(thread_id, data)

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
        """执行实际刷盘：优先使用增量保存，减少序列化开销"""
        with self._lock:
            dirty_list = list(self._dirty)
            self._dirty.clear()
            # 取出变更键记录
            changed = {}
            for tid in dirty_list:
                changed[tid] = self._changed_keys.pop(tid, set())
        for tid in dirty_list:
            data = self._cache.get(tid)
            if data is not None:
                if changed.get(tid):
                    self._save_incremental_to_disk(tid, data, changed[tid])
                else:
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

    @staticmethod
    def _pack_key(*parts) -> str:
        """将元组键打包为字符串，避免 ast.literal_eval 开销"""
        return "\x00".join(str(p) for p in parts)

    @staticmethod
    def _unpack_key(key_str: str) -> tuple:
        """将字符串键解包为元组"""
        return tuple(key_str.split("\x00"))

    def _deserialize_storage(self, data: dict) -> dict:
        """将 JSON 数据反序列化为内部存储结构

        serde.dumps_typed 返回 (type_name, bytes) 元组，需要分别还原。
        使用 \x00 分隔的字符串键替代 str(tuple) + ast.literal_eval，减少 CPU 开销。
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
            tid, ns, cp_id = self._unpack_key(key_str)
            for inner_key_str, (tid_w, ch, val_list, tpath) in writes.items():
                task_id, idx = self._unpack_key(inner_key_str)
                result["writes"][(tid, ns, cp_id)][(task_id, int(idx))] = (
                    tid_w, ch, (val_list[0], self._from_b64(val_list[1])), tpath
                )
        # blobs: (thread_id, checkpoint_ns, channel, version) -> (type, bytes)
        for key_str, (typ, val_b64) in data.get("blobs", {}).items():
            tid, ns, ch, ver = self._unpack_key(key_str)
            # version 在 checkpoint 中是 int，但反序列化后可能是 str，统一转为 int 以匹配
            try:
                ver = int(ver)
            except (ValueError, TypeError):
                pass
            result["blobs"][(tid, ns, ch, ver)] = (typ, self._from_b64(val_b64))
        return result

    def _serialize_storage(self, data: dict) -> dict:
        """将内部存储结构序列化为 JSON 可存储格式

        serde.dumps_typed 返回 (type_name, bytes) 元组，需要分别序列化。
        使用 \x00 分隔的字符串键替代 str(tuple)，减少序列化开销。
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
            outer_key = self._pack_key(tid, ns, cp_id)
            result["writes"][outer_key] = {}
            for (task_id, idx), (tid_w, ch, val_tuple, tpath) in writes.items():
                inner_key = self._pack_key(task_id, idx)
                result["writes"][outer_key][inner_key] = [
                    tid_w, ch, [val_tuple[0], self._to_b64(val_tuple[1])], tpath
                ]
        for key, (typ, val_bytes) in data["blobs"].items():
            tid, ns, ch, ver = key
            result["blobs"][self._pack_key(tid, ns, ch, ver)] = [typ, self._to_b64(val_bytes)]
        return result

    @staticmethod
    def _to_b64(data: bytes) -> str:
        import base64
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def _from_b64(s: str) -> bytes:
        import base64
        return base64.b64decode(s.encode("ascii"))

    @staticmethod
    def _serialize_checkpoint(cp_data: tuple) -> list:
        """序列化单个检查点数据"""
        cp_tuple, meta_tuple, parent = cp_data
        return [
            [cp_tuple[0], JsonFileSaver._to_b64(cp_tuple[1])],
            [meta_tuple[0], JsonFileSaver._to_b64(meta_tuple[1])],
            parent,
        ]

    @staticmethod
    def _serialize_writes(writes: dict) -> dict:
        """序列化单个 writes 块"""
        result = {}
        for (task_id, idx), (tid_w, ch, val_tuple, tpath) in writes.items():
            inner_key = JsonFileSaver._pack_key(task_id, idx)
            result[inner_key] = [
                tid_w, ch, [val_tuple[0], JsonFileSaver._to_b64(val_tuple[1])], tpath
            ]
        return result

    @staticmethod
    def _serialize_blob(blob: tuple) -> list:
        """序列化单个 blob"""
        typ, val_bytes = blob
        return [typ, JsonFileSaver._to_b64(val_bytes)]

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

    def _prune_checkpoints(self, thread_id: str, checkpoint_ns: str) -> int:
        """裁剪指定线程的旧检查点，保留最近 max_checkpoints 个。
        同时清理孤儿 writes 和 blobs。
        返回删除的检查点数量。
        """
        data = self._cache.get(thread_id)
        if data is None:
            return 0

        checkpoints = data["storage"].get(thread_id, {}).get(checkpoint_ns, {})
        if len(checkpoints) <= self.max_checkpoints:
            return 0

        # 按 checkpoint_id 排序，保留最新的 max_checkpoints 个
        sorted_ids = sorted(checkpoints.keys())
        to_keep = set(sorted_ids[-self.max_checkpoints:])
        removed = 0

        # 删除旧检查点及其 writes
        for cp_id in sorted_ids:
            if cp_id in to_keep:
                continue
            del checkpoints[cp_id]
            removed += 1
            # 清理对应的 writes
            data["writes"].pop((thread_id, checkpoint_ns, cp_id), None)

        # 清理孤儿 blobs：收集剩余检查点引用的所有 (channel, version)
        active_versions: set[tuple[str, str]] = set()
        stored = data["storage"].get(thread_id, {})
        for ns, cps in stored.items():
            for cp_id, (cp_tuple, _meta_tuple, _parent) in cps.items():
                checkpoint = self.serde.loads_typed(cp_tuple)
                for ch, ver in checkpoint.get("channel_versions", {}).items():
                    active_versions.add((ch, ver))

        # 移除不再被任何检查点引用的 blob
        orphan_keys = []
        for (tid, ns, ch, ver) in data["blobs"]:
            if tid == thread_id and (ch, ver) not in active_versions:
                orphan_keys.append((tid, ns, ch, ver))
        for key in orphan_keys:
            del data["blobs"][key]

        return removed

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
        cp_id = checkpoint["id"]

        for k, v in new_versions.items():
            blob_key = (thread_id, checkpoint_ns, k, v)
            data["blobs"][blob_key] = (
                self.serde.dumps_typed(values[k]) if k in values else ("empty", b"")
            )
            # 记录 blob 变更
            self._changed_keys[thread_id].add(f"blobs:{self._pack_key(*blob_key)}")

        data["storage"][thread_id][checkpoint_ns].update(
            {
                cp_id: (
                    self.serde.dumps_typed(c),
                    self.serde.dumps_typed(get_checkpoint_metadata(config, metadata)),
                    config["configurable"].get("checkpoint_id"),  # parent
                )
            }
        )
        # 记录 storage 变更
        self._changed_keys[thread_id].add(f"storage:{thread_id}:{checkpoint_ns}:{cp_id}")

        # 裁剪旧检查点，防止无限增长
        self._prune_checkpoints(thread_id, checkpoint_ns)

        # 标记脏数据，由后台线程异步写入磁盘
        self._mark_dirty(thread_id)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": cp_id,
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

        has_new = False
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
            has_new = True

        if has_new:
            # 记录 writes 变更
            self._changed_keys[thread_id].add(f"writes:{self._pack_key(*outer_key)}")
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
    # 异步方法
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

    def _cleanup_loop(self) -> None:
        """后台清理线程：每天扫描一次，删除超过 max_file_age_days 未修改的 thread 文件"""
        while not self._shutdown:
            # 每 6 小时检查一次
            time.sleep(21600)
            if self._shutdown:
                break
            self._cleanup_old_files()

    def _cleanup_old_files(self) -> int:
        """删除超过保留期限的旧文件，返回删除数量"""
        cutoff = time.time() - self.max_file_age_days * 86400
        deleted = 0
        for fp in self.save_dir.glob("*.json"):
            try:
                if fp.stat().st_mtime < cutoff:
                    # 如果文件对应的 thread 还在内存缓存中，先卸载
                    thread_id = fp.stem
                    with self._lock:
                        if thread_id in self._cache:
                            del self._cache[thread_id]
                    fp.unlink()
                    deleted += 1
            except OSError:
                pass
        return deleted

    def close(self) -> None:
        """安全关闭：停止后台刷盘线程并确保所有数据落盘"""
        if self._shutdown:
            return
        self._shutdown = True
        self._flush_event.set()
        self._flush_thread.join(timeout=5.0)
        if hasattr(self, "_cleanup_thread"):
            self._cleanup_thread.join(timeout=1.0)
        self._do_flush()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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
                "max_checkpoints_per_thread": self.max_checkpoints,
                "save_dir": str(self.save_dir),
                "disk_files": len(list(self.save_dir.glob("*.json"))),
                "dirty_threads": len(self._dirty),
            }