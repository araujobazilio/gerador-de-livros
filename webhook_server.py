from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import stripe
import firebase_admin
from firebase_admin import firestore, credentials
import os
from dotenv import load_dotenv
import logging
import pandas as pd
from datetime import datetime

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar variáveis de ambiente
load_dotenv()

# Configurar Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Usar o segredo do webhook do Stripe CLI em desenvolvimento local
# O Stripe CLI fornece o segredo na saída quando você executa 'stripe listen'
webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_ce4d371b9b6e0eca440edf5899427bd6bfbba23e15d6c8f5775de5a9b6af6062")

# Arquivo CSV para armazenar usuários pagantes
ARQUIVO_USUARIOS = os.getenv("ARQUIVO_USUARIOS", "usuarios.csv")

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
            novo = pd.DataFrame([[email, status, datetime.now().isoformat(), 0, "Premium", json.dumps(metadata) if metadata else "{}"]], 
                               columns=["email", "status", "data_pagamento", "valor", "produto", "metadata"])
            df = pd.concat([df, novo], ignore_index=True)
        
        df.to_csv(ARQUIVO_USUARIOS, index=False)
        logger.info(f"Usuário {email} registrado com sucesso no CSV")
        return True
    except Exception as e:
        logger.error(f"Erro ao registrar pagamento no CSV: {str(e)}")
        return False

# Configuração do Firestore

try:
    # Verificar se o Firebase já foi inicializado
    if not firebase_admin._apps:
        cred = credentials.Certificate({
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
        logger.info("✅ Firebase Admin inicializado com sucesso")
    
    db = firestore.client()
    logger.info("✅ Firestore inicializado com sucesso")
    
except Exception as e:
    logger.error(f"❌ Erro ao inicializar o Firebase: {str(e)}")
    db = None

class WebhookHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Stripe-Signature')
        self.end_headers()
    
    def do_OPTIONS(self):
        self._set_headers(200)
    
    def handle_checkout_session(self, session):
        try:
            # Obter informações do usuário
            user_id = session.get('client_reference_id')
            email = session.get('customer_email')
            
            # Se não tiver email, tentar buscar do cliente
            if not email and session.get('customer'):
                try:
                    customer = stripe.Customer.retrieve(session.get('customer'))
                    email = customer.get('email')
                except Exception as e:
                    logger.error(f"Erro ao buscar cliente: {str(e)}")
            
            # Verificar se temos pelo menos um identificador
            if not user_id and not email:
                logger.error("Nem ID do usuário nem email encontrados na sessão")
                return False
            
            # Preparar metadados
            metadata = session.get('metadata', {})
            if not metadata:
                metadata = {}
                
            if user_id:
                metadata['user_id'] = user_id
            if email:
                metadata['email'] = email
                
            # Registrar no CSV
            if email:
                registrar_pagamento_csv(email, "pago", metadata)
            
            # Atualizar no Firebase se possível
            if user_id and db:
                logger.info(f"Atualizando assinatura para o usuário: {user_id}")
                
                # Atualizar o status da assinatura no Firestore
                user_ref = db.collection('users').document(user_id)
                user_ref.update({
                    'assinatura': True,
                    'data_assinatura': firestore.SERVER_TIMESTAMP,
                    'tipo_assinatura': 'vitalicio',
                    'status_pagamento': 'pago',
                    'ultima_atualizacao': firestore.SERVER_TIMESTAMP
                })
                
                logger.info(f"✅ Assinatura ativada com sucesso para o usuário: {user_id}")
            elif not db:
                logger.warning("Firestore não inicializado, salvando apenas no CSV")
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao processar checkout.session.completed: {str(e)}", exc_info=True)
            return False
        
    def do_POST(self):
        if self.path == '/webhook':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # Verificar se o webhook_secret está configurado
            if not webhook_secret:
                error_msg = "STRIPE_WEBHOOK_SECRET não configurado"
                logger.error(error_msg)
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": error_msg}).encode())
                return

            # Obter a assinatura do cabeçalho
            sig_header = self.headers.get('Stripe-Signature')
            if not sig_header:
                error_msg = "Cabeçalho Stripe-Signature não encontrado"
                logger.error(error_msg)
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": error_msg}).encode())
                return

            try:
                logger.info(f"🔔 Novo evento recebido: {post_data.decode('utf-8')}")
                
                # Verificar a assinatura do webhook
                event = stripe.Webhook.construct_event(
                    post_data, sig_header, webhook_secret
                )
                
                logger.info(f"🔔 Evento processado: {event['type']}")
                
                # Processar o evento
                if event['type'] == 'checkout.session.completed':
                    self.handle_checkout_session(event['data']['object'])
                
                self._set_headers(200)
                self.wfile.write(json.dumps({'status': 'success'}).encode())
                
            except ValueError as e:
                error_msg = f"Dados do webhook inválidos: {str(e)}"
                logger.error(error_msg)
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": error_msg}).encode())
            except stripe.error.SignatureVerificationError as e:
                error_msg = f"Assinatura do webhook inválida: {str(e)}"
                logger.error(error_msg)
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": error_msg}).encode())
            except Exception as e:
                error_msg = f"Erro ao processar webhook: {str(e)}"
                logger.error(error_msg, exc_info=True)
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": "Erro interno do servidor"}).encode())
        else:
            self._set_headers(404)
            self.wfile.write(b'Not Found')

def run(server_class=HTTPServer, handler_class=WebhookHandler, port=None):
    """Inicia o servidor HTTP"""
    try:
        # Usar a porta definida pelo Cloud Run ou 5000 por padrão
        if port is None:
            port = int(os.getenv('PORT', 5000))
        
        server_address = ('', port)
        httpd = server_class(server_address, handler_class)
        logger.info(f'Iniciando servidor webhook na porta {port}...')
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info('Servidor encerrado')
        httpd.server_close()

if __name__ == "__main__":
    inicializar_arquivo_csv()
    print(f'🚀 Servidor de webhook rodando na porta {int(os.getenv("PORT", 5000))}')
    print(f'🔑 Webhook secret: {webhook_secret[:10]}...' if webhook_secret else '⚠️  STRIPE_WEBHOOK_SECRET não configurado')
    print(f'📝 Arquivo CSV: {ARQUIVO_USUARIOS}')
    run()