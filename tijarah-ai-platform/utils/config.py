"""utils/config.py"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv()

@dataclass
class AppConfig:
    db_server          : str  = "localhost"
    db_name            : str  = "SmartInventory_DWH"
    db_driver          : str  = "ODBC Driver 17 for SQL Server"
    db_trusted         : bool = True
    db_username        : str  = ""
    db_password        : str  = ""
    gmail_sender       : str  = ""
    gmail_app_password : str  = ""
    report_recipients  : list = field(default_factory=list)
    # Student Bedrock Gateway model selection.
    # The API key itself is NOT stored here — it's read directly from the
    # SBG_API_KEY environment variable inside utils/ai_service.py. These
    # two fields exist mainly so the background scheduler (which has no
    # Flask session to read a model from) can pick the same model the
    # interactive app uses, by setting LLM_MODEL / LLM_MAX_TOKENS in .env.
    llm_model          : str  = "anthropic.claude-sonnet-4-6"
    llm_max_tokens     : int  = 2000

def load_config() -> AppConfig:
    r = os.getenv("REPORT_RECIPIENTS","")
    return AppConfig(
        db_server         = os.getenv("DB_SERVER","localhost"),
        db_name           = os.getenv("DB_NAME","SmartInventory_DWH"),
        db_driver         = os.getenv("DB_DRIVER","ODBC Driver 17 for SQL Server"),
        db_trusted        = os.getenv("DB_TRUSTED_CONNECTION","yes").lower() in ("yes","true","1"),
        db_username       = os.getenv("DB_USERNAME",""),
        db_password       = os.getenv("DB_PASSWORD",""),
        gmail_sender      = os.getenv("GMAIL_SENDER",""),
        gmail_app_password= os.getenv("GMAIL_APP_PASSWORD",""),
        report_recipients = [x.strip() for x in r.split(",") if x.strip()],
        llm_model         = os.getenv("LLM_MODEL", "anthropic.claude-sonnet-4-6"),
        llm_max_tokens    = int(os.getenv("LLM_MAX_TOKENS", "2000")),
    )