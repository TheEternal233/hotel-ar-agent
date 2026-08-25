"""信用卡对账 — 微信 / 支付宝 / OTA卡 / 预付卡 四种付款方式对账

入口文件。负责文件识别、数据流编排、对账调度、报告输出。
流程：
  读取 PMS报表 + POS机银行流水
  → 分别按 4 种付款方式统计数量与金额
  → 同种付款方式数量匹配后对比金额，相同则对平、不同则计算差额
  → 输出对账差异表格
挂应收、挂房账、挂团队、OC、ENT、YFD 等付款方式不统计。
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from langchain.tools import tool
    _HAS_LANGCHAIN = True
except ImportError:
    _HAS_LANGCHAIN = False
    def tool(fn):
        return fn

from tools import BASE_DIR
from tools.credit_card_recon.parser import _read_pms_report, _read_pos_statement, _read_yfd_pms, _read_yfd_bank
from tools.credit_card_recon.matcher import _reconcile_channel
from tools.credit_card_recon.reporter import _generate_recon_report
from tools.credit_card_recon.constants import RECON_PAYMENT_METHODS

logger=logging.getLogger(__name__)
def _classify_files(data_dir):
    """扫描目录，识别 PMS报表 与 POS机银行流水、YFD各渠道文件 文件

    Returns:
        dict: {"pms_report": filename|None, "pos": filename|None}
    """
    files = [f for f in os.listdir(data_dir) if f.endswith(".xlsx") and not f.startswith("~$")]
    mapping = {
        "pms_report": None,
        "pos": None,
        "yfd_alipay_pms": None,
        "yfd_alipay_bank":None,
        "yfd_wechat_pms":None,
        "yfd_wechat_bank":None,


    }
    for f in files:
        fl = f.lower()
        if "pms报表" in fl:
            mapping["pms_report"] = f
        elif "pos" in fl or ("银行流水" in fl and "yfd" not in fl):
            mapping["pos"] = f
        elif "yfd" in fl and "alipay" in fl:
            if "pms" in fl and "应收" in fl:
                mapping["yfd_alipay_pms"] = f
            elif "银行流水" in fl:
                mapping["yfd_alipay_bank"] = f
        elif "yfd" in fl and "wechat" in fl:
            if "pms" in fl and "应收" in fl:
                mapping["yfd_wechat_pms"] = f
            elif "银行流水" in fl:
                mapping["yfd_wechat_bank"] = f
    return mapping


def _run_recon(pms_path, pos_path):
    """执行对账核心流程：解析 → 按 4 种付款方式对账 → 生成报告"""
    # 1) 读取 PMS报表 与 POS银行流水，按 4 种付款方式分组
    logger.info("开始通用对账: PMS=%s, POS=%s", pms_path, pos_path)
    pms_groups = _read_pms_report(pms_path)
    pos_groups = _read_pos_statement(pos_path)

    # 2) 对 4 种付款方式逐一对账（数量匹配 + 金额对比 + 差额）
    recon_results = []
    for method in RECON_PAYMENT_METHODS:
        pms_txs = pms_groups.get(method, [])
        pos_txs = pos_groups.get(method, [])
        # 只对至少一方有数据的付款方式生成对账结果
        if pms_txs or pos_txs:
            try:
                result=_reconcile_channel(method,pms_txs,pos_txs)
                recon_results.append(result)
            except Exception:
                logger.exception("渠道[%s]对账失败，已跳过", method)

    # 3) 输出对账差异表格
    return recon_results

def _run_yfd_recon(pms_path, bank_path,channel_name,channel_keyword):
    """执行 YFD 单渠道对账：解析->服用通用匹配逻辑->返回单条结果"""
    logger.info("开始YFD对账: channel=%s, PMS=%s, Bank=%s", channel_name, pms_path, bank_path)
    pms_txs = _read_yfd_pms(pms_path,channel_keyword)
    bank_txs=_read_yfd_bank(bank_path)
    return _reconcile_channel(channel_name, pms_txs, bank_txs)


def batch_card_recon(data_dir=None):
    """批量信用卡对账：通用PMS+POS+YFD ALIPAY/WECHAT 独立对账"""
    if data_dir is None:
        data_dir = os.path.join(BASE_DIR, "data", "清远", "信用卡对账")
    if not os.path.exists(data_dir):
        return f"错误：数据目录不存在: {data_dir}"
    files = _classify_files(data_dir)
    all_results = []
    errors = []

    tasks = []

    # 通用对账
    if files["pms_report"] and files["pos"]:
        tasks.append(("通用PMS/POS对账", lambda: _run_recon(
            os.path.join(data_dir, files["pms_report"]),
            os.path.join(data_dir, files["pos"]),
        )))

    # YFD ALIPAY独立对账
    if files["yfd_alipay_pms"] and files["yfd_alipay_bank"]:
        tasks.append(("YFD支付宝对账", lambda: [_run_yfd_recon(
            os.path.join(data_dir, files["yfd_alipay_pms"]),
            os.path.join(data_dir, files["yfd_alipay_bank"]),
            "YFD支付宝", "YFD 支付宝",
        )]))

    # YFD WECHAT 独立对账
    if files["yfd_wechat_pms"] and files["yfd_wechat_bank"]:
        tasks.append(("YFD微信对账", lambda: [_run_yfd_recon(
            os.path.join(data_dir, files["yfd_wechat_pms"]),
            os.path.join(data_dir, files["yfd_wechat_bank"]),
            "YFD微信", "YFD 微信",
        )]))

    if tasks:
        with ThreadPoolExecutor(max_workers=min(len(tasks), 3)) as executor:
            future_to_name = {executor.submit(task_fn): name for name, task_fn in tasks}
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    all_results.extend(future.result())
                except Exception:
                    logger.exception(f"{name}失败")
                    errors.append(f"{name}失败")

    if not all_results:
        err_detail = "；".join(errors) if errors else "未找到任何可对账的文件组合"
        return f"错误：{err_detail}"

    result = _generate_recon_report(all_results)
    if errors:
        result += f"\n\n警告：以下渠道对账失败 — {'; '.join(errors)}"
    return result






@tool
def credit_card_recon(bank_statement_path: str = "", pms_card_path: str = "") -> str:
    """信用卡对账：对微信/支付宝/OTA卡/预付卡 4 种付款方式对账。

    当用户上传了文件时，必须传入文件路径参数：
    - bank_statement_path: POS机银行流水文件路径
    - pms_card_path: PMS报表文件路径
    仅当用户未提供任何文件时才可不传参（走批量模式）。
    """
    if not bank_statement_path and not pms_card_path:
        return batch_card_recon()

    for p in (bank_statement_path, pms_card_path):
        if not p or not os.path.exists(p):
            return f"error: 文件不存在 {p}"

    bank_lower=bank_statement_path.lower()
    pms_lower=pms_card_path.lower()

    #YFD ALIPAY独立对账
    if "yfd" in bank_lower and "alipay" in bank_lower and "yfd" in pms_lower and "alipay" in pms_lower:
        recon_result=_run_yfd_recon(pms_card_path, bank_statement_path, "YFD支付宝","YFD 支付宝")

        result=_generate_recon_report([recon_result])

    #YFD WECHAT独立对账
    elif "yfd" in bank_lower and "wechat" in bank_lower and "yfd" in pms_lower and "wechat" in pms_lower:
        recon_result=_run_yfd_recon(pms_card_path,bank_statement_path,"YFD微信","YFD 微信")
        result=_generate_recon_report([recon_result])
    else:
        #通用PMS+POS对账
        recon_results=_run_recon(pms_card_path, bank_statement_path)
        result=_generate_recon_report(recon_results)


    # 清理上传文件（仅限项目目录内的文件，防止误删）
    _cleanup_temp_files(bank_statement_path, pms_card_path)
    return result


def _cleanup_temp_files(*paths):
    """安全清理临时文件：仅删除 BASE_DIR 子目录下的文件"""
    base = Path(BASE_DIR).resolve()
    for p in paths:
        if not p:
            continue
        try:
            fp = Path(p).resolve()
            try:
                fp.relative_to(base)
            except ValueError:
                continue
            if fp.exists():
                os.remove(p)
                logger.info("已清理临时文件: %s", p)
        except OSError:
            logger.warning("清理临时文件失败: %s", p)