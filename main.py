from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "running", "message": "Hello from FastAPI!"}
