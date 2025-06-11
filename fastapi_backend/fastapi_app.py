from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from transformers import AutoProcessor, AutoModelForCausalLM
import torch
from PIL import Image

app = FastAPI()

# Allow cross-origin if frontend is running separately
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load multimodal model + processor
model_id = "ContactDoctor/Bio‑Medical‑MultiModal‑Llama‑3‑8B‑V1"
model = AutoModelForCausalLM.from_pretrained(model_id)
processor = AutoProcessor.from_pretrained(model_id)

@app.post("/chat/")
async def chat(prompt: str = Form(...), image: UploadFile = None):
    inputs = {"text": prompt}
    
    if image:
        pil_image = Image.open(image.file).convert("RGB")
        inputs["image"] = pil_image

    processed = processor(**inputs, return_tensors="pt")
    output = model.generate(**processed, max_new_tokens=512)
    response = processor.decode(output[0], skip_special_tokens=True)
    
    return {"response": response}
