# Comandos para deploy no Google Cloud Run

# 1. Build e push da imagem do webhook (se ainda não foi feito)
copy Dockerfile.webhook Dockerfile
gcloud builds submit --tag gcr.io/gerador-de-livros-464216/gerador-livros-webhook .
del Dockerfile

# 2. Deploy do webhook
gcloud run deploy gerador-livros-webhook `
  --image gcr.io/gerador-de-livros-464216/gerador-livros-webhook `
  --platform managed `
  --region southamerica-east1 `
  --allow-unauthenticated `
  --port 5000

# 3. Deploy do frontend Streamlit
gcloud run deploy gerador-livros-streamlit `
  --image gcr.io/gerador-de-livros-464216/gerador-livros-streamlit `
  --platform managed `
  --region southamerica-east1 `
  --allow-unauthenticated `
  --port 8501

# 4. Obter URLs dos serviços
Write-Host "URLs dos serviços implantados:"
gcloud run services describe gerador-livros-webhook --platform managed --region southamerica-east1 --format="value(status.url)"
gcloud run services describe gerador-livros-streamlit --platform managed --region southamerica-east1 --format="value(status.url)"
