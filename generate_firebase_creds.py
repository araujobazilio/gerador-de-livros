import os
import json
from dotenv import load_dotenv

def generate_firebase_creds():
    """Gera o arquivo firebase-credentials.json a partir das variáveis de ambiente."""
    print("Gerando arquivo de credenciais do Firebase...")
    
    # Carrega as variáveis do arquivo .env
    load_dotenv()
    
    # Dicionário com as credenciais
    creds = {
        "type": os.getenv("FIREBASE_ADMIN_TYPE"),
        "project_id": os.getenv("FIREBASE_ADMIN_PROJECT_ID"),
        "private_key_id": os.getenv("FIREBASE_ADMIN_PRIVATE_KEY_ID"),
        "private_key": os.getenv("FIREBASE_ADMIN_PRIVATE_KEY").replace('\\n', '\n'),
        "client_email": os.getenv("FIREBASE_ADMIN_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_ADMIN_CLIENT_ID"),
        "auth_uri": os.getenv("FIREBASE_ADMIN_AUTH_URI"),
        "token_uri": os.getenv("FIREBASE_ADMIN_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("FIREBASE_ADMIN_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.getenv("FIREBASE_ADMIN_CLIENT_X509_CERT_URL"),
        "universe_domain": "googleapis.com"
    }
    
    # Salva o arquivo
    with open('firebase-credentials.json', 'w') as f:
        json.dump(creds, f, indent=2)
    
    print("✅ Arquivo firebase-credentials.json gerado com sucesso!")

if __name__ == "__main__":
    generate_firebase_creds()
