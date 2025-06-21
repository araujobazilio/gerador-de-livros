import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

class Config:
    # Configurações do Firebase
    FIREBASE_CONFIG = {
        "apiKey": os.getenv("FIREBASE_API_KEY"),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
        "projectId": os.getenv("FIREBASE_PROJECT_ID"),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET"),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": os.getenv("FIREBASE_APP_ID"),
        "measurementId": os.getenv("FIREBASE_MEASUREMENT_ID")
    }
    
    # Configurações do Stripe
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
    STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
    
    # Outras configurações
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
    SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:8501/success")
    CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "http://localhost:8501/cancel")
