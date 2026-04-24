import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Project settings
    PROJECT_NAME: str = "UIAA Prototype"
    VERSION: str = "0.1.0"
    DEBUG_MODE: bool = True

settings = Settings()
