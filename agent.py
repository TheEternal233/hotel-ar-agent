from langchain_core.messages import SystemMessage

from tools.protocol_settlement.aging_pms import aging_analysis
from tools.search import bocha_search
from tools.ar_recon import ar_recon

from tools.ctrip_commission import ctrip_commission
from tools.daily_check import daily_night_audit_check
from tools.daily_ar import daily_ar_processing
from tools.credit_card_recon import credit_card_recon
from tools.data_integration import data_integration
from state import AgentState
from llm import get_llm

TOOLS = [bocha_search, ar_recon, aging_analysis, ctrip_commission, daily_night_audit_check, daily_ar_processing, credit_card_recon, data_integration]

SYSTEM_PROMPT = 'You are a hotel AR accounting AI assistant. Use tools to help with reconciliation, aging analysis, credit card matching, etc. Respond in Chinese.'

def agent(state: AgentState) -> dict:
    llm = get_llm()
    llm_with_tools = llm.bind_tools(TOOLS)
    response = llm_with_tools.invoke([SystemMessage(content=SYSTEM_PROMPT)] + state['messages'])
    return {'messages': [response]}
