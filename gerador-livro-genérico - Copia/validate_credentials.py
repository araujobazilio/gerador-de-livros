import json
import os
from pathlib import Path

def validate_credentials():
    print("=== Validação do arquivo de credenciais do Firebase ===\n")
    
    # 1. Verifica se o arquivo existe
    cred_path = Path(__file__).parent / 'firebase-credentials.json'
    print(f"1. Verificando arquivo em: {cred_path}")
    
    if not cred_path.exists():
        print("❌ ERRO: Arquivo não encontrado!")
        return False
    
    print("✅ Arquivo encontrado")
    
    # 2. Verifica permissões
    if not os.access(cred_path, os.R_OK):
        print("❌ ERRO: Sem permissão para ler o arquivo!")
        return False
    
    print("✅ Permissão de leitura concedida")
    
    # 3. Tenta ler e validar o JSON
    try:
        with open(cred_path, 'r', encoding='utf-8') as f:
            cred_data = json.load(f)
        print("✅ Arquivo JSON é válido")
    except json.JSONDecodeError as e:
        print(f"❌ ERRO: Arquivo JSON inválido - {str(e)}")
        return False
    except Exception as e:
        print(f"❌ ERRO ao ler o arquivo: {str(e)}")
        return False
    
    # 4. Verifica campos obrigatórios
    required_fields = [
        'type',
        'project_id',
        'private_key_id',
        'private_key',
        'client_email',
        'client_id',
        'auth_uri',
        'token_uri',
        'auth_provider_x509_cert_url',
        'client_x509_cert_url'
    ]
    
    missing_fields = [field for field in required_fields if field not in cred_data]
    
    if missing_fields:
        print("❌ ERRO: Campos obrigatórios ausentes:")
        for field in missing_fields:
            print(f"   - {field}")
        return False
    
    print("✅ Todos os campos obrigatórios estão presentes")
    
    # 5. Exibe informações básicas (sem dados sensíveis)
    print("\nInformações do arquivo de credenciais:")
    print(f"   - Tipo: {cred_data.get('type')}")
    print(f"   - Project ID: {cred_data.get('project_id')}")
    print(f"   - Client Email: {cred_data.get('client_email')}")
    print(f"   - Private Key ID: {cred_data.get('private_key_id')[:8]}...")
    
    # 6. Verifica se a chave privada está no formato correto
    private_key = cred_data.get('private_key', '')
    if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
        print("❌ AVISO: A chave privada pode não estar no formato correto")
    else:
        print("✅ Formato da chave privada parece correto")
    
    return True

if __name__ == "__main__":
    print("Iniciando validação do arquivo de credenciais...\n")
    if validate_credentials():
        print("\n✅ Validação concluída com sucesso!")
    else:
        print("\n❌ A validação falhou. Verifique as mensagens acima.")
        exit(1)
