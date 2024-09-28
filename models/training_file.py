from sqlalchemy import DateTime, func
from extensions import db
import uuid


class TrainingFile(db.Model):
    __tablename__ = "training_file"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    filename = db.Column(db.String(50), nullable=False)
    # original_file_name是user上傳時，本機的file name
    original_file_name = db.Column(db.String(255), nullable=False)
    is_trained: bool = db.Column(db.Boolean, default=False, nullable=False)
    upload_time = db.Column(DateTime(timezone=True), default=func.now())

    # 上傳file後先生成TrainingFile物件，再從TrainingFile object拿filename做為檔名存file。
    def __init__(self, user_id, filename, original_file_name):
        self.user_id = user_id
        self.filename = filename
        self.original_file_name = original_file_name
        self.is_trained = False

    def set_is_trained(self, is_trained: bool):
        self.is_trained = is_trained
