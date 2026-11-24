from fastapi import FastAPI


app = FastAPI()


@app.get("/Hystorial")
def Historial():
    return {"data":"Comming"}