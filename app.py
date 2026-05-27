#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《医药代表管理办法》解读培训 - 在线考试系统
Flask单文件部署版
"""

import os
import json
import random
import base64
import threading
from datetime import datetime
try:
    import requests
except ImportError:
    requests = None
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

# ============ 加载题库 ============
from questions import SINGLE_CHOICE_QUESTIONS, MULTIPLE_CHOICE_QUESTIONS

ALL_SINGLE = SINGLE_CHOICE_QUESTIONS
ALL_MULTIPLE = MULTIPLE_CHOICE_QUESTIONS

# 考试会话存储
exam_sessions = {}

# 持久化存储文件
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "exam_records.json")
ADMIN_PASSWORD = "livzon2026"

# GitHub 持久化存储（部署重启不丢数据）
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "AeverLam/pharma-compliance-exam"
GITHUB_BRANCH = "main"
GITHUB_DATA_PATH = "data/exam_records.json"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DATA_PATH}"

def init_data_file():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)

def _get_token():
    """获取GitHub token（环境变量 > gitconfig）"""
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    try:
        import re
        cfg = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.git', 'config')).read()
        m = re.search(r'https://[^:]+:([^@]+)@github\.com', cfg)
        if m:
            return m.group(1)
    except:
        pass
    return ""

def git_load_records():
    """从GitHub加载记录（首次启动时恢复历史数据）"""
    token = _get_token()
    if not requests or not token:
        return None
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        resp = requests.get(GITHUB_API_URL, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10)
        if resp.status_code == 200:
            raw = base64.b64decode(resp.json()["content"]).decode()
            return json.loads(raw)
    except:
        pass
    return None

def sync_from_github():
    """启动时从GitHub恢复数据"""
    records = git_load_records()
    if records:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

def save_record_to_file(record):
    """保存考试记录到本地 + GitHub"""
    init_data_file()
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            records = json.load(f)
    except:
        records = []
    records.append(record)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    # 异步推送到 GitHub 永久存储
    if requests and GITHUB_TOKEN:
        threading.Thread(target=async_push_to_github, args=(records,), daemon=True).start()

def async_push_to_github(records):
    """异步推送到 GitHub"""
    token = _get_token()
    if not requests or not token:
        return
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    content = base64.b64encode(json.dumps(records, ensure_ascii=False, indent=2).encode()).decode()
    try:
        resp = requests.get(GITHUB_API_URL, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10)
        sha = resp.json().get("sha", "") if resp.status_code == 200 else ""
    except:
        sha = ""
    data = {"message": f"自动保存 {len(records)}条记录", "content": content, "branch": GITHUB_BRANCH}
    if sha:
        data["sha"] = sha
    try:
        requests.put(GITHUB_API_URL, headers=headers, json=data, timeout=15)
    except:
        pass

def load_all_records():
    """读取所有考试记录（本地+GitHub双重恢复）"""
    init_data_file()
    records = []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            records = json.load(f)
    except:
        pass
    if not records:
        sync_from_github()
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                records = json.load(f)
        except:
            pass
    return records

# ============ 前端页面 ============
@app.route("/")
def index():
    return send_from_directory('.', 'exam.html')

@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

# ============ API 接口 ============

@app.route("/api/questions/count")
def get_question_count():
    """获取题库数量"""
    return jsonify({
        "single": len(ALL_SINGLE),
        "multiple": len(ALL_MULTIPLE),
        "total": len(ALL_SINGLE) + len(ALL_MULTIPLE)
    })

@app.route("/api/exam/start", methods=["POST"])
def start_exam():
    """开始考试，随机选题"""
    data = request.json or {}
    username = data.get("username", "匿名用户")
    province = data.get("province", "")
    position = data.get("position", "")
    phone = data.get("phone", "")

    # 标识IIT题目（ID >= 111的单选题和ID >= 62的多选题）
    iit_single = [q for q in ALL_SINGLE if q.get("id") and isinstance(q["id"], str) and int(q["id"][1:]) >= 111]
    iit_multiple = [q for q in ALL_MULTIPLE if q.get("id") and isinstance(q["id"], str) and int(q["id"][1:]) >= 62]
    
    # 随机选题
    single_count = min(30, len(ALL_SINGLE))
    multiple_count = min(10, len(ALL_MULTIPLE))
    
    # 每次考试至少保证2题来自IIT案例
    non_iit_single = [q for q in ALL_SINGLE if q not in iit_single]
    non_iit_multiple = [q for q in ALL_MULTIPLE if q not in iit_multiple]
    
    selected_single = []
    selected_multiple = []
    
    # 先确保至少2题IIT
    random.shuffle(iit_single)
    random.shuffle(iit_multiple)
    if iit_single:
        selected_single.extend(iit_single[:2])
    if iit_multiple and len(selected_single) < 2:
        selected_multiple.append(iit_multiple[0])
    
    # 补满剩余题目
    remaining_single = single_count - len(selected_single)
    remaining_multiple = multiple_count - len(selected_multiple)
    
    random.shuffle(non_iit_single)
    random.shuffle(non_iit_multiple)
    selected_single.extend(non_iit_single[:remaining_single])
    selected_multiple.extend(non_iit_multiple[:remaining_multiple])
    
    random.shuffle(selected_single)
    random.shuffle(selected_multiple)

    session_id = os.urandom(16).hex()

    exam_sessions[session_id] = {
        "username": username,
        "province": province,
        "position": position,
        "phone": phone,
        "single": selected_single,
        "multiple": selected_multiple,
        "answers": {},
        "start_time": datetime.now().isoformat(),
        "status": "in_progress"
    }

    # 返回题目（不包含答案）
    response = {
        "session_id": session_id,
        "username": username,
        "single": [
            {
                "id": q["id"],
                "index": i,
                "question": q["question"],
                "options": q["options"],
                "type": "single"
            }
            for i, q in enumerate(selected_single)
        ],
        "multiple": [
            {
                "id": q["id"],
                "index": i,
                "question": q["question"],
                "options": q["options"],
                "type": "multiple"
            }
            for i, q in enumerate(selected_multiple)
        ],
        "single_score": 2,
        "multiple_score": 4,
        "total": single_count * 2 + multiple_count * 4,
        "pass_score": 90
    }

    return jsonify(response)

@app.route("/api/exam/submit", methods=["POST"])
def submit_exam():
    """提交考试并评分"""
    data = request.json or {}
    session_id = data.get("session_id")
    answers = data.get("answers", {})

    if not session_id or session_id not in exam_sessions:
        return jsonify({"error": "考试会话不存在或已过期"}), 400

    session = exam_sessions[session_id]
    if session["status"] == "completed":
        return jsonify({"error": "该考试已完成提交"}), 400

    session["answers"] = answers
    session["status"] = "completed"
    session["end_time"] = datetime.now().isoformat()

    # 评分
    single_score_total = 0
    multiple_score_total = 0
    single_correct = 0
    multiple_correct = 0
    single_wrong = 0
    multiple_wrong = 0
    details = []

    # 评分单选题
    for q in session["single"]:
        user_answer = answers.get(f"single_{q['id']}")
        correct = user_answer is not None and user_answer == q["answer"]
        if correct:
            single_score_total += 2
            single_correct += 1
        else:
            single_wrong += 1
        details.append({
            "id": q["id"],
            "type": "single",
            "question": q["question"],
            "options": q["options"],
            "answer": q["answer"],
            "user_answer": user_answer,
            "correct": correct,
            "explanation": q["explanation"]
        })

    # 评分多选题
    for q in session["multiple"]:
        user_answer = answers.get(f"multiple_{q['id']}", [])
        correct_answer = q["answer"]
        # 多选题：完全正确才得分
        if isinstance(user_answer, list) and sorted(user_answer) == sorted(correct_answer):
            multiple_score_total += 4
            multiple_correct += 1
        else:
            multiple_wrong += 1
        details.append({
            "id": q["id"],
            "type": "multiple",
            "question": q["question"],
            "options": q["options"],
            "answer": correct_answer,
            "user_answer": user_answer,
            "correct": sorted(user_answer) == sorted(correct_answer) if isinstance(user_answer, list) else False,
            "explanation": q["explanation"]
        })

    total_score = single_score_total + multiple_score_total
    passed = total_score >= 90

    result = {
        "username": session["username"],
        "single_score": single_score_total,
        "multiple_score": multiple_score_total,
        "total_score": total_score,
        "single_correct": single_correct,
        "single_total": len(session["single"]),
        "multiple_correct": multiple_correct,
        "multiple_total": len(session["multiple"]),
        "passed": passed,
        "details": details,
        "start_time": session["start_time"],
        "end_time": session["end_time"]
    }

    session["result"] = result
    
    # 计算考试用时（分钟）
    duration_seconds = 0
    try:
        start = datetime.fromisoformat(session["start_time"])
        end = datetime.fromisoformat(session["end_time"])
        duration_seconds = int((end - start).total_seconds())
    except:
        pass
    
    # 持久化保存考试记录
    record = {
        "username": session["username"],
        "province": session.get("province", ""),
        "position": session.get("position", ""),
        "phone": session.get("phone", ""),
        "score": total_score,
        "single_score": single_score_total,
        "multiple_score": multiple_score_total,
        "single_correct": single_correct,
        "single_total": len(session["single"]),
        "multiple_correct": multiple_correct,
        "multiple_total": len(session["multiple"]),
        "passed": passed,
        "duration_seconds": duration_seconds,
        "start_time": session["start_time"],
        "end_time": session["end_time"],
        "submit_time": datetime.now().isoformat()
    }
    save_record_to_file(record)
    
    return jsonify(result)

@app.route("/admin")
def admin_page():
    return send_from_directory('.', 'admin.html')

@app.route("/api/admin/records", methods=["POST"])
def get_admin_records():
    data = request.json or {}
    password = data.get("password", "")
    if password != ADMIN_PASSWORD:
        return jsonify({"error": "密码错误"}), 401
    records = load_all_records()
    # 按提交时间倒序
    records.reverse()
    return jsonify({
        "total": len(records),
        "records": records
    })

@app.route("/api/questions/all")
def get_all_questions():
    """导出全部题库（管理员用）"""
    return jsonify({
        "single": [
            {
                "id": q["id"],
                "question": q["question"],
                "options": q["options"],
                "answer": q["answer"],
                "explanation": q["explanation"]
            }
            for q in ALL_SINGLE
        ],
        "multiple": [
            {
                "id": q["id"],
                "question": q["question"],
                "options": q["options"],
                "answer": q["answer"],
                "explanation": q["explanation"]
            }
            for q in ALL_MULTIPLE
        ]
    })

# ============ 启动时从GitHub恢复历史记录 ============
init_data_file()
sync_from_github()

# ============ 主入口 ============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
