import os
import json
import logging
import pandas as pd
from datetime import datetime
from flask import Flask, request, jsonify
import stripe
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar variáveis de ambiente
load_dotenv()

# Configurar Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Usar o segredo do webhook do Stripe
webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_ce4d371b9b6e0eca440edf5899427bd6bfbba23e15d6c8f5775de5a9b6af6062")

# Arquivo CSV para armazenar usuários pagantes
ARQUIVO_USUARIOS = os.getenv("ARQUIVO_USUARIOS", "usuarios.csv")

# Inicializar Flask app
app = Flask(__name__)

def inicializar_arquivo_csv():
    """Inicializa o arquivo CSV se não existir"""
    if not os.path.exists(ARQUIVO_USUARIOS):
        df = pd.DataFrame(columns=["email", "status", "data_pagamento", "valor", "produto", "metadata"])
        df.to_csv(ARQUIVO_USUARIOS, index=False)
        logger.info(f"Arquivo {ARQUIVO_USUARIOS} criado com sucesso")

def registrar_pagamento_csv(email, status="pago", metadata=None):
    """Registra um pagamento no arquivo CSV"""
    try:
        inicializar_arquivo_csv()
        df = pd.read_csv(ARQUIVO_USUARIOS)
        
        # Verificar se o email já existe
        if email in df["email"].values:
            # Atualizar status
            df.loc[df["email"] == email, "status"] = status
            df.loc[df["email"] == email, "data_pagamento"] = datetime.now().isoformat()
            if metadata:
                df.loc[df["email"] == email, "metadata"] = json.dumps(metadata)
        else:
            # Adicionar novo usuário
            novo_usuario = {
                "email": email,
                "status": status,
                "data_pagamento": datetime.now().isoformat(),
                "valor": metadata.get("valor", "") if metadata else "",
                "produto": metadata.get("produto", "") if metadata else "",
                "metadata": json.dumps(metadata) if metadata else ""
            }
            df = pd.concat([df, pd.DataFrame([novo_usuario])], ignore_index=True)
        
        # Salvar no CSV
        df.to_csv(ARQUIVO_USUARIOS, index=False)
        logger.info(f"Pagamento registrado para {email}")
        return True
    except Exception as e:
        logger.error(f"Erro ao registrar pagamento no CSV: {e}")
        return False

# Configuração do Firebase
try:
    # Verificar se o Firebase já foi inicializado
    firebase_admin.get_app()
except ValueError:
    # Inicializar o Firebase
    firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_credentials:
        cred = credentials.Certificate(firebase_credentials)
    else:
        # Fallback para variáveis de ambiente individuais
        cred = credentials.Certificate({
            "type": os.getenv("FIREBASE_ADMIN_TYPE"),
            "project_id": os.getenv("FIREBASE_ADMIN_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_ADMIN_PRIVATE_KEY_ID"),
            "private_key": os.getenv("FIREBASE_ADMIN_PRIVATE_KEY", "").replace("\\n", "\n"),
            "client_email": os.getenv("FIREBASE_ADMIN_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_ADMIN_CLIENT_ID"),
            "auth_uri": os.getenv("FIREBASE_ADMIN_AUTH_URI"),
            "token_uri": os.getenv("FIREBASE_ADMIN_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.getenv("FIREBASE_ADMIN_AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": os.getenv("FIREBASE_ADMIN_CLIENT_X509_CERT_URL")
        })
    firebase_admin.initialize_app(cred)

db = firestore.client()

def atualizar_assinatura_firestore(email, status=True, metadata=None):
    """Atualiza o status de assinatura no Firestore"""
    try:
        doc_ref = db.collection('usuarios').document(email)
        dados = {
            'email': email,
            'assinatura_ativa': status,
            'data_atualizacao': datetime.now().isoformat()
        }
        if metadata:
            dados['metadata'] = metadata
        doc_ref.set(dados, merge=True)
        logger.info(f"Assinatura atualizada no Firestore para {email}")
        return True
    except Exception as e:
        logger.error(f"Erro ao atualizar Firestore: {e}")
        return False

def handle_checkout_session(session):
    """Processa uma sessão de checkout do Stripe"""
    try:
        # Extrair informações da sessão
        customer_email = session.get("customer_details", {}).get("email")
        if not customer_email:
            logger.warning("Email do cliente não encontrado na sessão")
            return False
        
        # Registrar no CSV e Firestore
        metadata = {
            "valor": session.get("amount_total", 0) / 100,  # Converter de centavos para reais
            "produto": session.get("metadata", {}).get("produto", "Assinatura Premium"),
            "session_id": session.get("id"),
            "payment_status": session.get("payment_status")
        }
        
        registrar_pagamento_csv(customer_email, status="pago", metadata=metadata)
        atualizar_assinatura_firestore(customer_email, status=True, metadata=metadata)
        
        logger.info(f"Checkout processado com sucesso para {customer_email}")
        return True
    except Exception as e:
        logger.error(f"Erro ao processar checkout: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        # Payload inválido
        logger.error(f"Payload inválido: {e}")
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        # Assinatura inválida
        logger.error(f"Assinatura inválida: {e}")
        return jsonify({'error': 'Invalid signature'}), 400
    
    # Processar o evento
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        if handle_checkout_session(session):
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'error': 'Failed to process checkout session'}), 500
    
    # Para outros tipos de eventos
    return jsonify({'status': 'received'}), 200

@app.route('/webhook/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    # Inicializar o arquivo CSV
    inicializar_arquivo_csv()
    
    # Obter porta do ambiente (para Cloud Run) ou usar 5000 como padrão
    port = int(os.environ.get('PORT', 5000))
    
    print(f'🚀 Servidor Flask de webhook rodando na porta {port}')
    print(f'🔑 Webhook secret: {webhook_secret[:10]}...' if webhook_secret else '⚠️  STRIPE_WEBHOOK_SECRET não configurado')
    print(f'📝 Arquivo CSV: {ARQUIVO_USUARIOS}')
    
    # Iniciar o servidor Flask
    app.run(host='0.0.0.0', port=port, debug=False)
