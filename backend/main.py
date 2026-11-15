
from fastapi import FastAPI

app = FastAPI(
    title="AGENT LAB",
    description="Plataforma local de orquestación multiagente",
    version="0.1.0"
)

@app.get("/")
def home():
    return {
        "project": "AGENT LAB",
        "status": "online",
        "message": "Nuestro laboratorio está funcionando"
    }
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AGENT LAB API",
        "version": "0.1.0"
    }