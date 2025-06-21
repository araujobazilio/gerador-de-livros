import firebase_admin
from firebase_admin import credentials, firestore
import os

def init_firebase():
    """Inicializa o Firebase com as credenciais do arquivo JSON."""
    try:
        # Verifica se o Firebase já foi inicializado
        if not firebase_admin._apps:
            # Tenta carregar as credenciais do arquivo firebase-credentials.json
            cred_path = os.path.join(os.path.dirname(__file__), 'firebase-credentials.json')
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                print("Firebase inicializado com sucesso!")
            else:
                print("Erro: Arquivo de credenciais não encontrado.")
                return None
        return firestore.client()
    except Exception as e:
        print(f"Erro ao inicializar o Firebase: {e}")
        return None

# Inicializa o Firestore
db = init_firebase()

def get_user_by_email(email):
    """Busca um usuário pelo email no Firestore."""
    if not db:
        return None
    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        docs = query.stream()
        for doc in docs:
            return {**doc.to_dict(), 'id': doc.id}
        return None
    except Exception as e:
        print(f"Erro ao buscar usuário: {e}")
        return None

def update_subscription_status(email, status=True):
    """Atualiza o status de assinatura de um usuário no Firestore."""
    if not db:
        return False
    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        docs = query.stream()
        for doc in docs:
            doc.reference.update({'assinatura': status})
            return True
        return False
    except Exception as e:
        print(f"Erro ao atualizar assinatura: {e}")
        return False
