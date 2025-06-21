import firebase_admin
from firebase_admin import credentials, firestore, auth
import os
import json
from typing import Dict, Optional, Any
from pathlib import Path

def init_firebase() -> Optional[firestore.client]:
    """
    Inicializa o Firebase com as credenciais do arquivo JSON.
    
    Returns:
        firestore.client: Cliente do Firestore ou None em caso de erro
    """
    try:
        # Verifica se o Firebase já foi inicializado
        if firebase_admin._apps:
            return firestore.client()
            
        # Caminho para o arquivo de credenciais
        cred_path = Path(__file__).parent / 'firebase-credentials.json'
        
        # Verifica se o arquivo de credenciais existe
        if not cred_path.exists():
            print(f"Erro: Arquivo de credenciais não encontrado em {cred_path}")
            # Tenta obter as credenciais de variáveis de ambiente
            cred_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
            if cred_json:
                try:
                    cred_dict = json.loads(cred_json)
                    cred = credentials.Certificate(cred_dict)
                except json.JSONDecodeError:
                    print("Erro: FIREBASE_CREDENTIALS_JSON não é um JSON válido")
                    return None
            else:
                return None
        else:
            # Carrega as credenciais do arquivo
            cred = credentials.Certificate(str(cred_path))
        
        # Inicializa o Firebase
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'gerador-de-livros-fb986.appspot.com'  # Substitua pelo seu bucket
        })
        
        print("✅ Firebase inicializado com sucesso!")
        return firestore.client()
        
    except Exception as e:
        print(f"❌ Erro ao inicializar o Firebase: {str(e)}")
        return None

# Inicializa o Firestore
db = init_firebase()

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Busca um usuário pelo email no Firestore.
    
    Args:
        email: Email do usuário a ser buscado
        
    Returns:
        Dict com os dados do usuário ou None se não encontrado
    """
    if not db:
        print("Erro: Firestore não inicializado")
        return None
        
    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        docs = query.stream()
        
        for doc in docs:
            user_data = doc.to_dict()
            user_data['id'] = doc.id
            return user_data
            
        print(f"Usuário com email {email} não encontrado")
        return None
        
    except Exception as e:
        print(f"Erro ao buscar usuário por email {email}: {str(e)}")
        return None

def update_subscription_status(
    email: str, 
    status: bool = True, 
    metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None
) -> bool:
    """
    Atualiza o status de assinatura de um usuário no Firestore com informações detalhadas.
    
    Args:
        email (str): Email do usuário para identificação
        status (bool): Novo status da assinatura (True para ativo, False para inativo)
        metadata (dict, optional): Metadados adicionais para auditoria
        user_id (str, optional): ID do usuário para busca direta (opcional)
        
    Returns:
        bool: True se a atualização foi bem-sucedida, False caso contrário
    """
    if not db:
        logger.error("Erro: Firestore não inicializado")
        return False
        
    try:
        users_ref = db.collection('users')
        
        # Prepara os dados para atualização
        update_data = {
            'assinatura': status,
            'data_atualizacao': firestore.SERVER_TIMESTAMP,
            'status_pagamento': 'pago' if status else 'cancelado',
            'ultima_atualizacao': firestore.SERVER_TIMESTAMP
        }
        
        # Adiciona metadados se fornecidos
        if metadata:
            if 'metadados_pagamento' not in update_data:
                update_data['metadados_pagamento'] = {}
            update_data['metadados_pagamento'].update(metadata)
            
        # Tenta encontrar o usuário pelo ID se fornecido
        if user_id:
            try:
                user_doc = users_ref.document(user_id).get()
                if user_doc.exists:
                    user_doc.reference.update(update_data)
                    logger.info(f"✅ Assinatura do usuário {user_id} atualizada via ID")
                    return True
                logger.warning(f"Usuário com ID {user_id} não encontrado")
            except Exception as e:
                logger.error(f"Erro ao buscar usuário por ID {user_id}: {str(e)}")
        
        # Se não encontrou pelo ID ou ID não foi fornecido, busca por email
        query = users_ref.where('email', '==', email).limit(1)
        docs = query.stream()
        
        updated = False
        for doc in docs:
            # Atualiza os dados do usuário
            doc.reference.update(update_data)
            
            # Registra o histórico de alterações
            history_data = {
                'tipo': 'atualizacao_assinatura',
                'status_anterior': doc.get('status_pagamento'),
                'novo_status': 'pago' if status else 'cancelado',
                'data': firestore.SERVER_TIMESTAMP,
                'metadados': metadata or {}
            }
            
            # Adiciona ao subcoleção de histórico
            doc.reference.collection('historico').add(history_data)
            
            updated = True
            logger.info(f"✅ Assinatura do usuário {email} atualizada para {status}")
            
            # Envia notificação por email se configurado
            if os.getenv('ENABLE_EMAIL_NOTIFICATIONS', '').lower() == 'true':
                enviar_email_confirmacao(email, status, metadata)
            
            break  # Apenas um documento deve corresponder ao email
            
        if not updated:
            logger.warning(f"⚠️ Usuário com email {email} não encontrado para atualização")
            
        return updated
        
    except firebase_admin.exceptions.FirebaseError as e:
        logger.error(f"Erro do Firebase ao atualizar assinatura para {email}: {str(e)}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Erro inesperado ao atualizar assinatura para {email}: {str(e)}", exc_info=True)
        return False

def enviar_email_confirmacao(email: str, status: bool, metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Envia um email de confirmação de atualização de assinatura.
    
    Args:
        email: Email do destinatário
        status: Novo status da assinatura
        metadata: Metadados adicionais para incluir no email
    """
    try:
        # Esta é uma implementação de exemplo - você precisará configurar seu próprio serviço de email
        status_text = "ATIVADA" if status else "CANCELADA"
        subject = f"📢 Confirmação de Assinatura - {status_text}"
        
        # Formata os metadados para exibição
        metadata_text = ""
        if metadata:
            for key, value in metadata.items():
                if key not in ['token', 'senha']:  # Não inclui dados sensíveis
                    metadata_text += f"{key}: {value}\n"
        
        body = f"""
        Olá,
        
        O status da sua assinatura foi atualizado para: {status_text}
        
        Detalhes da transação:
        {metadata_text}
        
        Caso você não tenha solicitado esta alteração, entre em contato com nosso suporte imediatamente.
        
        Atenciosamente,
        Equipe de Suporte
        """
        
        # Aqui você implementaria o envio real do email usando sua API de email preferida
        # Por exemplo, usando SendGrid, AWS SES, etc.
        logger.info(f"[SIMULAÇÃO] Email enviado para {email} - Assunto: {subject}")
        
    except Exception as e:
        logger.error(f"Erro ao enviar email de confirmação: {str(e)}", exc_info=True)

def create_user(email: str, password: str, nome: str, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """
    Cria um novo usuário no Firebase Authentication e no Firestore.
    
    Args:
        email: Email do usuário
        password: Senha do usuário
        nome: Nome do usuário
        is_admin: Se o usuário é administrador
        
    Returns:
        Dict com os dados do usuário criado ou None em caso de erro
    """
    try:
        # Cria o usuário no Firebase Authentication
        user = auth.create_user(
            email=email,
            password=password
        )
        
        # Cria o documento do usuário no Firestore
        user_data = {
            'uid': user.uid,
            'email': email,
            'nome': nome,
            'assinatura': False,  # Por padrão, a assinatura é falsa
            'is_admin': is_admin,
            'data_criacao': firestore.SERVER_TIMESTAMP,
            'data_atualizacao': firestore.SERVER_TIMESTAMP
        }
        
        db.collection('users').document(user.uid).set(user_data)
        
        print(f"✅ Usuário {email} criado com sucesso!")
        return user_data
        
    except Exception as e:
        print(f"❌ Erro ao criar usuário {email}: {str(e)}")
        return None
        return False
