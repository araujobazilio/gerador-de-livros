FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema necessárias
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar apenas os arquivos necessários para o webhook
COPY webhook_flask.py .
COPY requirements.webhook.txt ./requirements.txt

# Instalar dependências Python específicas para o webhook
# Configurar pip com timeout maior e mais tentativas de retry
RUN pip install --no-cache-dir --timeout 300 --retries 5 -r requirements.txt

# Expor a porta que o webhook usa
EXPOSE 5000

# Comando para iniciar o servidor webhook Flask
CMD ["python", "webhook_flask.py"]
