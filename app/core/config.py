import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Use NeonDB connection string. Default is for local testing if not provided.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/scarlet")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Secret key for sessions. Must be static across serverless cold starts.
    # We recommend setting this in Vercel Environment Variables.
    SECRET_KEY = os.environ.get("SECRET_KEY", "scarlet-super-secret-fallback-key-2026")
    
    # Enable connection pooling suitable for serverless environment if needed, 
    # but Neon usually handles this via pooling proxy.
    # We will stick to defaults unless specific serverless pooling settings are required.
    # SQLALCHEMY_ENGINE_OPTIONS = {
    #     "pool_pre_ping": True,
    # }
