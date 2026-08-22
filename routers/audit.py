"""审计日志查询 API"""

from fastapi import APIRouter, Query

from utils.audit_logger import audit

router = APIRouter(prefix="/api/audit", tags=["审计日志"])


@router.get("/logs")
async def list_logs(
    module: str = Query("", description="业务模块过滤"),
    action: str = Query("", description="操作过滤"),
    user: str = Query("", description="用户过滤"),
    status: str = Query("", description="状态过滤 (success/failed/blocked)"),
    days: int = Query(7, ge=1, le=365, description="查询最近N天"),
    limit: int = Query(200, ge=1, le=2000, description="每页条数"),
    offset: int = Query(0, ge=0, description="分页偏移"),
):
    """查询审计日志，支持多条件过滤和分页。"""
    records = audit.query(
        module=module, action=action, user=user,
        status=status, days=days, limit=limit, offset=offset,
    )
    total = audit.count(
        module=module, action=action, user=user,
        status=status, days=days,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": records,
    }


@router.get("/stats")
async def get_stats(days: int = Query(7, ge=1, le=365)):
    """获取审计统计摘要。"""
    return audit.stats(days=days)


@router.get("/modules")
async def list_modules():
    """列出所有可用的模块和操作类型。"""
    return {
        "modules": {
            "ota_recon": {"label": "OTA对账", "actions": ["upload", "preview", "match", "confirm", "reject", "export"]},
            "card_recon": {"label": "信用卡对账", "actions": ["upload", "preview", "match", "confirm", "reject", "export"]},
            "aging": {"label": "账龄分析", "actions": ["generate", "export"]},
            "ctrip": {"label": "携程佣金", "actions": ["upload", "preview", "confirm", "reject", "export"]},
            "invoice": {"label": "发票管理", "actions": ["upload", "generate", "export"]},
            "scheduler": {"label": "智能调度", "actions": ["start", "cancel", "approve", "reject", "complete", "fail"]},
            "chat": {"label": "AI对话", "actions": ["send", "tool_call", "block"]},
            "config": {"label": "系统配置", "actions": ["update", "reload"]},
            "files": {"label": "文件管理", "actions": ["upload", "validate", "delete"]},
            "auth": {"label": "认证登录", "actions": ["login", "logout"]},
        }
    }


@router.delete("/logs/{event_id}")
async def delete_log(event_id: str):
    """删除单条审计日志。"""
    ok = audit.delete_by_id(event_id)
    if ok:
        return {"deleted": True, "event_id": event_id}
    return {"deleted": False, "event_id": event_id, "reason": "未找到该记录"}


@router.post("/cleanup")
async def cleanup_audit_logs(retain_days: int = Query(90, ge=30, le=365)):
    """清理过期审计日志（管理员操作）。"""
    deleted = audit.cleanup(retain_days=retain_days)
    audit.log("config", "cleanup", f"清理审计日志，保留{retain_days}天，删除{deleted}个文件",
              user="admin", context={"retain_days": retain_days, "deleted_files": deleted})
    return {"deleted_files": deleted, "retain_days": retain_days}