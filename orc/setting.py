import os
from dataclasses import dataclass

@dataclass
class Setting:
    """
    A class to represent a setting for the orchestrator parameters.

    Attributes:
        name (str): The name of the setting.
        value (str): The value of the setting.
    """
    LLM_API_KEY: str = os.getenv('GROQ_API_KEY', 'default_key')
    
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'default_database_url')
    DATABASE_USER: str = os.getenv('DATABASE_USER', 'default_user')
    DATABASE_PASSWORD: str = os.getenv('DATABASE_PASSWORD', 'default_password')
