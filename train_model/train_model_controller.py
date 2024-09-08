from flask import Blueprint, request, Response
import logging
import json
from transformers import AutoTokenizer
import transformers
import torch


train_model_bp = Blueprint("train_model", __name__)
logger = logging.getLogger(__name__)

model = "./my-autotrain-llm"
tokenizer = AutoTokenizer.from_pretrained(model)
pipeline = transformers.pipeline(
    "text-generation",
    model=model,
    torch_dtype=torch.float16,
    framework="pt"
)


@train_model_bp.post("/training_file")
def upload_training_file():
    pass

@train_model_bp.post('/chat')
def chat():
    
    input_text = request.json.get('input_text', '')  
    instruction = "請用朋友語氣回答："  

    full_input = f"{instruction}{input_text}"

    sequences = pipeline(
        full_input,
        do_sample=True, 
        top_p=0.9, 
        temperature=0.7,
        num_return_sequences=1,
        eos_token_id=tokenizer.eos_token_id,
        max_length=50,
        truncation=True,
    )
    
    for seq in sequences:
        generated_text = seq['generated_text']
        
        print(f"Generated Text: {generated_text}")

        result = generated_text.replace(instruction, "").replace(input_text, "").strip()

        response = json.dumps({"response": result}, ensure_ascii=False)
        return Response(response, content_type="application/json; charset=utf-8")