from flask import Blueprint, request, Response, jsonify
from flasgger import swag_from
import logging
import json
from transformers import AutoTokenizer
import transformers
import traceback
import time
import torch
from repository.trainedmodel_repo import TrainedModelRepo
from repository.trainingfile_repo import TrainingFileRepo
from service.utils_controller import FILE_DIRECTORY
from train_model.finetune import train
from concurrent.futures import TimeoutError
from requests.exceptions import RequestException
import os

from utils.merge_csv_files import merge_csv_files


train_model_bp = Blueprint("train_model", __name__)
logger = logging.getLogger(__name__)


model = "./my-autotrain-llm"
tokenizer = AutoTokenizer.from_pretrained(model)
generator = transformers.pipeline(
    "text-generation", model=model, torch_dtype=torch.float16, framework="pt"
)


@train_model_bp.post("/train_model")
@swag_from(
    {
        "tags": ["Training"],
        "description": """
    此API用來啟動微調，會回傳開始訓練或是失敗。

    Input:
    - 可以接受與微調相關的任何參數，若未填寫則使用 default 參數。

    Returns:
    - JSON 回應訊息：
      - 成功時：返回開始訓練。
      - 失敗時：返回錯誤消息及相應的 HTTP 狀態碼。
    """,
        "parameters": [
            {
                "name": "config",
                "in": "body",
                "type": "object",
                "required": False,
                "description": "Training configuration",
                "schema": {
                    "type": "object",
                    "properties": {
                        "project_name": {"type": "string"},
                        "model_name": {"type": "string"},
                        "data_path": {"type": "string"},
                        "lr": {"type": "number"},
                        "epochs": {"type": "integer"},
                        "batch_size": {"type": "integer"},
                        "dataset_name": {"type": "string"},
                    },
                },
            }
        ],
        "responses": {
            200: {
                "description": "Training started successfully",
                "examples": {
                    "application/json": {
                        "status": "Training started successfully",
                    }
                },
            },
            500: {
                "description": "Internal server error",
                "examples": {
                    "application/json": {"status": "Error", "message": "Error message"}
                },
            },
        },
    }
)
def train_model():
    try:
        user_info = request.form.get("user_info")
        if user_info:
            user_info = json.loads(user_info)
        else:
            return jsonify({"error": "Forbidden"}), 403

        # 獲取 userId
        user_id = user_info.get("user_Id")
        # 取得user還沒train過的file
        not_trained_files = TrainingFileRepo.find_not_trained_file_by_user_id(
            user_id=user_id
        )
        files_path = [
            os.path.join(FILE_DIRECTORY, f.filename) for f in not_trained_files
        ]
        # merged_file是所有user上傳的file合成的訓練資料
        merged_file = merge_csv_files(files_path)
        default_config = {}
        saved_model = TrainedModelRepo.find_trainedmodel_by_user_id(user_id)
        # 如果是第一次練就生成new_model
        if saved_model is None:
            new_model = TrainedModelRepo.create_trainedmodel(user_id)
            if new_model is None:
                return jsonify({"status": "Error", "message": "Internel Error"}), 500
            default_config = {
                "project_name": new_model.modelname,
                "model_name": "./saved-taide-model",
                "data_path": FILE_DIRECTORY,
                "lr": 2e-4,
                "epochs": 3,
                "batch_size": 12,
                "trainer": "sft",
                "dataset_name": merged_file,
            }
        else:
            # 已經練過了，接續之前練過的model再訓練
            default_config = {
                "project_name": saved_model.modelname,
                "model_name": saved_model.modelname,
                "data_path": FILE_DIRECTORY,
                "lr": 2e-4,
                "epochs": 3,
                "batch_size": 12,
                "trainer": "sft",
                "dataset_name": merged_file,
            }
        # 全部的file一次載入並訓練
        custom_config = request.json
        if not custom_config:
            custom_config = default_config

        train_config = {**default_config, **custom_config}

        train(train_config)
        # train完成後要做的事
        # 把拿去train的資料is_trained設成true
        for f in not_trained_files:
            TrainingFileRepo.update_is_trained(f, True)
        # 刪掉合成的merged_file
        try:
            os.remove(os.path.join(FILE_DIRECTORY, merged_file))
        except Exception as e:
            logging.error(f"{e}")
        return (
            jsonify(
                {"status": "Training started successfully", "config": train_config}
            ),
            200,
        )
    except Exception as e:
        return jsonify({"status": "Error", "message": str(e)}), 500


@train_model_bp.post("/chat")
@swag_from(
    {
        "tags": ["Chat"],
        "description": """
     此 API 用於啟動聊天服務。

    Returns:
    - JSON 回應訊息：
      - 成功時：返回訊息。
      - 失敗時：返回錯誤訊息，可能是server錯誤或server反應間間過長。
    """,
        "parameters": [
            {
                "name": "input_text",
                "in": "body",
                "type": "string",
                "required": True,
                "description": "Input text for the chat",
            }
        ],
        "responses": {
            200: {
                "description": "Generated chat response",
                "examples": {"application/json": {"response": "Generated text"}},
            },
            500: {
                "description": "Internal server error",
                "examples": {
                    "application/json": {"status": "Error", "message": "Error message"}
                },
            },
        },
    }
)
def chat():
    try:
        input_text = request.json.get("input_text", "")
        if not input_text:
            return jsonify({"error": "Input text is required"}), 400
        instruction = "你是我的朋友，請你以和過去回答相同的語氣與我聊天，注意回答的內容要符合問題。"
        full_input = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": input_text},
        ]

        start_time = time.time()
        sequences = generator(
            full_input,
            do_sample=True,
            top_p=0.9,
            temperature=0.7,
            num_return_sequences=1,
            eos_token_id=tokenizer.eos_token_id,
            # max_new_tokens=50,
            max_length=70,
            # truncation=True,
        )

        # 之後會改小
        if time.time() - start_time > 3000:
            return jsonify({"error": "Request timeout, please try again"}), 504

        generated_text = ""
        for message in sequences[0]["generated_text"]:
            if message["role"] == "assistant":
                generated_text = message["content"]
                break

        response = json.dumps({"response": generated_text}, ensure_ascii=False)
        return Response(response, content_type="application/json; charset=utf-8")

    except (RequestException, TimeoutError) as e:
        return jsonify({"error": "Error in generating response, please try again"}), 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500
