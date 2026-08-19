from langchain_core.messages import SystemMessage

from orchestrator.tool_wrapper import with_resilience
from tools.protocol_settlement.aging_pms import aging_analysis, aging_and_notice
from tools.search import bocha_search
from tools.ar_recon import ar_recon
from tools.batch_scheduler import batch_scheduler

from tools.ctrip_commission_reconcile.ctrip_commission import ctrip_commission
from tools.daily_ar import daily_ar_processing
from tools.credit_card_recon import credit_card_recon
from tools.data_integration import data_integration
from state import AgentState
from llm import get_llm

TOOLS = [
    with_resilience(bocha_search, retries=2, timeout=30),
    with_resilience(ar_recon, retries=2, timeout=120),
    with_resilience(aging_analysis, retries=2, timeout=120),
    with_resilience(aging_and_notice, retries=2, timeout=120),
    with_resilience(ctrip_commission, retries=2, timeout=120),
    with_resilience(daily_ar_processing, retries=2, timeout=60),
    with_resilience(credit_card_recon, retries=2, timeout=120),
    with_resilience(data_integration, retries=1, timeout=30),
    with_resilience(batch_scheduler, retries=1, timeout=600),
]

SYSTEM_PROMPT = 'You are a hotel AR accounting AI assistant. Use tools to help with reconciliation, aging analysis, credit card matching, etc. Respond in Chinese.'

def agent(state: AgentState) -> dict:
    llm = get_llm()
    llm_with_tools = llm.bind_tools(TOOLS)
    response = llm_with_tools.invoke([SystemMessage(content=SYSTEM_PROMPT)] + state['messages'])
    return {'messages': [response]}