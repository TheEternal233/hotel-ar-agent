from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    thread_id: str = ""
    uploaded_files: list[str] = []

class ChatResponse(BaseModel):
    response: str
    thread_id: str = ""

class TaskRequest(BaseModel):
    module: str
    file_paths: list[str] = []
    thread_id: str = ""

class OtaReconRequest(BaseModel):
    ota_path: str
    pms_path: str

class AgingRequest(BaseModel):
    receivable_path: str
    as_of_date: str = ""

class CardReconRequest(BaseModel):
    bank_statement_path: str
    pms_card_path: str

class CtripRequest(BaseModel):
    settlement_path: str
    pms_path: str = ""

class InvoiceRequest(BaseModel):
    receivable_path: str
    invoice_type: str = "普通发票"

class CorpReconRequest(BaseModel):
    receivable_path: str

class ConfigRequest(BaseModel):
    action: str
    source_path: str = ""

class AgingNoticeRequest(BaseModel):
    receivable_path: str
    as_of_date: str = ""
    notice_month: str = ""
    notice_date: str = ""
    due_date: str = ""

class FileListResponse(BaseModel):
    ok: bool
    files: list = []
    detail: str = ""

class FileDeleteRequest(BaseModel):
    path: str