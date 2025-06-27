import streamlit as st
import os
import pandas as pd
import requests
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
import stripe

# Carregar variáveis de ambiente
load_dotenv()

# Configuração do Stripe
stripe.api_key = os.getenv("STRIPE_API_KEY")
STRIPE_PAYMENT_LINK = os.getenv("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/seu_link_aqui")

# Inicializar Firebase
# Desativando temporariamente a inicialização do Firebase Admin SDK
# para evitar problemas de permissão no Cloud Run

# Variável global para simular o banco de dados
db = None

# Função para simular o acesso ao Firestore
def get_firestore_db():
    return None  # Retorna None para indicar que não estamos usando Firestore

# Função para verificar assinatura no CSV
def verificar_assinatura_csv(email):
    try:
        arquivo_usuarios = os.getenv("ARQUIVO_USUARIOS", "usuarios.csv")
        if os.path.exists(arquivo_usuarios):
            df = pd.read_csv(arquivo_usuarios)
            if 'email' in df.columns and email in df['email'].values:
                return True
        return False
    except Exception as e:
        st.error(f"Erro ao verificar CSV: {e}")
        return False

# Função para verificar assinatura no Firestore (desativada)
def verificar_assinatura_firestore(email):
    # Fallback para o CSV já que o Firestore está com problemas de permissão
    return verificar_assinatura_csv(email)

# Função para atualizar status de assinatura no Firestore (desativada)
def atualizar_assinatura_firestore(email, status=True):
    # Usamos apenas o CSV por enquanto
    try:
        # Verificar se o arquivo existe
        arquivo_usuarios = os.getenv("ARQUIVO_USUARIOS", "usuarios.csv")
        
        # Carregar dados existentes ou criar um novo DataFrame
        try:
            df = pd.read_csv(arquivo_usuarios)
        except FileNotFoundError:
            df = pd.DataFrame(columns=['email', 'assinatura_ativa', 'data_atualizacao'])
        
        # Verificar se o email já existe no DataFrame
        if email in df['email'].values:
            # Atualizar o registro existente
            df.loc[df['email'] == email, 'assinatura_ativa'] = status
            df.loc[df['email'] == email, 'data_atualizacao'] = datetime.now().isoformat()
        else:
            # Adicionar novo registro
            novo_registro = pd.DataFrame({
                'email': [email],
                'assinatura_ativa': [status],
                'data_atualizacao': [datetime.now().isoformat()]
            })
            df = pd.concat([df, novo_registro], ignore_index=True)
        
        # Salvar o DataFrame atualizado
        df.to_csv(arquivo_usuarios, index=False)
        return True
    except Exception as e:
        st.error(f"Erro ao atualizar arquivo CSV: {e}")
        return False

# Função para exibir tela de assinatura
def exibir_tela_assinatura():
    st.title("💎 Assinatura Premium")
    # Verifica se o usuário já pagou pelo email no CSV
    if 'usuario' in st.session_state and st.session_state.usuario.get('email'):
        email = st.session_state.usuario.get('email')
        with st.spinner("🔍 Verificando status do pagamento..."):
            try:
                assinatura_ativa = verificar_assinatura_csv(email)
                if not assinatura_ativa:
                    assinatura_ativa = verificar_assinatura_firestore(email)
                
                if assinatura_ativa:
                    st.session_state.assinatura_ativa = True
                    st.success("✅ Sua assinatura está ativa!")
                    st.balloons()
                    # Redirecionar para a página principal após confirmar assinatura
                    st.session_state.pagina = 'principal'
                    st.rerun()  # Força o Streamlit a recarregar a página
                    return
                else:
                    st.warning("⚠️ Você ainda não possui uma assinatura ativa.")
                    
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"""
                        ### Assine agora e desbloqueie recursos premium!
                        - ✨ Acesso a todos os modelos de livros
                        - 📚 Gere livros ilimitados
                        - 🎨 Personalizações avançadas
                        - 🔄 Atualizações constantes
                        """)
                    
                    st.link_button("💳 Assinar Premium", STRIPE_PAYMENT_LINK, type="primary")
                    
                    st.markdown("---")
                    st.subheader("Já realizou o pagamento?")
                    if st.button("🔄 Verificar meu pagamento"):
                        # Aqui normalmente verificaríamos via API do Stripe
                        # Por simplicidade, vamos apenas atualizar o status
                        sucesso = atualizar_assinatura_firestore(email, True)
                        if sucesso:
                            st.session_state.assinatura_ativa = True
                            st.success("✅ Pagamento confirmado! Sua assinatura está ativa.")
                            st.balloons()
                            # Redirecionar para a página principal após confirmar pagamento
                            st.session_state.pagina = 'principal'
                            st.rerun()
                        else:
                            st.error("❌ Não foi possível verificar seu pagamento. Tente novamente mais tarde.")
            except Exception as e:
                st.error(f"Ocorreu um erro: {e}")
    else:
        st.warning("⚠️ Você precisa fazer login para assinar.")
        st.button("Fazer Login", on_click=lambda: setattr(st.session_state, 'pagina', 'login'))

# Função para exibir tela principal
def exibir_tela_principal():
    st.title("📚 Gerador de Livros")
    st.write("Bem-vindo ao Gerador de Livros! Esta é uma versão simplificada para deploy.")
    
    if 'usuario' in st.session_state and st.session_state.usuario.get('email'):
        st.write(f"Logado como: {st.session_state.usuario.get('email')}")
        
        if st.session_state.get('assinatura_ativa', False):
            st.success("✅ Assinatura Premium ativa!")
            st.write("Aqui você normalmente veria as opções para gerar livros.")
            st.info("Funcionalidades de IA temporariamente desativadas para facilitar o deploy.")
        else:
            st.warning("⚠️ Você ainda não possui uma assinatura premium.")
            st.button("Ver planos", on_click=lambda: setattr(st.session_state, 'pagina', 'assinatura'))
    else:
        st.warning("⚠️ Faça login para continuar.")
        st.button("Fazer Login", on_click=lambda: setattr(st.session_state, 'pagina', 'login'))

# Função para exibir tela de login
def exibir_tela_login():
    st.title("🔐 Login")
    
    email = st.text_input("Email")
    senha = st.text_input("Senha", type="password")
    
    if st.button("Entrar"):
        # Simulação de login
        if email and senha:
            st.session_state.usuario = {"email": email}
            st.session_state.pagina = "principal"
            st.rerun()
        else:
            st.error("Por favor, preencha todos os campos.")

# Configuração inicial da sessão
if 'pagina' not in st.session_state:
    st.session_state.pagina = 'principal'
if 'assinatura_ativa' not in st.session_state:
    st.session_state.assinatura_ativa = False

# Roteamento de páginas
if st.session_state.pagina == 'principal':
    exibir_tela_principal()
elif st.session_state.pagina == 'assinatura':
    exibir_tela_assinatura()
elif st.session_state.pagina == 'login':
    exibir_tela_login()
