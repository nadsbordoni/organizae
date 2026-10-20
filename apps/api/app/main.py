from fastapi import FastAPI

app = FastAPI(
    title="Organizaê API",
    description="API de gerenciamento e agendamentos",
    version="0.1.0"
)

@app.get("/health")
def health():
    return {"status": "ok"}