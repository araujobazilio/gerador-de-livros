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

## Deploy original (com problemas)
gcloud run deploy gerador-livros-webhook --image gcr.io/gerador-de-livros-464216/gerador-livros-webhook --platform managed --region southamerica-east1 --allow-unauthenticated --port 5000

## Deploy bem-sucedido (27/06/2025)
# Deploy do webhook minimalista
gcloud builds submit --tag gcr.io/gerador-de-livros-464216/gerador-livros-webhook-minimal .
gcloud run deploy gerador-livros-webhook --image gcr.io/gerador-de-livros-464216/gerador-livros-webhook-minimal --platform managed --region southamerica-east1 --allow-unauthenticated

# Deploy do frontend Streamlit
gcloud run deploy gerador-livros-streamlit --image gcr.io/gerador-de-livros-464216/gerador-livros-streamlit --platform managed --region southamerica-east1 --allow-unauthenticated --port 8501 --set-env-vars="WEBHOOK_URL=https://gerador-livros-webhook-789118129373.southamerica-east1.run.app/webhook"
```

## URLs dos serviços
- Webhook: https://gerador-livros-webhook-789118129373.southamerica-east1.run.app
- Frontend: https://gerador-livros-streamlit-789118129373.southamerica-east1.run.app

## Configuração de variáveis de ambiente

### Webhook
```bash
gcloud run services update gerador-livros-webhook \
  --region=southamerica-east1 \
  --update-env-vars="ADMIN_EMAIL=[email],STRIPE_SECRET_KEY=[chave],STRIPE_WEBHOOK_SECRET=[segredo],APP_URL=[url_frontend],ARQUIVO_USUARIOS=usuarios.csv,FIREBASE_PROJECT_ID=[projeto_id]"
```

### Frontend Streamlit
```bash
# Primeira parte das variáveis
gcloud run services update gerador-livros-streamlit \
  --region=southamerica-east1 \
  --update-env-vars="ADMIN_EMAIL=[email],STRIPE_SECRET_KEY=[chave],STRIPE_PAYMENT_LINK=[link],STRIPE_PRICE_ID=[price_id],APP_URL=[url_frontend],ARQUIVO_USUARIOS=usuarios.csv"

# Segunda parte das variáveis
gcloud run services update gerador-livros-streamlit \
  --region=southamerica-east1 \
  --update-env-vars="FIREBASE_API_KEY=[api_key],FIREBASE_AUTH_DOMAIN=[auth_domain],FIREBASE_PROJECT_ID=[projeto_id],FIREBASE_STORAGE_BUCKET=[bucket],FIREBASE_MESSAGING_SENDER_ID=[sender_id],FIREBASE_APP_ID=[app_id],FIREBASE_MEASUREMENT_ID=[measurement_id],WEBHOOK_URL=[url_webhook]/webhook"
```

**Nota:** Os valores reais das variáveis foram substituídos por placeholders por motivos de segurança.
