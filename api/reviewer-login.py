from fastapi import FastAPI
from main import ReviewerLoginRequest, reviewer_login

app = FastAPI()

@app.post("/")
@app.post("/api/reviewer-login")
def reviewer_login_endpoint(req: ReviewerLoginRequest):
    return reviewer_login(req)
