# Histórico de Deploy - Gerador de Livros

## 27/06/2025 - Migração para Google Cloud Run

### Problemas Enfrentados
- Conflitos de dependências com `crewai`, `openai`, `langchain` e `chromadb`
- Erro com o pacote `pypika` que é dependência do `chromadb`
- Conflitos entre versões do `pydantic` (versão 1.10.8 vs 2.4.2)

### Soluções Implementadas
1. **Separação de serviços**:
   - Webhook do Stripe em um container separado
   - Frontend Streamlit em outro container

2. **Simplificação temporária**:
   - Criação de uma versão simplificada do aplicativo (`streamlit_app_simplified.py`)
   - Remoção temporária das dependências problemáticas de IA
   - Manutenção das funcionalidades essenciais (login, assinatura, Stripe)

3. **Arquivos de requisitos separados**:
   - `requirements.webhook.txt` - Apenas dependências necessárias para o webhook
   - `requirements.streamlit.txt` - Dependências para o frontend sem as bibliotecas de IA problemáticas

### Próximos Passos
1. Fazer o deploy da versão simplificada
2. Configurar variáveis de ambiente no Google Cloud Run
3. Atualizar a URL do webhook no Stripe
4. Adicionar gradualmente as funcionalidades de IA
5. Testar e monitorar o desempenho

### Comandos Utilizados
```bash
# Build e push das imagens Docker
gcloud builds submit --tag gcr.io/gerador-de-livros-464216/gerador-livros-webhook --file Dockerfile.webhook .
gcloud builds submit --tag gcr.io/gerador-de-livros-464216/gerador-livros-streamlit --file Dockerfile.streamlit .

# Deploy dos serviços
gcloud run deploy gerador-livros-webhook --image gcr.io/gerador-de-livros-464216/gerador-livros-webhook --platform managed --region southamerica-east1 --allow-unauthenticated --port 5000
gcloud run deploy gerador-livros-streamlit --image gcr.io/gerador-de-livros-464216/gerador-livros-streamlit --platform managed --region southamerica-east1 --allow-unauthenticated --port 8501
```
