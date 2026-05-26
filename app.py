#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《医药代表管理办法》解读培训 - 在线考试系统
Flask单文件部署版
"""

import os
import json
import random
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

# ============ 加载题库 ============
from questions import SINGLE_CHOICE_QUESTIONS, MULTIPLE_CHOICE_QUESTIONS

ALL_SINGLE = SINGLE_CHOICE_QUESTIONS
ALL_MULTIPLE = MULTIPLE_CHOICE_QUESTIONS

# 考试会话存储
exam_sessions = {}

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

    # 随机选题
    # 单选题：从题库随机抽取30道
    # 多选题：从题库随机抽取10道
    single_count = min(30, len(ALL_SINGLE))
    multiple_count = min(10, len(ALL_MULTIPLE))

    selected_single = random.sample(ALL_SINGLE, single_count)
    selected_multiple = random.sample(ALL_MULTIPLE, multiple_count)

    session_id = os.urandom(16).hex()

    exam_sessions[session_id] = {
        "username": username,
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
        "pass_score": 80
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
    passed = total_score >= 80

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
    return jsonify(result)

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

# ============ 主入口 ============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
