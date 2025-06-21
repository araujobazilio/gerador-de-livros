import streamlit as st
import os
import json
import base64
import time
import random
import string
import re
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore, auth
import bcrypt
import stripe
from openai import OpenAI
import hashlib
import glob
import webbrowser
from firebase_setup import db, get_user_by_email, update_subscription_status
from app import gerar_livro_generico

# Função para atualizar o status da assinatura no Firestore
def atualizar_status_assinatura(usuario_id, status):
    """
    Atualiza o status de assinatura de um usuário no Firestore.
    
    Args:
        usuario_id (str): ID do usuário no Firestore
        status (bool): Novo status da assinatura (True = ativa, False = inativa)
        
    Returns:
        bool: True se a atualização foi bem-sucedida, False caso contrário
    """
    try:
        if not usuario_id:
            print("❌ ID do usuário não fornecido para atualização de assinatura")
            return False
            
        user_ref = db.collection('users').document(usuario_id)
        user_ref.update({
            'assinatura': status,
            'data_atualizacao': firestore.SERVER_TIMESTAMP,
            'status_pagamento': 'pago' if status else 'cancelado'
        })
        print(f"✅ Status de assinatura atualizado para o usuário {usuario_id}: {status}")
        return True
    except Exception as e:
        print(f"❌ Erro ao atualizar status de assinatura: {str(e)}")
        return False
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import json

# Carregar variáveis de ambiente
load_dotenv()

# Configurar Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_PAYMENT_LINK = os.getenv("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/test")

# Arquivo CSV para armazenar usuários pagantes
ARQUIVO_USUARIOS = os.getenv("ARQUIVO_USUARIOS", "usuarios.csv")

# Inicializar cliente OpenAI (será configurado pelo usuário)
client = None

# Configuração da página (deve ser a primeira chamada Streamlit)
st.set_page_config(
    page_title="Gerador de Livros para Amazon KDP",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# === BLOCO DE AUTENTICAÇÃO COM FIREBASE ===

def hash_senha(senha):
    """Gera o hash da senha para armazenamento seguro."""
    return hashlib.sha256(senha.encode()).hexdigest()

def cadastrar_usuario(nome, email, senha):
    """Cadastra um novo usuário no Firebase."""
    try:
        # Verifica se o usuário já existe
        existing_user = get_user_by_email(email)
        if existing_user:
            return False, "E-mail já cadastrado."
        
        # Cria um novo usuário
        user_data = {
            'nome': nome,
            'email': email,
            'senha_hash': hash_senha(senha),
            'assinatura': False,
            'data_cadastro': time.strftime('%Y-%m-%d %H:%M:%S'),
            'is_admin': False,
            'reset_token': None,
            'reset_token_expiry': None
        }
        
        # Adiciona o usuário ao Firestore
        if db:
            db.collection('users').add(user_data)
            return True, "Usuário cadastrado com sucesso!"
        else:
            return False, "Erro ao conectar ao banco de dados."
    except Exception as e:
        return False, f"Erro ao cadastrar usuário: {str(e)}"

def autenticar_usuario(email, senha):
    """Autentica o usuário e verifica o status de assinatura no Firebase."""
    try:
        user = get_user_by_email(email)
        if user and user.get('senha_hash') == hash_senha(senha):
            # Verifica se é admin
            is_admin = user.get('email') == os.getenv('ADMIN_EMAIL')
            return {
                'id': user.get('id'),
                'nome': user.get('nome'),
                'email': email,
                'assinatura': user.get('assinatura', False),
                'is_admin': is_admin
            }
        return None
    except Exception as e:
        print(f"Erro na autenticação: {e}")
        return None

def solicitar_redefinicao_senha(email):
    """Solicita a redefinição de senha para o e-mail informado."""
    try:
        user = get_user_by_email(email)
        if not user:
            return False, "E-mail não cadastrado."
        
        # Gera um token de redefinição (simplificado - em produção, use uma biblioteca segura)
        reset_token = hashlib.sha256(f"{email}{time.time()}".encode()).hexdigest()
        reset_token_expiry = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        
        # Atualiza o usuário com o token de redefinição
        user_ref = db.collection('users').document(user['id'])
        user_ref.update({
            'reset_token': reset_token,
            'reset_token_expiry': reset_token_expiry
        })
        
        # Em produção, envie um e-mail com o link de redefinição
        # Aqui apenas simulamos o envio
        reset_link = f"{os.getenv('APP_URL', 'http://localhost:8501')}?reset_token={reset_token}"
        print(f"Link de redefinição (simulado): {reset_link}")
        
        return True, "Um link de redefinição foi enviado para o seu e-mail."
    except Exception as e:
        return False, f"Erro ao processar a solicitação: {str(e)}"

def redefinir_senha_com_token(token, nova_senha):
    """Redefine a senha usando o token de redefinição."""
    try:
        # Encontra o usuário com o token válido
        users_ref = db.collection('users')
        query = users_ref.where('reset_token', '==', token).limit(1)
        docs = query.stream()
        
        for doc in docs:
            user_data = doc.to_dict()
            # Verifica se o token ainda é válido
            if user_data.get('reset_token_expiry') and \
               datetime.fromisoformat(user_data['reset_token_expiry']) > datetime.utcnow():
                # Atualiza a senha e limpa o token
                doc.reference.update({
                    'senha_hash': hash_senha(nova_senha),
                    'reset_token': None,
                    'reset_token_expiry': None
                })
                return True, "Senha redefinida com sucesso!"
        
        return False, "Token inválido ou expirado."
    except Exception as e:
        return False, f"Erro ao redefinir a senha: {str(e)}"

# Inicialização das variáveis de sessão
if 'usuario' not in st.session_state:
    st.session_state.usuario = {"id": None, "nome": "", "email": "", "assinatura": False, "is_admin": False}
if 'aba_atual' not in st.session_state:
    st.session_state.aba_atual = "login"

# === INTERFACE DE AUTENTICAÇÃO ===
    
    st.markdown("---")
    if st.button("Voltar para o login"):
        st.session_state.aba_atual = "login"
        st.rerun()

def fazer_logout():
    """Realiza o logout do usuário."""
    st.session_state.usuario = {"id": None, "nome": "", "email": "", "assinatura": False, "is_admin": False}
    st.session_state.aba_atual = "login"
    st.rerun()

# === DETECÇÃO DE LIVRO EM ANDAMENTO ===

def verificar_livro_em_andamento():
    """Verifica se há um livro em andamento e exibe opção para continuar."""
    livros_existentes = sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'livro_*')), reverse=True)
    livro_ultimo = None
    metadata_ultimo = None
    
    if livros_existentes:
        for pasta in livros_existentes:
            metadata_path = os.path.join(pasta, 'metadata.json')
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        metadata_ultimo = json.load(f)
                        livro_ultimo = pasta
                        break
                except Exception as e:
                    print(f"Erro ao ler metadata.json: {e}")
    
    if livro_ultimo and metadata_ultimo and st.session_state.usuario["id"] is None:
        with st.container():
            st.warning("⚠️ Livro em andamento detectado!")
            st.write(f"**Tema:** {metadata_ultimo.get('tema', 'Desconhecido')}")
            st.write(f"**Autor:** {metadata_ultimo.get('autor', 'Desconhecido')}")
            
            if st.button('Continuar último livro'):
                # Preencher os campos do formulário ao retomar
                st.session_state.tema_livro = metadata_ultimo.get('tema', '')
                st.session_state.autor_livro = metadata_ultimo.get('autor', '')
                st.session_state.email_autor_livro = metadata_ultimo.get('email', '')
                st.session_state.genero_livro = metadata_ultimo.get('genero', '')
                st.session_state.estilo_livro = metadata_ultimo.get('estilo', '')
                st.session_state.publico_alvo_livro = metadata_ultimo.get('publico_alvo', '')
                st.session_state.descricao_livro = metadata_ultimo.get('descricao', '')
                st.session_state.retomar_livro = True
                st.success('Campos preenchidos! Faça login para continuar a geração do livro.')
                st.rerun()
        
        st.markdown("<div style='background:#FFF4F4;padding:10px;border-radius:6px;margin:10px 0;color:#c00;font-weight:bold;'>"
                   "Se a sessão cair, faça login novamente e clique em 'Continuar último livro' para retomar de onde parou.</div>", 
                   unsafe_allow_html=True)
        st.markdown("---")

# === ROTAS DA APLICAÇÃO ===

def criar_sessao_checkout(email_cliente):
    """
    Cria uma sessão de checkout no Stripe para processamento de pagamento.
    
    Args:
        email_cliente (str): E-mail do cliente para envio da confirmação
        
    Returns:
        str: URL da sessão de checkout ou None em caso de erro
    """
    try:
        # Verificar se a chave da API do Stripe está configurada
        if not stripe.api_key:
            error_msg = "Chave da API do Stripe não configurada. Verifique a variável STRIPE_SECRET_KEY no arquivo .env"
            st.error(error_msg)
            print(f"ERRO: {error_msg}")
            return None
            
        # Configurar URLs de retorno
        app_url = os.getenv('APP_URL', 'http://localhost:8501')
        success_url = os.getenv('STRIPE_SUCCESS_URL', f"{app_url}?payment=success&session_id={{CHECKOUT_SESSION_ID}}")
        cancel_url = os.getenv('STRIPE_CANCEL_URL', f"{app_url}?payment=cancelled")
        
        # Validar URLs
        if not success_url or not cancel_url:
            error_msg = "URLs de retorno do Stripe não configuradas corretamente. Verifique as variáveis STRIPE_SUCCESS_URL e STRIPE_CANCEL_URL no .env"
            st.error(error_msg)
            print(f"ERRO: {error_msg}")
            return None

        # Verificar se o preço do produto está configurado
        stripe_price_id = os.getenv('STRIPE_PRICE_ID')
        if not stripe_price_id:
            error_msg = "ID do preço do produto não configurado. Verifique a variável STRIPE_PRICE_ID no .env"
            st.error(error_msg)
            print(f"ERRO: {error_msg}")
            return None
            
        # Verificar se o e-mail do cliente é válido
        if not email_cliente or "@" not in email_cliente:
            error_msg = "E-mail do cliente inválido"
            st.error(error_msg)
            print(f"ERRO: {error_msg}")
            return None
        
        try:
            # Tentar criar a sessão de checkout
            session_params = {
                "payment_method_types": ["card"],
                "line_items": [{
                    'price': stripe_price_id,
                    'quantity': 1,
                }],
                "mode": 'subscription' if stripe_price_id.startswith('price_') and 'monthly' in stripe_price_id.lower() else 'payment',
                "success_url": success_url,
                "cancel_url": cancel_url,
                "customer_email": email_cliente,
                "metadata": {
                    'user_email': email_cliente,
                    'app_name': 'Gerador de Livros',
                    'environment': os.getenv('ENVIRONMENT', 'development')
                },
                "payment_intent_data": {
                    'setup_future_usage': 'off_session',
                    'metadata': {'no_webhook': 'true'}
                }
            }
            
            # Adicionar configuração de assinatura se for um preço recorrente
            if 'monthly' in stripe_price_id.lower() or 'yearly' in stripe_price_id.lower():
                session_params["subscription_data"] = {
                    'metadata': {'no_webhook': 'true'}
                }
            
            # Criar a sessão
            session = stripe.checkout.Session.create(**session_params)
            
            # Log de sucesso
            print(f"Sessão de checkout criada com sucesso: {session.id}")
            print(f"URL de sucesso: {success_url}")
            print(f"URL de cancelamento: {cancel_url}")
            
            return session.url
            
        except stripe.error.StripeError as e:
            # Erros específicos do Stripe
            error_msg = f"Erro na API do Stripe: {str(e)}"
            st.error("Ocorreu um erro ao processar seu pagamento. Por favor, tente novamente mais tarde.")
            print(f"ERRO STRIPE: {error_msg}")
            return None
            
    except Exception as e:
        # Erros inesperados
        error_msg = f"Erro inesperado ao criar sessão de pagamento: {str(e)}"
        st.error("Ocorreu um erro inesperado. Por favor, entre em contato com o suporte.")
        print(f"ERRO INESPERADO: {error_msg}")
        return None
        return None

def verificar_pagamento(session_id):
    """
    Verifica o status de um pagamento no Stripe e atualiza o status da assinatura.
    
    Args:
        session_id (str): ID da sessão de checkout do Stripe
        
    Returns:
        tuple: (bool, str) - (sucesso, mensagem)
    """
    try:
        if not session_id or not isinstance(session_id, str):
            logger.error("ID da sessão inválido ou não fornecido")
            return False, "ID da sessão inválido"
            
        logger.info(f"Verificando status do pagamento para a sessão: {session_id}")
        
        # Recupera a sessão do Stripe com expansão de dados relacionados
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=[
                'payment_intent',
                'subscription',
                'customer',
                'line_items'
            ]
        )
        
        logger.debug(f"Dados completos da sessão: {json.dumps(session, default=str)}")
        
        # Verifica se a sessão foi encontrada
        if not session:
            logger.error(f"Sessão não encontrada: {session_id}")
            return False, "Sessão de pagamento não encontrada"
            
        # Obtém metadados importantes
        metadata = getattr(session, 'metadata', {}) or {}
        usuario_id = metadata.get('usuario_id') or session.client_reference_id
        email = session.customer_email or (session.customer.email if hasattr(session.customer, 'email') else None)
        
        logger.info(f"Verificando pagamento - Sessão: {session.id}, Status: {session.payment_status}, Email: {email}")
        
        # Verifica se o pagamento foi bem-sucedido
        if session.payment_status == 'paid':
            if not email:
                error_msg = "Email do cliente não encontrado na sessão"
                logger.error(error_msg)
                return False, error_msg
                
            logger.info(f"✅ Pagamento confirmado para {email}")
            
            try:
                # Atualiza o status da assinatura no Firebase
                logger.info("Atualizando status da assinatura no Firebase...")
                success = update_subscription_status(email, True)
                
                if success:
                    logger.info(f"✅ Assinatura atualizada com sucesso para {email}")
                    
                    # Atualiza a sessão local se o usuário estiver logado
                    if 'usuario' in st.session_state:
                        st.session_state.usuario['assinatura'] = True
                        st.session_state.usuario['status_pagamento'] = 'pago'
                        logger.info("✅ Sessão local atualizada com sucesso")
                    
                    # Registra dados adicionais para auditoria
                    logger.info(f"Dados da transação - ID: {session.id}, Valor: {session.amount_total/100:.2f} {session.currency.upper()}, "
                              f"Método: {session.payment_method_types[0] if session.payment_method_types else 'N/A'}")
                    
                    # Retorna sucesso com mensagem detalhada
                    return True, "Pagamento confirmado com sucesso! Sua assinatura está ativa."
                else:
                    error_msg = f"Falha ao atualizar assinatura no Firebase para {email}"
                    logger.error(error_msg)
                    return False, error_msg
                    
            except Exception as firebase_error:
                error_msg = f"Erro ao atualizar assinatura: {str(firebase_error)}"
                logger.error(error_msg, exc_info=True)
                return False, error_msg
                
        elif session.payment_status in ['unpaid', 'no_payment_required']:
            logger.warning(f"Pagamento não realizado ou não requerido. Status: {session.payment_status}")
            return False, "Pagamento não realizado ou pendente de confirmação."
            
        else:
            logger.warning(f"Status de pagamento não confirmado: {session.payment_status}")
            return False, f"Status do pagamento: {session.payment_status}"
            
    except stripe.error.StripeError as e:
        error_msg = f"Erro na API do Stripe: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, "Erro ao processar a verificação de pagamento. Tente novamente mais tarde."
        
    except Exception as e:
        error_msg = f"Erro inesperado ao verificar pagamento: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, "Ocorreu um erro inesperado. Por favor, entre em contato com o suporte."

def pagina_principal():
    """Exibe a página principal do aplicativo."""
    # Verificar se o usuário está logado
    if "usuario" not in st.session_state or st.session_state.usuario["id"] is None:
        st.warning("Você precisa fazer login para acessar esta página.")
        st.session_state.aba_atual = "login"
        st.rerun()
        return
    
    # Sidebar com informações e navegação
    with st.sidebar:
        st.image("https://img.freepik.com/free-vector/hand-drawn-flat-design-stack-books_23-2149334862.jpg", width=200)
        st.markdown("## Menu de Navegação")
        
        # Opções de navegação
        opcao = st.radio(
            "Escolha uma opção:",
            [" Criar Novo Livro", " Meus Livros", " Sobre o Aplicativo", " Configurações"]
        )
        
        st.markdown("---")
        st.markdown("### Como usar")
        st.markdown("""
        1. Escolha 'Criar Novo Livro' no menu
        2. Preencha as informações do autor
        3. Digite o tema desejado para o livro
        4. Escolha o gênero, estilo e público-alvo
        5. Adicione uma descrição para o livro
        6. Clique em "Gerar Livro"
        7. Aguarde enquanto nossos agentes trabalham
        8. Baixe o livro gerado pronto para KDP
        """)
        
        # Campo para a chave da API da OpenAI
        st.markdown("---")
        st.markdown("### Chave da API da OpenAI")
        st.markdown("""
        Para utilizar este aplicativo, você precisa fornecer sua própria chave da API da OpenAI.
        Você pode obter uma chave em: [OpenAI API Keys](https://platform.openai.com/api-keys)
        """)
        
        # Campo para a chave da API com opção de ocultar
        api_key = st.text_input("Chave da API da OpenAI:", type="password", help="Sua chave será usada apenas para esta sessão e não será armazenada.")
        
        # Salvar a chave na sessão
        if api_key:
            st.session_state.api_key = api_key
            st.success(" Chave da API configurada!")
        else:
            st.warning(" Você precisa fornecer uma chave da API da OpenAI para gerar livros.")
    
    # Conteúdo principal
    st.title(" Gerador de Livros para Amazon KDP")
    
    # Barra superior com informações do usuário e botão de logout
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"""
            <div style='background:#f0f2f6;padding:10px;border-radius:5px;margin-bottom:20px;'>
                <b>Usuário:</b> {st.session_state.usuario["nome"]} | 
                <b>Status:</b> {'Assinante ' if st.session_state.usuario["assinatura"] or st.session_state.usuario["is_admin"] else 'Não assinante '}
            </div>
        """, unsafe_allow_html=True)
    
    with col2:
        if st.button("Sair", key="btn_logout"):
            fazer_logout()
    
    # Roteamento baseado na opção selecionada no menu
    if "📝 Criar Novo Livro" in opcao:
        exibir_criar_livro()
    elif "📚 Meus Livros" in opcao:
        exibir_meus_livros()
    elif "ℹ️ Sobre o Aplicativo" in opcao:
        exibir_sobre()
    elif "⚙️ Configurações" in opcao:
        exibir_configuracoes()

def exibir_tela_assinatura():
    """Exibe a tela de assinatura"""
    st.warning("🔒 Acesso Restrito")
    st.markdown("""
    <div style='text-align:center; margin:2rem 0;'>
        <h3 style='color:#FF5A5F;'>Acesso Premium</h3>
        <p>Para acessar todas as funcionalidades do Gerador de Livros, você precisa de uma assinatura Premium.</p>
        <p>Por apenas <strong>R$ 97,00</strong> você terá acesso vitalício a todas as ferramentas!</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Colunas para os benefícios
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🎁 O que você recebe:")
        st.markdown("""
        - Acesso vitalício ao Gerador de Livros
        - Suporte prioritário
        - Atualizações futuras inclusas
        - Modelos exclusivos de livros
        - Guia de Publicação na Amazon KDP
        """)
    
    with col2:
        st.markdown("### 🚀 Funcionalidades Premium:")
        st.markdown("""
        - Geração ilimitada de livros
        - Exportação em múltiplos formatos
        - Capas profissionais
        - Revisão automática de texto
        - Otimização para KDP
        """)
    
    # Botão de assinatura
    st.markdown("<div style='text-align: center; margin: 2rem 0;'>", unsafe_allow_html=True)
    
    # Verifica se o usuário está logado
    if 'usuario' not in st.session_state or 'email' not in st.session_state.usuario:
        st.error("Você precisa estar logado para assinar.")
        if st.button("Fazer Login"):
            st.session_state.aba_atual = "login"
            st.rerun()
    else:
        # Se chegou até aqui, o usuário está logado e não tem assinatura ativa
        # Verifica se já existe um ID de sessão salvo
        if 'ultima_sessao_checkout' in st.session_state and st.session_state.ultima_sessao_checkout:
            # Se já existe uma sessão, verifica o status do pagamento
            with st.spinner("Verificando status do pagamento..."):
                success = verificar_pagamento(st.session_state.ultima_sessao_checkout)
                if success:
                    st.success("✅ Pagamento confirmado! Redirecionando...")
                    st.session_state.usuario['assinatura'] = True
                    st.session_state.aba_atual = "app"
                    st.rerun()
                    return
        
        # Se não tem sessão ou o pagamento não foi confirmado, mostra o botão de assinatura
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button("💳 Assinar Agora (R$ 97,00)", use_container_width=True, type="primary"):
                # Cria uma nova sessão de checkout
                if 'usuario' not in st.session_state or 'email' not in st.session_state.usuario:
                    st.error("Erro: Usuário não autenticado.")
                    return
                
                try:
                    # Cria a sessão de checkout no Stripe
                    session = stripe.checkout.Session.create(
                        payment_method_types=['card', 'pix'],
                        line_items=[{
                            'price': STRIPE_PRICE_ID,
                            'quantity': 1,
                        }],
                        mode='payment',
                        success_url=os.getenv('STRIPE_SUCCESS_URL') + '?session_id={CHECKOUT_SESSION_ID}',
                        cancel_url=os.getenv('STRIPE_CANCEL_URL'),
                        customer_email=st.session_state.usuario['email'],
                        client_reference_id=st.session_state.usuario['id'],
                        metadata={
                            'user_id': st.session_state.usuario['id'],
                            'email': st.session_state.usuario['email']
                        },
                        # Desabilita notificações de webhook para evitar dependência do webhook local
                        payment_intent_data={
                            'metadata': {
                                'user_id': st.session_state.usuario['id'],
                                'email': st.session_state.usuario['email']
                            }
                        },
                        allow_promotion_codes=True
                    )
                    
                    # Salva o ID da sessão para verificação posterior
                    st.session_state.ultima_sessao_checkout = session.id
                    
                    # Redireciona para o checkout
                    checkout_url = session.url
                    st.components.v1.html(f"""
                    <script>
                        window.open("{checkout_url}", "_blank");
                    </script>
                    """, height=0)
                    
                    # Instruções para o usuário
                    st.info("📱 Uma nova aba foi aberta para você completar o pagamento. Após o pagamento, você será redirecionado de volta para o aplicativo.")
                    
                except Exception as e:
                    st.error(f"Erro ao processar o pagamento: {str(e)}")
        
        with col2:
            # Botão para verificar o pagamento manualmente
            if st.button("✅ Já paguei, verificar", use_container_width=True):
                if 'ultima_sessao_checkout' in st.session_state and st.session_state.ultima_sessao_checkout:
                    with st.spinner("Verificando pagamento..."):
                        success = verificar_pagamento(st.session_state.ultima_sessao_checkout)
                        if success:
                            st.success("✅ Pagamento confirmado! Sua assinatura está ativa.")
                            st.balloons()
                            
                            # Atualiza o estado do usuário na sessão
                            if 'usuario' in st.session_state:
                                st.session_state.usuario['assinatura'] = True
                                
                            # Redireciona para a página principal
                            st.session_state.aba_atual = "app"
                            st.rerun()
                        else:
                            st.error("❌ Pagamento não confirmado. Se você já realizou o pagamento, aguarde alguns instantes e tente novamente.")
                else:
                    st.error("❌ Nenhuma sessão de checkout encontrada. Por favor, clique em 'Assinar Agora' primeiro.")
        
        st.markdown("""
        <div style='margin-top: 2rem; font-size: 0.9em; color: #666; text-align: center;'>
            <p>Pagamento seguro via Stripe | 7 dias de garantia incondicional</p>
            <p>Suporte 24/7 | Acesso imediato após a confirmação do pagamento</p>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Adiciona um botão para voltar ao início
    if st.button("← Voltar para o início"):
        st.session_state.aba_atual = "app"
        st.rerun()
    
    # Adiciona um botão para atualizar manualmente a assinatura (apenas para debug)
    if st.checkbox("Mostrar opções avançadas"):
        st.warning("Apenas para fins de depuração")
        if st.button("🔄 Atualizar status da assinatura manualmente"):
            if 'usuario' in st.session_state and 'email' in st.session_state.usuario:
                email = st.session_state.usuario['email']
                with st.spinner(f"Atualizando assinatura para {email}..."):
                    success = update_subscription_status(email, True)
                    if success:
                        st.success(f"✅ Assinatura atualizada com sucesso para {email}")
                        st.session_state.usuario['assinatura'] = True
                        st.session_state.aba_atual = "app"
                        st.rerun()
                    else:
                        st.error("❌ Falha ao atualizar assinatura")
            else:
                st.error("❌ Usuário não encontrado na sessão")
                
        # Exibe informações de debug
        st.write("### Informações de Sessão")
        st.write(f"Usuário: {st.session_state.get('usuario')}")
        st.write(f"Última sessão de checkout: {st.session_state.get('ultima_sessao_checkout')}")
        
        # Botão para limpar a sessão
        if st.button("🗑️ Limpar dados da sessão"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.success("✅ Sessão limpa com sucesso")
            st.rerun()

# === FUNÇÕES DAS SEÇÕES DO APLICATIVO ===

def exibir_criar_livro():
    """Exibe o formulário para criação de um novo livro."""
    st.header("📝 Criar Novo Livro")
    
    # Verifica se o usuário tem uma chave da API configurada
    if 'api_key' not in st.session_state or not st.session_state.api_key:
        st.warning("⚠️ Você precisa configurar sua chave da API da OpenAI para gerar livros.")
        return
    
    # Formulário para criação do livro
    with st.form("form_livro"):
        st.subheader("Informações do Livro")
        
        # Campos do formulário
        col1, col2 = st.columns(2)
        
        with col1:
            tema = st.text_input("Tema do livro*", value=st.session_state.get('tema_livro', ''))
            autor = st.text_input("Nome do autor*", value=st.session_state.get('autor_livro', ''))
            email_autor = st.text_input("E-mail do autor*", value=st.session_state.get('email_autor_livro', ''))
            genero = st.selectbox(
                "Gênero do livro*",
                ["Infantil", "Ficção", "Não-ficção", "Autoajuda", "Negócios", "Tecnologia", "Outro"],
                index=["Infantil", "Ficção", "Não-ficção", "Autoajuda", "Negócios", "Tecnologia", "Outro"].index(st.session_state.get('genero_livro', 'Infantil'))
            )
        
        with col2:
            estilo = st.selectbox(
                "Estilo de escrita*",
                ["Descontraído", "Formal", "Acadêmico", "Narrativo", "Poético", "Técnico"],
                index=["Descontraído", "Formal", "Acadêmico", "Narrativo", "Poético", "Técnico"].index(st.session_state.get('estilo_livro', 'Descontraído'))
            )
            publico_alvo = st.selectbox(
                "Público-alvo*",
                ["Crianças (3-6 anos)", "Crianças (7-10 anos)", "Adolescentes", "Jovens adultos", "Adultos", "Todas as idades"],
                index=["Crianças (3-6 anos)", "Crianças (7-10 anos)", "Adolescentes", "Jovens adultos", "Adultos", "Todas as idades"].index(st.session_state.get('publico_alvo_livro', 'Crianças (3-6 anos)'))
            )
            formato = st.selectbox(
                "Formato do livro*",
                ["Capa dura", "Capa mole", "E-book", "Áudio-livro"],
                index=["Capa dura", "Capa mole", "E-book", "Áudio-livro"].index(st.session_state.get('formato_livro', 'Capa dura'))
            )
        
        # Número de capítulos
        num_capitulos = st.slider(
            "Número de capítulos",
            min_value=1,
            max_value=20,
            value=st.session_state.get('num_capitulos', 5),
            step=1,
            help="Selecione o número de capítulos para o livro."
        )
        
        # Descrição do livro
        descricao = st.text_area(
            "Descrição do livro*",
            value=st.session_state.get('descricao_livro', ''),
            help="Descreva o conteúdo que você gostaria que o livro tivesse. Seja o mais detalhista possível.",
            height=150
        )
        
        # Botão de envio
        btn_gerar = st.form_submit_button("✨ Gerar Livro", use_container_width=True)
    
    # Processamento do formulário
    if btn_gerar:
        # Validação dos campos obrigatórios
        if not tema or not autor or not email_autor or not descricao:
            st.error("⚠️ Por favor, preencha todos os campos obrigatórios (*).")
            return
        
        # Salva os dados na sessão
        st.session_state.tema_livro = tema
        st.session_state.autor_livro = autor
        st.session_state.email_autor_livro = email_autor
        st.session_state.genero_livro = genero
        st.session_state.estilo_livro = estilo
        st.session_state.publico_alvo_livro = publico_alvo
        st.session_state.descricao_livro = descricao
        st.session_state.formato_livro = formato
        st.session_state.num_capitulos = num_capitulos
        
        # Inicia o processo de geração do livro
        gerar_livro()

def gerar_livro():
    """Gera o livro com base nos parâmetros fornecidos."""
    # Cria um container para o progresso
    progress_placeholder = st.empty()
    result_placeholder = st.empty()
    
    # Define as etapas do processo
    etapas = [
        "Preparando estrutura do livro...",
        f"Gerando {st.session_state.num_capitulos} capítulos...",
        "Criando introdução e conclusão...",
        "Revisando o conteúdo...",
        "Formatando para publicação...",
        "Finalizando..."
    ]
    
    # Função de callback para atualizar o progresso
    def callback_progresso(etapa, mensagem=None):
        with progress_placeholder.container():
            st.markdown(f"**Etapa {etapa}/{len(etapas)}: {mensagem or etapas[etapa-1]}")
            st.progress(etapa / len(etapas))
    
    try:
        # Inicia a geração do livro
        with st.spinner("Iniciando geração do livro. Este processo pode levar alguns minutos..."):
            # Chama a função de geração do livro da API
            conteudo_livro = gerar_livro_generico(
                tema=st.session_state.tema_livro,
                api_key=st.session_state.api_key,
                autor=st.session_state.autor_livro,
                email_autor=st.session_state.email_autor_livro,
                genero=st.session_state.genero_livro,
                estilo=st.session_state.estilo_livro,
                publico_alvo=st.session_state.publico_alvo_livro,
                descricao=st.session_state.descricao_livro,
                formato=st.session_state.formato_livro,
                num_capitulos=st.session_state.num_capitulos,
                callback=callback_progresso
            )
            
            # Verifica se o conteúdo foi gerado corretamente
            if not conteudo_livro or len(conteudo_livro) < 100:
                st.error("❌ O conteúdo gerado parece estar vazio ou incompleto. Tente novamente com uma descrição mais detalhada.")
                return
            
            # Salva o conteúdo na sessão
            st.session_state.conteudo_livro = conteudo_livro
            st.session_state.livro_gerado = True
            
            # Exibe mensagem de sucesso
            st.success("✅ Livro gerado com sucesso!")
            st.balloons()
            
            # Exibe o conteúdo gerado
            with st.expander("📖 Visualizar Livro", expanded=True):
                st.markdown(conteudo_livro, unsafe_allow_html=True)
            
            # Opções de download
            st.download_button(
                label="⬇️ Baixar em PDF",
                data=conteudo_livro.encode('utf-8'),
                file_name=f"{st.session_state.tema_livro}.txt",
                mime="text/plain",
                help="Baixe o livro em formato de texto simples."
            )
            
            # Botão para gerar um novo livro
            if st.button("🔄 Gerar Outro Livro", type="secondary"):
                st.session_state.livro_gerado = False
                st.rerun()
    
    except Exception as e:
        st.error(f"❌ Ocorreu um erro ao gerar o livro: {str(e)}")
        st.error("Verifique sua conexão com a internet e tente novamente.")

def exibir_meus_livros():
    """Exibe a lista de livros gerados pelo usuário."""
    st.header("📚 Meus Livros")
    
    # Verifica se há livros na sessão
    if 'livros_gerados' not in st.session_state:
        st.session_state.livros_gerados = []
    
    # Se não há livros, exibe mensagem
    if not st.session_state.livros_gerados:
        st.info("Você ainda não gerou nenhum livro. Vá para 'Criar Novo Livro' para começar!")
        return
    
    # Exibe a lista de livros gerados
    for i, livro in enumerate(st.session_state.livros_gerados):
        with st.expander(f"📖 {livro['titulo']} - {livro['data']}"):
            st.markdown(f"**Gênero:** {livro['genero']}")
            st.markdown(f"**Estilo:** {livro['estilo']}")
            st.markdown(f"**Público-alvo:** {livro['publico_alvo']}")
            
            # Botões de ação
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button(f"👁️ Visualizar", key=f"ver_{i}"):
                    st.session_state.livro_selecionado = i
                    st.session_state.aba_atual = "visualizar_livro"
                    st.rerun()
            
            with col2:
                st.download_button(
                    label="⬇️ Baixar",
                    data=livro['conteudo'].encode('utf-8'),
                    file_name=f"{livro['titulo']}.txt",
                    mime="text/plain",
                    key=f"baixar_{i}",
                    use_container_width=True
                )
            
            with col3:
                if st.button(f"🗑️ Excluir", key=f"excluir_{i}", type="secondary", use_container_width=True):
                    st.session_state.livros_gerados.pop(i)
                    st.success("Livro removido com sucesso!")
                    st.rerun()

def exibir_sobre():
    """Exibe informações sobre o aplicativo."""
    st.header("ℹ️ Sobre o Aplicativo")
    
    st.markdown("""
    ## Gerador de Livros para Amazon KDP
    
    Este aplicativo utiliza Inteligência Artificial para criar livros personalizados de qualquer gênero e estilo, 
    prontos para publicação na Amazon KDP (Kindle Direct Publishing).
    
    ### Como Funciona
    
    1. **Crie seu livro**: Preencha o formulário com as informações do seu livro.
    2. **Gere o conteúdo**: Nosso sistema irá criar um livro único baseado nas suas preferências.
    3. **Revise e personalize**: Faça ajustes finais no conteúdo gerado.
    4. **Publique**: Baixe o livro formatado e publique na Amazon KDP.
    
    ### Recursos Principais
    
    - Geração de livros em minutos
    - Múltiplos gêneros e estilos
    - Personalização completa
    - Formatação otimizada para KDP
    - Download em vários formatos
    
    ### Suporte
    
    Em caso de dúvidas ou problemas, entre em contato com nosso suporte:
    - E-mail: suporte@geradordelivros.com
    - WhatsApp: (11) 98765-4321
    
    ### Termos de Uso
    
    Ao utilizar este aplicativo, você concorda com nossos Termos de Serviço e Política de Privacidade.
    O conteúdo gerado é de sua responsabilidade como autor.
    """)

def exibir_configuracoes():
    """Exibe as configurações do aplicativo."""
    st.header("⚙️ Configurações")
    
    with st.form("form_configuracoes"):
        st.subheader("Configurações da Conta")
        
        # Informações do usuário
        if 'usuario' in st.session_state:
            st.markdown(f"**Nome:** {st.session_state.usuario.get('nome', 'Não informado')}")
            st.markdown(f"**E-mail:** {st.session_state.usuario.get('email', 'Não informado')}")
            st.markdown(f"**Data de Cadastro:** {st.session_state.usuario.get('data_cadastro', 'Não disponível')}")
            
            # Status da assinatura
            status_assinatura = "Ativa ✅" if st.session_state.usuario.get('assinatura', False) else "Inativa ❌"
            st.markdown(f"**Status da Assinatura:** {status_assinatura}")
            
            # Botão para gerenciar assinatura
            if st.form_submit_button("🔄 Gerenciar Assinatura", use_container_width=True):
                st.session_state.aba_atual = "assinatura"
                st.rerun()
        
        st.divider()
        
        # Configurações de privacidade
        st.subheader("Privacidade")
        
        # Opção para excluir conta
        if st.form_submit_button("🗑️ Excluir Minha Conta", type="secondary", use_container_width=True):
            if st.toggle("Tem certeza que deseja excluir sua conta? Esta ação não pode ser desfeita."):
                # Aqui você pode adicionar a lógica para excluir a conta do usuário
                st.error("Funcionalidade de exclusão de conta não implementada ainda.")

def novo_livro():
    """Limpa a sessão e inicia um novo livro."""
    st.session_state.livro_gerado = False
    st.session_state.conteudo_livro = None
    st.session_state.tema_livro = ""
    st.session_state.autor_livro = ""
    st.session_state.email_autor_livro = ""
    st.session_state.genero_livro = ""
    st.session_state.estilo_livro = ""
    st.session_state.publico_alvo_livro = ""
    st.session_state.descricao_livro = ""
    st.session_state.formato_livro = ""
    st.rerun()

def exibir_barra_superior():
    """Exibe a barra superior com informações do usuário e opção de logout."""
    if 'usuario' not in st.session_state or not st.session_state.usuario:
        return
    
    st.markdown("""
    <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;'>
        <div>
            <span style='font-size:1.1rem'><b>Usuário:</b> {}</span> |
            <span style='font-size:1.1rem'><b>Assinatura:</b> {}</span>
        </div>
        <div>
            <button onclick="window.location.href='?logout=true'" style='background:#FF5A5F;color:white;border:none;padding:0.4rem 1rem;border-radius:0.3rem;font-weight:bold;cursor:pointer;'>Sair</button>
        </div>
    </div>
    """.format(
        st.session_state.usuario.get("nome", ""),
        "Ativa ✅" if st.session_state.usuario.get("assinatura", False) else "Inativa ❌"
    ), unsafe_allow_html=True)

# === ESTILOS CSS ===

def carregar_estilos():
    """Carrega os estilos CSS personalizados."""
    st.markdown("""
    <style>
        .main-header {
            font-size: 2.5rem;
            color: #FF5A5F;
            text-align: center;
            margin-bottom: 1rem;
        }
        .sub-header {
            font-size: 1.5rem;
            color: #484848;
            margin-bottom: 2rem;
            text-align: center;
        }
        .info-text {
            background-color: #F0F2F6;
            padding: 1rem;
            border-radius: 0.5rem;
            margin-bottom: 1rem;
        }
        .highlight {
            color: #FF5A5F;
            font-weight: bold;
        }
        .result-container {
            background-color: #F8F9FA;
            padding: 1.5rem;
            border-radius: 0.5rem;
            border: 1px solid #E0E0E0;
            margin-top: 2rem;
        }
        .chapter-title {
            font-size: 1.3rem;
            color: #484848;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
            font-weight: bold;
        }
        .book-content {
            white-space: pre-line;
            line-height: 1.6;
        }
        .tema-destaque {
            font-size: 1.2rem;
            color: #FF5A5F;
            font-weight: bold;
            background-color: #FFF4F4;
            padding: 0.5rem 1rem;
            border-radius: 0.3rem;
            display: inline-block;
            margin: 1rem 0;
        }
        .api-key-container {
            background-color: #F0F8FF;
            padding: 1rem;
            border-radius: 0.5rem;
            margin-bottom: 1rem;
            border: 1px solid #ADD8E6;
        }
        .progress-container {
            margin: 1.5rem 0;
        }
        .progress-step {
            margin-bottom: 0.8rem;
            padding: 0.8rem;
            border-radius: 0.3rem;
            background-color: #F8F9FA;
            border-left: 4px solid #E0E0E0;
        }
        .progress-step.active {
            border-left: 4px solid #FF5A5F;
            background-color: #FFF4F4;
        }
        .progress-step.completed {
            border-left: 4px solid #4CAF50;
            background-color: #F1F8E9;
        }
        .kdp-section {
            background-color: #FFF8E1;
            padding: 1rem;
            border-radius: 0.5rem;
            margin: 1.5rem 0;
            border: 1px solid #FFE082;
        }
        .author-section {
            background-color: #E8F5E9;
            padding: 1rem;
            border-radius: 0.5rem;
            margin: 1.5rem 0;
            border: 1px solid #C8E6C9;
        }
        .format-section {
            display: flex;
            flex-direction: column;
            gap: 0.8rem;
            margin: 1rem 0;
        }
        .download-button {
            margin-top: 1.5rem;
            padding: 0.8rem;
            background-color: #4CAF50;
            color: white;
            border-radius: 0.3rem;
            text-align: center;
            font-weight: bold;
        }
    </style>
    """, unsafe_allow_html=True)

# === CONFIGURAÇÕES INICIAIS ===

# Inicializar o cliente do Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
APP_URL = os.getenv("APP_URL", "http://localhost:8501")

# Configuração do Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-credentials.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# === FUNÇÕES DE AUTENTICAÇÃO ===





# === FUNÇÕES DO STRIPE ===

def criar_sessao_checkout(usuario_id, email, nome, preco_id=STRIPE_PRICE_ID):
    """
    Cria uma sessão de checkout do Stripe para assinatura.
    
    Args:
        usuario_id (str): ID do usuário no sistema
        email (str): E-mail do usuário
        nome (str): Nome do usuário
        preco_id (str): ID do preço no Stripe (opcional)
        
    Returns:
        str: URL da sessão de checkout ou None em caso de erro
    """
    try:
        logger.info(f"Iniciando criação de sessão de checkout para o usuário: {usuario_id} ({email})")
        
        # URL de sucesso e cancelamento
        success_url = f"{APP_URL}/?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{APP_URL}/assinatura?cancelado=true"
        
        # Metadados adicionais
        metadata = {
            'usuario_id': str(usuario_id),
            'usuario_nome': nome,
            'usuario_email': email,
            'tipo_assinatura': 'premium',
            'app_versao': '1.0.0',
            'origem': 'streamlit_app'
        }
        
        # Dados do cliente para o Stripe
        customer_data = {
            'email': email,
            'name': nome,
            'metadata': {
                'user_id': str(usuario_id),
                'app_name': 'Gerador de Livros',
                'signup_date': datetime.now().isoformat()
            }
        }
        
        logger.info(f"Criando sessão de checkout no Stripe para {email}")
        
        # Criar sessão de checkout
        session = stripe.checkout.Session.create(
            payment_method_types=['card', 'boleto'],
            line_items=[{
                'price': preco_id,
                'quantity': 1,
                'description': 'Assinatura Premium - Gerador de Livros'
            }],
            mode='subscription',
            customer_email=email,
            client_reference_id=str(usuario_id),
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
            subscription_data={
                'metadata': metadata,
                'trial_settings': {
                    'end_behavior': {
                        'missing_payment_method': 'cancel'
                    }
                }
            },
            allow_promotion_codes=True,
            customer_creation='always',
            expires_at=int((datetime.now() + timedelta(hours=24)).timestamp()),  # Expira em 24h
            payment_intent_data={
                'metadata': metadata,
                'description': f'Assinatura Premium - {nome}'
            },
            automatic_tax={'enabled': True},  # Habilita cálculo automático de impostos
            consent_collection={
                'terms_of_service': 'required',
                'promotions': 'auto'
            },
            phone_number_collection={
                'enabled': True
            },
            shipping_address_collection={
                'allowed_countries': ['BR', 'PT', 'US']
            },
            billing_address_collection='required',
            customer_update={
                'name': 'auto',
                'address': 'auto',
                'shipping': 'auto'
            },
            payment_method_options={
                'card': {
                    'request_three_d_secure': 'automatic'
                },
                'boleto': {
                    'expires_after_days': 3
                }
            }
        )
        
        logger.info(f"Sessão de checkout criada com sucesso: {session.id}")
        logger.debug(f"URL de sucesso: {success_url}")
        logger.debug(f"URL de cancelamento: {cancel_url}")
        
        # Armazena o ID da sessão para verificação posterior
        if 'ultima_sessao_checkout' not in st.session_state:
            st.session_state.ultima_sessao_checkout = session.id
        
        return session.url
        
    except stripe.error.StripeError as e:
        error_msg = f"Erro na API do Stripe: {str(e)}"
        logger.error(error_msg)
        st.error("Erro ao processar o pagamento. Por favor, tente novamente.")
        return None
    except Exception as e:
        error_msg = f"Erro inesperado ao criar sessão de checkout: {str(e)}"
        logger.error(error_msg, exc_info=True)
        st.error("Ocorreu um erro inesperado. Por favor, entre em contato com o suporte.")
        return None
        return None

def verificar_pagamento(session_id):
    """
    Verifica o status de um pagamento pelo ID da sessão do Stripe.
    
    Args:
        session_id (str): ID da sessão do Stripe a ser verificada
        
    Returns:
        tuple: (sucesso: bool, mensagem: str)
    """
    try:
        logger.info(f"Iniciando verificação do pagamento para a sessão: {session_id}")
        
        # 1. Buscar a sessão no Stripe com expansão de dados adicionais
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=[
                'payment_intent',
                'subscription',
                'customer',
                'line_items'
            ]
        )
        
        logger.debug(f"Dados da sessão: {json.dumps(session, default=str, indent=2)}")
        
        # 2. Verificar se a sessão foi encontrada
        if not session:
            logger.error(f"Sessão não encontrada: {session_id}")
            return False, "Sessão de pagamento não encontrada. Por favor, tente novamente."
        
        # 3. Verificar o status do pagamento
        if session.payment_status == 'paid' or (hasattr(session, 'subscription') and session.subscription):
            logger.info(f"Pagamento confirmado para a sessão: {session_id}")
            
            # 4. Obter o ID do usuário
            usuario_id = session.client_reference_id
            if not usuario_id:
                # Tenta obter do metadata se não estiver no client_reference_id
                usuario_id = session.metadata.get('user_id')
            
            if not usuario_id:
                logger.error("ID do usuário não encontrado na sessão do Stripe")
                return False, "Erro ao identificar o usuário. Por favor, entre em contato com o suporte."
            
            # 5. Coletar metadados para auditoria
            metadados = {
                'stripe_session_id': session.id,
                'payment_intent': session.payment_intent.id if hasattr(session, 'payment_intent') and session.payment_intent else None,
                'subscription_id': session.subscription.id if hasattr(session, 'subscription') and session.subscription else None,
                'customer_id': session.customer.id if hasattr(session, 'customer') and session.customer else None,
                'amount_total': session.amount_total / 100 if hasattr(session, 'amount_total') and session.amount_total else 0,
                'currency': session.currency.upper() if hasattr(session, 'currency') and session.currency else 'BRL',
                'payment_status': session.payment_status,
                'payment_method_types': session.payment_method_types if hasattr(session, 'payment_method_types') else [],
                'created': datetime.fromtimestamp(session.created).isoformat() if hasattr(session, 'created') else None,
                'expires_at': datetime.fromtimestamp(session.expires_at).isoformat() if hasattr(session, 'expires_at') else None
            }
            
            logger.info(f"Metadados do pagamento: {json.dumps(metadados, indent=2)}")
            
            # 6. Atualizar status da assinatura no Firestore
            try:
                # Usa a função update_subscription_status do firebase_setup.py
                from firebase_setup import update_subscription_status
                
                sucesso = update_subscription_status(
                    user_id=usuario_id,
                    is_active=True,
                    subscription_plan='premium',
                    payment_method=session.payment_method_types[0] if hasattr(session, 'payment_method_types') and session.payment_method_types else 'card',
                    subscription_id=session.subscription.id if hasattr(session, 'subscription') and session.subscription else None,
                    metadata=metadados
                )
                
                if sucesso:
                    logger.info(f"Status da assinatura atualizado com sucesso para o usuário: {usuario_id}")
                    
                    # 7. Atualizar a sessão do usuário
                    if 'usuario' in st.session_state and st.session_state.usuario.get('id') == usuario_id:
                        st.session_state.usuario['assinatura'] = True
                        st.session_state.usuario['plano'] = 'premium'
                        st.session_state.usuario['data_assinatura'] = datetime.now().isoformat()
                    
                    # 8. Registrar o pagamento bem-sucedido
                    logger.info(f"Pagamento confirmado e assinatura ativada para o usuário: {usuario_id}")
                    return True, "✅ Pagamento confirmado! Sua assinatura foi ativada com sucesso!"
                else:
                    logger.error(f"Falha ao atualizar o status da assinatura para o usuário: {usuario_id}")
                    return False, "❌ Erro ao ativar sua assinatura. Por favor, entre em contato com o suporte."
                    
            except Exception as db_error:
                logger.error(f"Erro ao atualizar o status da assinatura no banco de dados: {str(db_error)}", exc_info=True)
                return False, "❌ Erro ao processar sua assinatura. Por favor, entre em contato com o suporte."
        
        # Se o pagamento não foi confirmado
        elif session.payment_status == 'unpaid':
            logger.warning(f"Pagamento não pago para a sessão: {session_id}")
            return False, "⚠️ Seu pagamento ainda não foi confirmado. Isso pode levar alguns minutos."
            
        elif session.payment_status == 'no_payment_required':
            logger.info(f"Sessão não requer pagamento: {session_id}")
            return False, "ℹ️ Esta sessão não requer pagamento."
            
        else:
            logger.warning(f"Status de pagamento não confirmado para a sessão {session_id}: {session.payment_status}")
            return False, "⏳ Aguardando confirmação do pagamento..."
            
    except stripe.error.StripeError as e:
        error_msg = f"Erro na API do Stripe ao verificar pagamento: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, f"❌ Erro ao verificar o pagamento: {str(e)}"
        
    except Exception as e:
        error_msg = f"Erro inesperado ao verificar pagamento: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, "❌ Ocorreu um erro inesperado. Por favor, tente novamente ou entre em contato com o suporte."

def exibir_tela_assinatura():
    """Exibe a tela de assinatura com opções de pagamento."""
    st.markdown("<h1 class='main-header'>Assinatura Premium</h1>", unsafe_allow_html=True)
    st.markdown("""
    <div class='info-text'>
        <p>Desbloqueie todo o potencial do Gerador de Livros com uma assinatura premium. Por apenas <strong>R$ 29,90/mês</strong>, você terá acesso a:</p>
        <ul>
            <li>✅ Geração ilimitada de livros</li>
            <li>✅ Suporte prioritário</li>
            <li>✅ Atualizações exclusivas</li>
            <li>✅ Recursos avançados de personalização</li>
        </ul>
        <p>Pague com cartão de crédito, boleto ou PIX.</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Verificar se já tem assinatura ativa
    if st.session_state.usuario.get('assinatura', False):
        st.success("✅ Você já possui uma assinatura ativa!")
        if st.button("Voltar para o aplicativo", type="primary", use_container_width=True):
            st.session_state.aba_atual = "app"
            st.rerun()
        return
    
    # Botão para assinar
    if st.button("Assinar Agora - R$ 29,90/mês", type="primary", use_container_width=True, key="assinar_agora"):
        with st.spinner("Preparando seu checkout seguro..."):
            # Criar sessão de checkout
            checkout_url = criar_sessao_checkout(
                usuario_id=st.session_state.usuario['id'],
                email=st.session_state.usuario['email'],
                nome=st.session_state.usuario['nome']
            )
            
            if checkout_url:
                # Redirecionar para o checkout do Stripe
                st.markdown(f'<meta http-equiv="refresh" content="0;url={checkout_url}">', unsafe_allow_html=True)
                st.warning("Redirecionando para o checkout seguro...")
            else:
                st.error("Não foi possível criar a sessão de pagamento. Tente novamente mais tarde.")
    
    # Link para voltar
    st.markdown("---")
    if st.button("Voltar para o aplicativo", type="secondary", use_container_width=True):
        st.session_state.aba_atual = "app"
        st.rerun()

# === FUNÇÕES DE GERAÇÃO DE LIVROS ===

def gerar_livro_generico(tema, autor, email_autor, genero, estilo, publico_alvo, descricao, formato, num_capitulos=12, api_key=None):
    """
    Gera um livro completo com base nos parâmetros fornecidos usando a API da OpenAI.
    
    Args:
        tema: Tema principal do livro
        autor: Nome do autor
        email_autor: E-mail do autor
        genero: Gênero literário
        estilo: Estilo de escrita
        publico_alvo: Público-alvo do livro
        descricao: Descrição detalhada do livro
        formato: Formato do livro (eBook, impresso, etc.)
        num_capitulos: Número de capítulos a serem gerados (padrão: 12)
        api_key: Chave da API da OpenAI
    
    Returns:
        str: Conteúdo completo do livro formatado
    """
    # Inicializar cliente OpenAI com a chave fornecida
    if api_key:
        client = OpenAI(api_key=api_key)
    else:
        raise ValueError("Chave da API da OpenAI não fornecida")
    try:
        # Inicializar variáveis
        livro_completo = f"# {tema.upper()}\n\n"
        livro_completo += f"**Autor:** {autor}\n"
        livro_completo += f"**Gênero:** {genero}\n"
        livro_completo += f"**Estilo:** {estilo}\n"
        livro_completo += f"**Público-alvo:** {publico_alvo}\n\n"
        
        # Adicionar prefácio
        livro_completo += "## Prefácio\n\n"
        livro_completo += f"Este livro foi gerado automaticamente pelo Gerador de Livros AI. \n"
        livro_completo += f"Tema: {tema}\n"
        livro_completo += f"Autor: {autor} ({email_autor})\n\n"
        
        # Gerar índice
        livro_completo += "## Índice\n\n"
        capitulos = []
        
        # Gerar títulos dos capítulos
        for i in range(1, num_capitulos + 1):
            try:
                # Usar a API da OpenAI para gerar títulos de capítulos criativos
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Você é um escritor especializado em criar títulos de capítulos cativantes."},
                        {"role": "user", "content": f"Gere um título criativo para o capítulo {i} de um livro sobre '{tema}'. O gênero é {genero} e o estilo é {estilo}. Apenas o título, sem numeração."}
                    ],
                    max_tokens=50,
                    temperature=0.7
                )
                titulo_capitulo = response.choices[0].message.content.strip('"\'').strip()
            except Exception as e:
                st.error(f"Erro ao gerar título do capítulo {i}: {str(e)}")
                titulo_capitulo = f"Capítulo {i}"
            
            capitulos.append(titulo_capitulo)
            livro_completo += f"{i}. {titulo_capitulo}\n"
        
        livro_completo += "\n"
        
        # Gerar conteúdo para cada capítulo
        for i, titulo in enumerate(capitulos, 1):
            st.toast(f"Gerando capítulo {i}/{num_capitulos}: {titulo}")
            
            livro_completo += f"# Capítulo {i}: {titulo}\n\n"
            
            # Usar a API da OpenAI para gerar o conteúdo do capítulo
            prompt = f"""
            Escreva um capítulo de um livro com as seguintes características:
            - Título: {titulo}
            - Tema principal: {tema}
            - Gênero: {genero}
            - Estilo: {estilo}
            - Público-alvo: {publico_alvo}
            - Descrição: {descricao}
            
            O capítulo deve ter entre 500 e 800 palavras, ser bem estruturado e cativante.
            """
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Você é um escritor profissional especializado em criar conteúdo literário cativante."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.8
            )
            
            conteudo_capitulo = response.choices[0].message.content.strip()
            livro_completo += f"{conteudo_capitulo}\n\n"
            
            # Adicionar uma pequena pausa para evitar sobrecarga da API
            time.sleep(1)
        
        # Adicionar posfácio
        livro_completo += "# Posfácio\n\n"
        livro_completo += f"Chegamos ao final desta jornada sobre '{tema}'. Espero que tenha gostado da leitura. "
        livro_completo += f"Este livro foi gerado automaticamente, mas cada palavra foi cuidadosamente elaborada para você.\n\n"
        livro_completo += f"Atenciosamente,\n{autor}\n"
        
        # Adicionar informações de direitos autorais
        ano_atual = datetime.now().year
        livro_completo += f"\n---\n"
        livro_completo += f"© {ano_atual} {autor}. Todos os direitos reservados.\n"
        livro_completo += f"Este livro foi gerado pelo Gerador de Livros AI.\n"
        
        return livro_completo
        
    except Exception as e:
        st.error(f"Erro ao gerar o livro: {str(e)}")
        return f"Ocorreu um erro ao gerar o livro: {str(e)}"

def salvar_livro_local(conteudo, tema, formato="txt"):
    """Salva o livro localmente na pasta de livros gerados."""
    try:
        # Criar pasta de backup se não existir
        backup_dir = "livros_gerados"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # Criar nome do arquivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_arquivo = f"{tema.replace(' ', '_')}_{timestamp}.{formato}"
        caminho_arquivo = os.path.join(backup_dir, nome_arquivo)
        
        # Salvar arquivo
        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            f.write(conteudo)
        
        return True, f"Arquivo salvo com sucesso em: {caminho_arquivo}"
    except Exception as e:
        return False, f"Erro ao salvar arquivo: {str(e)}"

def exibir_resultado_livro(conteudo_livro, tema, autor, formato):
    """Exibe o resultado do livro gerado com opções de download."""
    st.success(f"Livro sobre '{tema}' gerado com sucesso!")
    
    # Criar abas para visualização e informações de publicação
    tab1, tab2 = st.tabs(["Visualizar Livro", "Informações de Publicação KDP"])
    
    with tab1:
        # Exibir o conteúdo do livro com formatação adequada
        st.markdown(f"<div class='book-content'>{conteudo_livro}</div>", unsafe_allow_html=True)
    
    with tab2:
        st.markdown("### Instruções para Publicação na Amazon KDP")
        st.markdown("""
        1. **Acesse o KDP**: Faça login em [kdp.amazon.com](https://kdp.amazon.com)
        2. **Crie um novo eBook**: Clique em '+ Criar eBook'
        3. **Detalhes do eBook**:
           - Preencha o título, subtítulo e descrição
           - Adicione palavras-chave relevantes
           - Escolha categorias apropriadas
        4. **Conteúdo do eBook**:
           - Faça upload do arquivo baixado (converta para EPUB ou use o Word)
           - Faça upload de uma capa (você pode criar uma em Canva.com)
        5. **Preço**:
           - Defina o preço e os territórios
           - Escolha as opções de royalties
        6. **Publicar**: Revise e publique seu livro
        """)
        
        st.info("**Dica**: Para criar uma capa atraente, você pode usar ferramentas como Canva, DALL-E ou Midjourney com a descrição da cena principal do seu livro.")
    
    # Opções para baixar o livro em diferentes formatos
    st.markdown("<div class='format-section'>", unsafe_allow_html=True)
    st.markdown("### Baixar Livro")
    
    # Criar arquivos temporários para download
    txt_filename = f"livro_{tema.replace(' ', '_')}.txt"
    md_filename = f"livro_{tema.replace(' ', '_')}.md"
    
    # Opção para baixar o livro como arquivo de texto
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="Baixar como TXT",
            data=conteudo_livro,
            file_name=txt_filename,
            mime="text/plain",
            use_container_width=True
        )
    
    with col2:
        # Opção para baixar como Markdown
        st.download_button(
            label="Baixar como Markdown",
            data=conteudo_livro,
            file_name=md_filename,
            mime="text/markdown",
            use_container_width=True
        )
    
    # Botão para salvar cópia local
    if st.button("💾 Salvar cópia local (backup)", key="backup_button"):
        success, message = salvar_livro_local(conteudo_livro, tema)
        if success:
            st.success(message)
        else:
            st.error(message)
    
    # Botão para criar um novo livro
    if st.button("🔄 Criar Novo Livro", key="new_book_button", type="primary"):
        novo_livro()
    
    st.markdown("</div>", unsafe_allow_html=True)

def exibir_formulario_livro():
    """Exibe o formulário para criação de um novo livro."""
    # Seção de informações do autor
    st.markdown("<div class='author-section'>", unsafe_allow_html=True)
    st.markdown("### Informações do Autor")
    
    # Campos do formulário
    col1, col2 = st.columns(2)
    
    with col1:
        autor = st.text_input("Nome do Autor*", 
                             value=st.session_state.get('autor_livro', ''),
                             placeholder="Ex: Maria Silva")
        
        genero = st.selectbox(
            "Gênero do Livro*",
            options=["Ficção", "Não-Ficção", "Fantasia", "Ficção Científica", "Romance", "Mistério/Suspense", "Terror/Horror", "Aventura", "Infantil", "Young Adult", "Biografia", "Autoajuda", "Cristão"],
            index=0 if not st.session_state.get('genero_livro') else ["Ficção", "Não-Ficção", "Fantasia", "Ficção Científica", "Romance", "Mistério/Suspense", "Terror/Horror", "Aventura", "Infantil", "Young Adult", "Biografia", "Autoajuda", "Cristão"].index(st.session_state.genero_livro)
        )
    
    with col2:
        email_autor = st.text_input("E-mail do Autor*", 
                                   value=st.session_state.get('email_autor_livro', ''),
                                   placeholder="Ex: autor@email.com")
        
        estilo = st.selectbox(
            "Estilo de Escrita*",
            options=["Narrativo", "Descritivo", "Dialogado", "Poético", "Humorístico", "Dramático", "Técnico", "Acadêmico"],
            index=0 if not st.session_state.get('estilo_livro') else ["Narrativo", "Descritivo", "Dialogado", "Poético", "Humorístico", "Dramático", "Técnico", "Acadêmico"].index(st.session_state.estilo_livro)
        )
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Seção de informações do livro
    st.markdown("<div class='book-section'>", unsafe_allow_html=True)
    st.markdown("## Informações do Livro")
    
    # Campo para a chave da API da OpenAI
    api_key = st.text_input(
        "Chave da API da OpenAI*",
        type="password",
        value=st.session_state.get('api_key', ''),
        placeholder="Insira sua chave da API da OpenAI (sk-...)",
        help="Você pode obter uma chave em https://platform.openai.com/api-keys"
    )
    st.session_state.api_key = api_key
    
    tema = st.text_input("Tema do Livro*", 
                         value=st.session_state.get('tema_livro', ''),
                         placeholder="Ex: Aventura Espacial, Mistério na Cidade Grande, etc.")
    
    # Número de capítulos
    num_capitulos = st.slider(
        "Número de Capítulos", 
        min_value=5, 
        max_value=30, 
        value=st.session_state.get('num_capitulos', 12), 
        step=1
    )
    st.session_state.num_capitulos = num_capitulos
    
    # Público-alvo e Formato
    col3, col4 = st.columns(2)
    
    with col3:
        publico_alvo = st.selectbox(
            "Público-Alvo*",
            options=["Infantil (0-12 anos)", "Adolescente (12-17 anos)", "Jovem Adulto (18-25 anos)", "Adulto (18+ anos)", "Todos os públicos"],
            index=3 if not st.session_state.get('publico_alvo_livro') else ["Infantil (0-12 anos)", "Adolescente (12-17 anos)", "Jovem Adulto (18-25 anos)", "Adulto (18+ anos)", "Todos os públicos"].index(st.session_state.publico_alvo_livro)
        )
    
    with col4:
        formato = st.selectbox(
            "Formato do Livro*",
            options=["eBook Kindle", "Livro impresso"],
            index=0 if not st.session_state.get('formato_livro') else ["eBook Kindle", "Livro impresso"].index(st.session_state.formato_livro)
        )
    
    descricao = st.text_area(
        "Descrição do Livro*",
        value=st.session_state.get('descricao_livro', ''),
        placeholder="Descreva brevemente o livro, incluindo personagens principais e mensagem central...",
        height=150
    )
    
    # Botão para gerar o livro
    if st.button("✨ Gerar Livro", type="primary", use_container_width=True):
        # Validar campos obrigatórios
        campos_obrigatorios = [
            (tema, "Tema do Livro"),
            (autor, "Nome do Autor"),
            (email_autor, "E-mail do Autor"),
            (descricao, "Descrição do Livro"),
            (api_key, "Chave da API da OpenAI")
        ]
        
        campos_faltando = [nome for valor, nome in campos_obrigatorios if not valor]
        
        if campos_faltando:
            st.error(f"Por favor, preencha os seguintes campos obrigatórios: {', '.join(campos_faltando)}")
            return
        
        # Salvar dados na sessão
        st.session_state.tema_livro = tema
        st.session_state.autor_livro = autor
        st.session_state.email_autor_livro = email_autor
        st.session_state.genero_livro = genero
        st.session_state.estilo_livro = estilo
        st.session_state.publico_alvo_livro = publico_alvo
        st.session_state.descricao_livro = descricao
        st.session_state.formato_livro = formato
        
        # Iniciar geração do livro
        st.session_state.gerando_livro = True
        st.rerun()
    
    st.markdown("</div>", unsafe_allow_html=True)

# === ROTEAMENTO PRINCIPAL ===

def exibir_tela_login():
    """Exibe o formulário de login."""
    st.title("🔑 Login")
    st.markdown("---")
    
    with st.form("login_form_unique"):
        email = st.text_input("E-mail", key="login_email_unique")
        senha = st.text_input("Senha", type="password", key="login_senha_unique")
        btn_login = st.form_submit_button("Entrar")
        
        if btn_login:
            if not email or not senha:
                st.error("Por favor, preencha todos os campos.")
                return
                
            usuario = autenticar_usuario(email, senha)
            if usuario:
                st.session_state.usuario = usuario
                st.session_state.aba_atual = "app"
                st.success(f"Bem-vindo(a), {usuario['nome']}!")
                st.rerun()
            else:
                st.error("E-mail ou senha inválidos.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📝 Criar Conta"):
            st.session_state.aba_atual = "cadastro"
            st.rerun()
    with col2:
        if st.button("🔒 Esqueci minha senha"):
            st.session_state.aba_atual = "recuperar"
            st.rerun()

def exibir_tela_cadastro():
    """Exibe o formulário de cadastro de usuário."""
    st.title("📝 Criar Conta")
    st.markdown("---")
    
    with st.form("cadastro_form_unique"):
        nome = st.text_input("Nome Completo", key="cadastro_nome_unique")
        email = st.text_input("E-mail", key="cadastro_email_unique")
        senha = st.text_input("Senha", type="password", key="cadastro_senha_unique")
        confirmar_senha = st.text_input("Confirmar Senha", type="password", key="cadastro_confirmar_senha_unique")
        btn_cadastrar = st.form_submit_button("Cadastrar")
        
        if btn_cadastrar:
            if not nome or not email or not senha or not confirmar_senha:
                st.error("Por favor, preencha todos os campos.")
                return
                
            if senha != confirmar_senha:
                st.error("As senhas não coincidem.")
                return
                
            sucesso, mensagem = cadastrar_usuario(nome, email, senha)
            if sucesso:
                st.success(mensagem)
                st.session_state.aba_atual = "login"
                st.rerun()
            else:
                st.error(mensagem)
    
    if st.button("← Voltar para o Login"):
        st.session_state.aba_atual = "login"
        st.rerun()

def exibir_tela_recuperar_senha():
    """Exibe o formulário de recuperação de senha."""
    st.title("🔒 Recuperar Senha")
    st.markdown("---")
    
    if 'etapa_recuperacao' not in st.session_state:
        st.session_state.etapa_recuperacao = 1
    
    if st.session_state.etapa_recuperacao == 1:
        # Etapa 1: Solicitar e-mail
        with st.form("recuperar_form_unique"):
            email = st.text_input("Digite seu e-mail", key="recuperar_email_unique")
            btn_enviar = st.form_submit_button("Enviar Código")
            
            if btn_enviar:
                if not email:
                    st.error("Por favor, digite seu e-mail.")
                else:
                    sucesso, mensagem = solicitar_redefinicao_senha(email)
                    if sucesso:
                        st.session_state.email_recuperacao = email
                        st.session_state.etapa_recuperacao = 2
                        st.success(mensagem)
                        st.rerun()
                    else:
                        st.error(mensagem)
    else:
        # Etapa 2: Inserir código e nova senha
        with st.form("redefinir_form_unique"):
            st.write(f"Enviamos um código para {st.session_state.email_recuperacao}")
            codigo = st.text_input("Código de verificação", key="recuperar_codigo_unique")
            nova_senha = st.text_input("Nova Senha", type="password", key="nova_senha_unique")
            confirmar_senha = st.text_input("Confirmar Nova Senha", type="password", key="confirmar_nova_senha_unique")
            btn_redefinir = st.form_submit_button("Redefinir Senha")
            
            if btn_redefinir:
                if not codigo or not nova_senha or not confirmar_senha:
                    st.error("Por favor, preencha todos os campos.")
                elif nova_senha != confirmar_senha:
                    st.error("As senhas não coincidem.")
                else:
                    sucesso, mensagem = redefinir_senha_com_token(
                        st.session_state.email_recuperacao,
                        codigo,
                        nova_senha
                    )
                    if sucesso:
                        st.success(mensagem)
                        del st.session_state.etapa_recuperacao
                        del st.session_state.email_recuperacao
                        st.session_state.aba_atual = "login"
                        st.rerun()
                    else:
                        st.error(mensagem)
    
    if st.button("← Voltar para o Login"):
        del st.session_state.etapa_recuperacao
        if 'email_recuperacao' in st.session_state:
            del st.session_state.email_recuperacao
        st.session_state.aba_atual = "login"
        st.rerun()

def exibir_tela_assinatura():
    """
    Exibe a tela de assinatura do serviço com opções de pagamento.
    
    Esta função gerencia o fluxo de assinatura, incluindo verificação de pagamentos pendentes,
    exibição de informações sobre o plano e processamento de novos pagamentos.
    """
    st.title("💎 Assinatura Premium")
    
    # Verificar se o usuário já pagou pelo email no CSV
    if 'usuario' in st.session_state and st.session_state.usuario.get('email'):
        email = st.session_state.usuario.get('email')
        with st.spinner("🔍 Verificando status do pagamento..."):
            try:
                # Verificar no CSV
                assinatura_ativa = verificar_assinatura_csv(email)
                if assinatura_ativa:
                    # Atualizar status no Firestore também
                    if st.session_state.usuario.get('id'):
                        atualizar_status_assinatura(st.session_state.usuario.get('id'), True)
                    
                    # Atualizar sessão
                    st.session_state.usuario['assinatura'] = True
                    st.success("✅ Pagamento confirmado! Sua assinatura foi ativada com sucesso.")
                    st.balloons()
                    st.rerun()
            except Exception as e:
                st.error(f"Erro ao verificar pagamento: {str(e)}")
    
    # Seção de benefícios
    st.markdown("""
    ## 🚀 Desbloqueie todo o potencial do Gerador de Livros
    
    Com a assinatura Premium, você tem acesso a:
    - 📚 Geração ilimitada de livros
    - 💾 Exportação em múltiplos formatos (PDF, DOCX, EPUB)
    - 🎨 Capas profissionais personalizadas
    - ✍️ Revisão automática de texto
    - 📊 Otimização para publicação no KDP
    - 🎁 Bônus exclusivos para assinantes
    - 🛡️ Garantia de satisfação de 7 dias
    - 🎓 Tutoriais e materiais exclusivos
    
    **💵 Apenas R$ 97,00 por mês**
    
    *Cancele quando quiser, sem taxas ou pegadinhas.*
    """)
    
    st.markdown("---")
    
    # Verifica se o usuário está logado
    if 'usuario' not in st.session_state or not st.session_state.usuario.get('id'):
        st.warning("🔒 Você precisa estar logado para assinar o plano Premium.")
        col1, col2 = st.columns([1, 2])
        with col1:
            if st.button("🔑 Fazer Login", key="assinatura_login_btn", use_container_width=True):
                st.session_state.aba_atual = "login"
                st.rerun()
        with col2:
            if st.button("📝 Criar Conta", key="assinatura_cadastro_btn", use_container_width=True):
                st.session_state.aba_atual = "cadastro"
                st.rerun()
        return
    
    # Se o usuário já tem assinatura ativa
    if st.session_state.usuario.get('assinatura'):
        st.success("✅ Você já possui uma assinatura Premium ativa!")
        st.info("Aproveite todos os recursos exclusivos disponíveis para você.")
        
        if st.button("🏠 Voltar para o Aplicativo", key="assinatura_voltar_btn", use_container_width=True):
            st.session_state.aba_atual = "app"
            st.rerun()
        return
    
    # Seção de pagamento
    st.markdown("### 💳 Escolha sua forma de pagamento")
    
    # Opções de pagamento
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        #### 💳 Cartão de Crédito
        - Pague com Visa, Mastercard, American Express
        - Processamento seguro via Stripe
        - Aprovação em segundos
        """)
    
    with col2:
        st.markdown("""
        #### 🏦 PIX
        - Pague com PIX em qualquer banco
        - Aprovação em até 1 dia útil
        - Sem taxas adicionais
        """)
    
    # Botão de assinatura com Payment Link
    if st.button("✅ Assinar Agora - R$ 97,00/mês", 
                type="primary", 
                use_container_width=True, 
                key="assinar_agora_btn",
                help="Clique para ser redirecionado ao pagamento seguro"):
        try:
            # Verifica se o usuário está logado
            if 'usuario' not in st.session_state or not st.session_state.usuario.get('id'):
                st.error("Sessão expirada. Por favor, faça login novamente.")
                st.session_state.aba_atual = "login"
                st.rerun()
                return
                
            # Verifica se o link de pagamento está configurado
            if not STRIPE_PAYMENT_LINK:
                st.error("Erro de configuração: Link de pagamento não definido.")
                return
                
            # Redireciona para o link de pagamento do Stripe
            st.components.v1.html(f"""
            <script>
                window.open("{STRIPE_PAYMENT_LINK}", "_blank");
            </script>
            """, height=0)
            
            # Mensagem de instrução
            st.info("""
            📱 Uma nova aba foi aberta para você completar o pagamento. 
            
            **Importante:** Certifique-se de usar o mesmo email cadastrado nesta plataforma ao realizar o pagamento.
            
            Após o pagamento, o acesso será liberado automaticamente em alguns minutos.
            
            Se você já realizou o pagamento, clique no botão abaixo para verificar o status.
            """)
            
            # Botão para verificação manual
            if st.button("🔄 Já paguei, verificar agora", type="secondary", key="verificar_pagamento_btn"):
                with st.spinner("🔍 Verificando pagamento..."):
                    # Verificar no CSV pelo email
                    email = st.session_state.usuario.get('email')
                    assinatura_ativa = verificar_assinatura_csv(email)
                    if assinatura_ativa:
                        # Atualizar status no Firestore também
                        if st.session_state.usuario.get('id'):
                            atualizar_status_assinatura(st.session_state.usuario.get('id'), True)
                        
                        # Atualizar sessão
                        st.session_state.usuario['assinatura'] = True
                        st.success("✅ Pagamento confirmado! Sua assinatura foi ativada com sucesso.")
                        st.balloons()
                        st.session_state.aba_atual = "app"
                        st.rerun()
                    else:
                        st.warning("Pagamento ainda não confirmado. Aguarde alguns minutos e tente novamente.")
                        
        except Exception as e:
            error_msg = f"Erro inesperado: {str(e)}"
            st.error(f"Ocorreu um erro ao processar seu pagamento. {error_msg}")
            print(f"ERRO ao redirecionar para o Payment Link: {error_msg}")
    
    # Botão para voltar sem assinar
    if st.button("Voltar sem assinar", key="voltar_sem_assinar_btn"):
        st.session_state.aba_atual = "app"
        st.rerun()
        
    # Rodapé informativo
    st.markdown("""
    <div style='margin-top: 2rem; font-size: 0.9em; color: #666; text-align: center;'>
        <p>Pagamento seguro via Stripe | 7 dias de garantia incondicional</p>
        <p>Suporte 24/7 | Acesso imediato após a confirmação do pagamento</p>
    </div>
    """, unsafe_allow_html=True)

def verificar_pagamento(session_id):
    """
    Verifica o status de um pagamento no Stripe.
    
    Args:
        session_id (str): ID da sessão de checkout do Stripe.
        
    Returns:
        tuple: (bool, str) - (sucesso, mensagem)
    """
    if not session_id or not isinstance(session_id, str):
        return False, "ID de sessão inválido"
    
    try:
        # Verificar se a chave da API do Stripe está configurada
        if not stripe.api_key:
            error_msg = "Chave da API do Stripe não configurada"
            print(f"ERRO: {error_msg}")
            return False, "Erro de configuração do sistema. Por favor, tente novamente mais tarde."
            
        # Buscar a sessão de checkout no Stripe
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            print(f"Sessão recuperada: {session.id}, Status: {session.payment_status}")
        except stripe.error.InvalidRequestError as e:
            error_msg = f"Sessão de pagamento inválida: {str(e)}"
            print(f"ERRO: {error_msg}")
            return False, "Sessão de pagamento inválida ou expirada."
        except stripe.error.StripeError as e:
            error_msg = f"Erro ao acessar o Stripe: {str(e)}"
            print(f"ERRO STRIPE: {error_msg}")
            return False, "Erro ao conectar ao serviço de pagamento. Tente novamente."
        
        # Verificar o status do pagamento
        if session.payment_status == 'paid':
            # Obter o ID do usuário da sessão
            user_id = session.client_reference_id
            user_email = session.customer_email or session.metadata.get('user_email')
            
            if not user_id and user_email:
                # Tentar obter o ID do usuário pelo e-mail
                user = get_user_by_email(user_email)
                if user:
                    user_id = user.get('id')
            
            if not user_id:
                error_msg = "ID do usuário não encontrado na sessão de pagamento"
                print(f"ERRO: {error_msg}")
                return False, "Erro ao identificar o usuário. Entre em contato com o suporte."
            
            # Atualizar o status da assinatura no banco de dados
            try:
                sucesso = atualizar_status_assinatura(user_id, True)
                if sucesso:
                    # Atualizar o estado do usuário na sessão, se for o mesmo usuário
                    if 'usuario' in st.session_state and st.session_state.usuario.get('id') == user_id:
                        st.session_state.usuario['assinatura'] = True
                        st.session_state.aba_atual = "app"  # Redireciona para o app
                    
                    # Log de sucesso
                    print(f"✅ Assinatura ativada para o usuário {user_id}")
                    return True, "✅ Pagamento confirmado! Sua assinatura foi ativada com sucesso."
                else:
                    error_msg = f"Falha ao atualizar assinatura no banco de dados para o usuário {user_id}"
                    print(f"ERRO: {error_msg}")
                    return False, "Erro ao ativar sua assinatura. Entre em contato com o suporte."
                    
            except Exception as e:
                error_msg = f"Erro ao atualizar assinatura: {str(e)}"
                print(f"ERRO: {error_msg}")
                return False, "Erro ao processar sua assinatura. Entre em contato com o suporte."
                
        elif session.payment_status in ['unpaid', 'no_payment_required']:
            return False, "Pagamento não realizado ou pendente. Por favor, tente novamente."
            
        else:
            return False, f"Status de pagamento não reconhecido: {session.payment_status}"
            
    except stripe.error.StripeError as e:
        # Erros específicos do Stripe
        error_msg = f"Erro na API do Stripe: {str(e)}"
        print(f"ERRO STRIPE: {error_msg}")
        return False, "Ocorreu um erro ao processar seu pagamento. Por favor, tente novamente mais tarde."
        
    except Exception as e:
        # Erros inesperados
        error_msg = f"Erro inesperado ao verificar pagamento: {str(e)}"
        print(f"ERRO INESPERADO: {error_msg}")
        return False, "Ocorreu um erro inesperado. Por favor, entre em contato com o suporte."


def verificar_assinatura_csv(email):
    """
    Verifica se o usuário tem assinatura ativa, priorizando o Firebase e usando CSV como backup
    
    Args:
        email (str): Email do usuário
        
    Returns:
        bool: True se o usuário tem assinatura ativa, False caso contrário
    """
    try:
        # Primeiro, tentar verificar no Firebase
        try:
            user = get_user_by_email(email)
            if user:
                print(f"Usuário encontrado no Firebase: {user.get('id')}")
                assinatura = user.get('assinatura', False)
                print(f"Status da assinatura no Firebase para {email}: {assinatura}")
                return assinatura
        except Exception as e:
            print(f"Erro ao verificar assinatura no Firebase: {str(e)}")
        
        # Se não encontrou no Firebase ou ocorreu erro, verificar no CSV como backup
        import pandas as pd
        import os
        
        # Verificar se o arquivo existe
        if not os.path.exists(ARQUIVO_USUARIOS):
            print(f"Arquivo de usuários não encontrado: {ARQUIVO_USUARIOS}")
            return False
        
        # Ler o arquivo CSV
        df = pd.read_csv(ARQUIVO_USUARIOS)
        
        # Verificar se o email existe e tem status "pago"
        if email in df["email"].values:
            status = df.loc[df["email"] == email, "status"].values[0]
            print(f"Status da assinatura no CSV para {email}: {status}")
            return status.lower() == "pago"
        
        print(f"Email {email} não encontrado no arquivo de usuários")
        return False
    except Exception as e:
        print(f"Erro ao verificar assinatura: {str(e)}")
        return False

def handle_webhook(payload, sig_header):
    """
    Processa eventos do webhook do Stripe.
    """
    try:
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        
        try:
            # Verificar a assinatura do webhook
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except ValueError as e:
            # Payload inválido
            print(f"⚠️  Webhook error while parsing basic request: {str(e)}")
            return {'statusCode': 400, 'body': 'Payload inválido'}
        except stripe.error.SignatureVerificationError as e:
            # Assinatura inválida
            print(f"⚠️  Webhook signature verification failed: {str(e)}")
            return {'statusCode': 400, 'body': 'Assinatura inválida'}

        # Processar o evento
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            return handle_checkout_session_completed(session)

        print(f"ℹ️  Evento recebido: {event['type']}")
        return {'statusCode': 200, 'body': 'Evento recebido'}
        
    except Exception as e:
        print(f"❌ Erro ao processar webhook: {str(e)}")
        return {'statusCode': 500, 'body': 'Erro interno do servidor'}

def handle_checkout_session_completed(session):
    """
    Processa o evento de conclusão de checkout.
    """
    try:
        # Obter o ID do usuário a partir dos metadados ou client_reference_id
        user_id = session.get('client_reference_id')
        
        if not user_id:
            print("❌ ID do usuário não encontrado na sessão")
            return {'statusCode': 400, 'body': 'ID do usuário não encontrado'}
        
        # Atualizar o status de assinatura no Firestore
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'assinatura': True,
            'data_assinatura': firestore.SERVER_TIMESTAMP,
            'tipo_assinatura': 'vitalicio',
            'status_pagamento': 'pago'
        })
        
        print(f"✅ Status de assinatura atualizado para o usuário {user_id}")
        return {'statusCode': 200, 'body': 'Assinatura ativada com sucesso'}
        
    except Exception as e:
        print(f"❌ Erro ao processar checkout.session.completed: {str(e)}")
        return {'statusCode': 500, 'body': 'Erro ao processar assinatura'}

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/webhook':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # Processar o webhook
            sig_header = self.headers.get('stripe-signature')
            result = handle_webhook(post_data, sig_header)
            
            # Enviar resposta
            self.send_response(result['statusCode'])
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'result': result['body']}).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

def start_webhook_server():
    """Inicia o servidor de webhook em uma thread separada."""
    server_address = ('', 5000)
    httpd = HTTPServer(server_address, WebhookHandler)
    print('🚀 Servidor de webhook rodando na porta 5000')
    httpd.serve_forever()

def main():
    """Função principal que gerencia o roteamento e a lógica do aplicativo."""
    # Inicialização das variáveis de sessão
    if 'usuario' not in st.session_state:
        st.session_state.usuario = {
            "id": None, 
            "nome": "", 
            "email": "", 
            "assinatura": False, 
            "is_admin": False
        }
    
    # Inicialização das variáveis de estado do livro
    if 'livro_gerado' not in st.session_state:
        st.session_state.livro_gerado = False
    
    if 'conteudo_livro' not in st.session_state:
        st.session_state.conteudo_livro = None
    
    # Carregar estilos CSS
    carregar_estilos()
    
    # Exibir barra superior com informações do usuário
    exibir_barra_superior()
    
    # Roteamento de páginas
    if 'aba_atual' not in st.session_state:
        st.session_state.aba_atual = "login"
    
    # Verificar logout
    if st.query_params.get("logout") == ["true"]:
        st.session_state.usuario = {
            "id": None, 
            "nome": "", 
            "email": "", 
            "assinatura": False, 
            "is_admin": False
        }
        st.session_state.aba_atual = "login"
        st.rerun()
        return
    
    # Verificar se o usuário está autenticado para rotas protegidas
    rotas_publicas = ["login", "cadastro", "recuperar"]
    if st.session_state.aba_atual not in rotas_publicas and st.session_state.usuario["id"] is None:
        st.warning("Você precisa fazer login para acessar esta página.")
        st.session_state.aba_atual = "login"
        st.rerun()
        return
    
    # Roteamento principal
    if st.session_state.aba_atual == "login":
        exibir_tela_login()
    elif st.session_state.aba_atual == "cadastro":
        exibir_tela_cadastro()
    elif st.session_state.aba_atual == "recuperar":
        exibir_tela_recuperar_senha()
    elif st.session_state.aba_atual == "assinatura":
        exibir_tela_assinatura()
    elif st.session_state.aba_atual == "app":
        # Verificar se o usuário tem permissão para acessar o app
        if not st.session_state.usuario["assinatura"] and not st.session_state.usuario["is_admin"]:
            st.warning("Você precisa de uma assinatura ativa para acessar o gerador de livros.")
            st.session_state.aba_atual = "assinatura"
            st.rerun()
            return
        
        # Exibir conteúdo do app baseado no estado
        if st.session_state.get('livro_gerado') and st.session_state.conteudo_livro:
            exibir_resultado_livro(
                st.session_state.conteudo_livro,
                st.session_state.tema_livro,
                st.session_state.autor_livro,
                st.session_state.formato_livro
            )
        elif st.session_state.get('gerando_livro', False):
            # Lógica para gerar o livro
            with st.spinner("Gerando seu livro. Isso pode levar alguns minutos..."):
                try:
                    # Chamar a função de geração do livro
                    conteudo_livro = gerar_livro_generico(
                        tema=st.session_state.tema_livro,
                        autor=st.session_state.autor_livro,
                        email_autor=st.session_state.email_autor_livro,
                        genero=st.session_state.genero_livro,
                        estilo=st.session_state.estilo_livro,
                        publico_alvo=st.session_state.publico_alvo_livro,
                        descricao=st.session_state.descricao_livro,
                        formato=st.session_state.formato_livro,
                        num_capitulos=st.session_state.num_capitulos,
                        api_key=st.session_state.get('api_key')
                    )
                    
                    # Salvar o conteúdo gerado na sessão
                    st.session_state.conteudo_livro = conteudo_livro
                    st.session_state.livro_gerado = True
                    st.session_state.gerando_livro = False
                    
                    # Salvar cópia local
                    salvar_livro_local(conteudo_livro, st.session_state.tema_livro)
                    
                    # Rerun para exibir o resultado
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Ocorreu um erro ao gerar o livro: {str(e)}")
                    st.session_state.gerando_livro = False
                    st.rerun()
        else:
            # Exibir o formulário de criação de livro
            pagina_principal()
    
    # Exibir rodapé apenas se não estiver na tela de login/cadastro
    if st.session_state.aba_atual not in ["login", "cadastro", "recuperar"]:
        st.markdown("---")
        st.markdown("Desenvolvido com ❤️ usando CrewAI e Streamlit")
    
    # Verificar se há um livro em andamento (apenas para usuários não logados)
    if st.session_state.usuario["id"] is None:
        verificar_livro_em_andamento()
        st.rerun()

if __name__ == "__main__":
    # Iniciar o servidor de webhook em uma thread separada
    webhook_thread = threading.Thread(target=start_webhook_server, daemon=True)
    webhook_thread.start()
    
    # Iniciar o aplicativo Streamlit
    main()
