import os
import stripe
from dotenv import load_dotenv
import json
import firebase_admin
from firebase_admin import firestore

# Carregar variáveis de ambiente
load_dotenv()

# Configurar Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# Inicializar Firebase
if not firebase_admin._apps:
    cred = firebase_admin.credentials.Certificate({
        "type": os.getenv("FIREBASE_ADMIN_TYPE"),
        "project_id": os.getenv("FIREBASE_ADMIN_PROJECT_ID"),
        "private_key_id": os.getenv("FIREBASE_ADMIN_PRIVATE_KEY_ID"),
        "private_key": os.getenv("FIREBASE_ADMIN_PRIVATE_KEY").replace('\\n', '\n'),
        "client_email": os.getenv("FIREBASE_ADMIN_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_ADMIN_CLIENT_ID"),
        "auth_uri": os.getenv("FIREBASE_ADMIN_AUTH_URI"),
        "token_uri": os.getenv("FIREBASE_ADMIN_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("FIREBASE_ADMIN_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.getenv("FIREBASE_ADMIN_CLIENT_X509_CERT_URL")
    })
    firebase_admin.initialize_app(cred)

db = firestore.client()

def handle_webhook(event):
    """
    Processa eventos do webhook do Stripe.
    """
    try:
        # Verificar a assinatura do webhook
        signature = event['headers'].get('stripe-signature')
        if not signature:
            return {'statusCode': 400, 'body': 'Assinatura não encontrada'}

        # Obter o payload do evento
        payload = event['body']
        
        try:
            # Verificar a assinatura do webhook
            webhook_event = stripe.Webhook.construct_event(
                payload, signature, endpoint_secret
            )
        except ValueError as e:
            # Payload inválido
            return {'statusCode': 400, 'body': 'Payload inválido'}
        except stripe.error.SignatureVerificationError as e:
            # Assinatura inválida
            return {'statusCode': 400, 'body': 'Assinatura inválida'}

        # Processar o evento
        if webhook_event['type'] == 'checkout.session.completed':
            session = webhook_event['data']['object']
            return handle_checkout_session_completed(session)

        # Outros tipos de eventos podem ser processados aqui
        
        return {'statusCode': 200, 'body': 'Evento recebido'}
        
    except Exception as e:
        print(f"Erro ao processar webhook: {str(e)}")
        return {'statusCode': 500, 'body': 'Erro interno do servidor'}

def handle_checkout_session_completed(session):
    """
    Processa o evento de conclusão de checkout.
    """
    try:
        # Obter o ID do usuário a partir dos metadados ou client_reference_id
        user_id = session.get('client_reference_id')
        
        if not user_id:
            print("ID do usuário não encontrado na sessão")
            return {'statusCode': 400, 'body': 'ID do usuário não encontrado'}
        
        # Atualizar o status de assinatura no Firestore
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'assinatura': True,
            'data_assinatura': firestore.SERVER_TIMESTAMP,
            'tipo_assinatura': 'vitalicio',
            'status_pagamento': 'pago'
        })
        
        print(f"Status de assinatura atualizado para o usuário {user_id}")
        return {'statusCode': 200, 'body': 'Assinatura ativada com sucesso'}
        
    except Exception as e:
        print(f"Erro ao processar checkout.session.completed: {str(e)}")
        return {'statusCode': 500, 'body': 'Erro ao processar assinatura'}

def lambda_handler(event, context):
    """
    Função principal para o AWS Lambda.
    """
    return handle_webhook(event)

# Para teste local
if __name__ == "__main__":
    # Este bloco é apenas para testes locais
    # Em produção, use o AWS Lambda
    from flask import Flask, request, jsonify
    
    app = Flask(__name__)
    
    @app.route('/webhook', methods=['POST'])
    def webhook():
        event = {
            'headers': dict(request.headers),
            'body': request.data.decode('utf-8')
        }
        result = handle_webhook(event)
        return jsonify(result), result['statusCode']
    
    print("Servidor webhook rodando em http://localhost:5000/webhook")
    app.run(port=5000)
