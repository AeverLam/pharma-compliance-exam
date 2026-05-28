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
from datetime import datetime, timezone, timedelta
try:
    import requests
except ImportError:
    requests = None
from flask import Flask, request, jsonify, send_from_directory, make_response

app = Flask(__name__)

# ============ 加载题库 ============
from questions import SINGLE_CHOICE_QUESTIONS, MULTIPLE_CHOICE_QUESTIONS

ALL_SINGLE = SINGLE_CHOICE_QUESTIONS
ALL_MULTIPLE = MULTIPLE_CHOICE_QUESTIONS

# 考试会话存储
exam_sessions = {}

# 飞书多维表格持久化（数据在飞书云端，永不丢失）
FEISHU_APP_ID = "cli_a938ac2a24391bcb"
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
BITABLE_APP_TOKEN = "YW4ab8lvlaVL1QsLyjQcDSZEnCh"
BITABLE_TABLE_ID = "tblpi3HfyCVa4do8"
# 字段ID映射（必须与飞书多维表格实际字段一致）
BITABLE_FIELDS = {
    "username": "fldXEKRvpM",
    "province": "fldMvhlRaI", 
    "position": "fldZ7u68z9",
    "phone": "fldmxLCmom",
    "score": "fldLdR4KVe",
    "passed": "fldUS40mDp",
    "duration": "fldQkMnlyP",
    "time": "fld4mpG09e"
}

# 持久化存储文件
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "exam_records.json")
# 新增：单独文件存储目录（更可靠）
RECORDS_DIR = os.path.join(DATA_DIR, "records")
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
    # 初始化单独文件存储目录
    if not os.path.exists(RECORDS_DIR):
        os.makedirs(RECORDS_DIR, exist_ok=True)

def _get_token():
    """获取GitHub token（优先使用模块级GITHUB_TOKEN）"""
    # 优先使用模块级变量（已从环境变量读取）
    if GITHUB_TOKEN:
        return GITHUB_TOKEN
    # 回退到环境变量读取
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    return ""

def git_load_records():
    """从GitHub加载记录（首次启动时恢复历史数据）"""
    token = _get_token()
    if not requests or not token:
        print(f"[{datetime.now()}] GitHub token not available")
        return None
    try:
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        resp = requests.get(GITHUB_API_URL, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10)
        if resp.status_code == 200:
            raw = base64.b64decode(resp.json()["content"]).decode()
            records = json.loads(raw)
            print(f"[{datetime.now()}] Successfully loaded {len(records)} records from GitHub")
            return records
        else:
            print(f"[{datetime.now()}] GitHub API error: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"[{datetime.now()}] GitHub load error: {e}")
    return None

def sync_from_github():
    """启动时从GitHub恢复数据"""
    records = git_load_records()
    if records:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

def save_record_to_file(record):
    """保存考试记录到本地（单独文件 + 汇总文件）+ GitHub备份 + 飞书多维表格"""
    init_data_file()
    
    # 【方案A核心】单独文件存储 - 最可靠
    # 每个记录单独存一个文件，避免文件损坏导致全部丢失
    record_id = record.get("submit_time", "").replace(":", "-").replace("+", "_") + "_" + record.get("username", "unknown")
    record_file = os.path.join(RECORDS_DIR, f"{record_id}.json")
    try:
        with open(record_file, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        print(f"[{datetime.now()}] Saved individual record: {record_file}")
    except Exception as e:
        print(f"[{datetime.now()}] Failed to save individual record: {e}")
    
    # 同时更新汇总文件（兼容旧逻辑）
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            records = json.load(f)
    except:
        records = []
    records.append(record)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    # GitHub备份（异步，失败不影响主流程）
    if requests:
        threading.Thread(target=async_push_to_github, args=(records,), daemon=True).start()
    
    # 飞书多维表格异步推送
    if requests and FEISHU_APP_SECRET:
        threading.Thread(target=_save_to_bitable, args=(record,), daemon=True).start()

def sync_push_to_github(records):
    """同步推送到 GitHub（阻塞式，确保数据保存成功）"""
    token = _get_token()
    if not requests or not token:
        print(f"[{datetime.now()}] GitHub push skipped: token not available")
        return False
    
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    content = base64.b64encode(json.dumps(records, ensure_ascii=False, indent=2).encode()).decode()
    sha = ""
    
    # 获取当前文件的 SHA
    try:
        resp = requests.get(GITHUB_API_URL, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10)
        if resp.status_code == 200:
            sha = resp.json().get("sha", "")
    except Exception as e:
        print(f"[{datetime.now()}] GitHub get SHA error: {e}")
    
    # 推送数据
    data = {"message": f"自动保存 {len(records)}条记录", "content": content, "branch": GITHUB_BRANCH}
    if sha:
        data["sha"] = sha
    
    try:
        resp = requests.put(GITHUB_API_URL, headers=headers, json=data, timeout=15)
        if resp.status_code in [200, 201]:
            print(f"[{datetime.now()}] Successfully pushed {len(records)} records to GitHub")
            return True
        else:
            print(f"[{datetime.now()}] GitHub push error: {resp.status_code} - {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[{datetime.now()}] GitHub push error: {e}")
        return False

# 保留异步推送函数（供其他场景使用）
def async_push_to_github(records):
    """异步推送到 GitHub（后台线程）"""
    threading.Thread(target=sync_push_to_github, args=(records,), daemon=True).start()

def _save_to_bitable(record):
    """保存到飞书多维表格（云端持久化，永不丢失）"""
    if not requests or not FEISHU_APP_SECRET:
        print(f"[{datetime.now()}] Bitable save skipped: FEISHU_APP_SECRET not set")
        return
    
    try:
        # 获取 token
        r = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}, timeout=10)
        token = r.json().get("tenant_access_token", "")
        if not token:
            print(f"[{datetime.now()}] Bitable save failed: no tenant_access_token, response: {r.json()}")
            return
        
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        # 解析提交时间为毫秒时间戳
        submit_time_str = record.get("submit_time", "")
        try:
            # 处理 ISO 格式时间字符串（带时区）
            if submit_time_str:
                from datetime import datetime as dt
                # 处理 +08:00 时区格式
                if "+" in submit_time_str:
                    dt_obj = dt.fromisoformat(submit_time_str)
                    now_ts = int(dt_obj.timestamp() * 1000)
                else:
                    dt_obj = dt.fromisoformat(submit_time_str.replace('Z', '+00:00'))
                    now_ts = int(dt_obj.timestamp() * 1000)
            else:
                now_ts = int(datetime.now().timestamp() * 1000)
        except Exception as e:
            print(f"[{datetime.now()}] Time parse error: {e}, using current time")
            now_ts = int(datetime.now().timestamp() * 1000)
        
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"
        
        # 构建字段数据（确保类型正确）
        fields = {
            BITABLE_FIELDS["username"]: str(record.get("username", "")),
            BITABLE_FIELDS["province"]: str(record.get("province", "")),
            BITABLE_FIELDS["position"]: str(record.get("position", "")),
            BITABLE_FIELDS["phone"]: str(record.get("phone", "")),
            BITABLE_FIELDS["score"]: float(record.get("score", 0)),
            BITABLE_FIELDS["passed"]: "通过" if record.get("passed") else "未通过",
            BITABLE_FIELDS["duration"]: float(record.get("duration_seconds", 0)),
            BITABLE_FIELDS["time"]: now_ts
        }
        
        data = {"fields": fields}
        
        print(f"[{datetime.now()}] Saving to Bitable: {fields}")
        
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        resp_data = resp.json()
        
        if resp.status_code == 200:
            print(f"[{datetime.now()}] Successfully saved record to Bitable: {record.get('username', 'unknown')}")
        else:
            print(f"[{datetime.now()}] Bitable save error: {resp.status_code} - {resp_data}")
    except Exception as e:
        print(f"[{datetime.now()}] Bitable save error: {e}")
        import traceback
        print(traceback.format_exc())

def load_all_records():
    """读取所有考试记录（优先从单独文件目录读取，更可靠）"""
    init_data_file()
    
    # 【方案A核心】优先从单独文件目录读取
    # 这样即使汇总文件损坏，也能恢复数据
    individual_records = []
    try:
        if os.path.exists(RECORDS_DIR):
            for filename in os.listdir(RECORDS_DIR):
                if filename.endswith('.json'):
                    filepath = os.path.join(RECORDS_DIR, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            record = json.load(f)
                            individual_records.append(record)
                    except Exception as e:
                        print(f"[{datetime.now()}] Failed to load {filename}: {e}")
            
            if individual_records:
                # 按提交时间排序
                individual_records.sort(key=lambda x: x.get('submit_time', ''), reverse=True)
                print(f"[{datetime.now()}] Loaded {len(individual_records)} records from individual files")
                
                # 同步到汇总文件（修复可能损坏的汇总文件）
                try:
                    with open(DATA_FILE, 'w', encoding='utf-8') as f:
                        json.dump(individual_records, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"[{datetime.now()}] Failed to sync to DATA_FILE: {e}")
                
                return individual_records
    except Exception as e:
        print(f"[{datetime.now()}] Failed to load individual records: {e}")
    
    # 回退到汇总文件
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            records = json.load(f)
        if records:
            return records
    except:
        pass
    
    # 最后尝试从GitHub恢复
    sync_from_github()
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

# ============ 前端页面 ============
@app.route("/")
def index():
    resp = make_response(send_from_directory('.', 'exam.html'))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

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

def check_user_exam_attempts(username, province, position):
    """检查用户已考试次数和最高成绩
    
    返回: (attempts_count, highest_score, records)
    - attempts_count: 已考试次数 (0-2)，只算成功提交的
    - highest_score: 最高成绩
    - records: 该用户的所有考试记录
    """
    records = load_all_records()
    user_records = [
        r for r in records 
        if r.get("username") == username 
        and r.get("province") == province 
        and r.get("position") == position
    ]
    attempts = len(user_records)
    highest_score = max([r.get("score", 0) for r in user_records], default=0)
    return attempts, highest_score, user_records


@app.route("/api/exam/check", methods=["POST"])
def check_exam_eligibility():
    """检查用户是否有考试资格"""
    data = request.json or {}
    username = data.get("username", "").strip()
    province = data.get("province", "").strip()
    position = data.get("position", "").strip()
    
    print(f"[{datetime.now()}] Check eligibility: username={username}, province={province}, position={position}")
    
    if not username or not province or not position:
        return jsonify({
            "eligible": False,
            "message": "请填写完整的个人信息（姓名、省公司/部门、职位）"
        })
    
    attempts, highest_score, records = check_user_exam_attempts(username, province, position)
    
    print(f"[{datetime.now()}] Check result: attempts={attempts}, highest_score={highest_score}")
    
    if attempts >= 2:
        return jsonify({
            "eligible": False,
            "attempts": attempts,
            "highest_score": highest_score,
            "message": f"您已完成 {attempts} 次考试，最高成绩为 {highest_score} 分。每人仅限 2 次考试机会。"
        })
    
    return jsonify({
        "eligible": True,
        "attempts": attempts,
        "highest_score": highest_score,
        "remaining": 2 - attempts,
        "message": f"您还有 {2 - attempts} 次考试机会" if attempts > 0 else "首次考试，祝您好运！"
    })


@app.route("/api/exam/start", methods=["POST"])
def start_exam():
    """开始考试，随机选题"""
    data = request.json or {}
    username = data.get("username", "匿名用户").strip()
    province = data.get("province", "").strip()
    position = data.get("position", "").strip()
    phone = data.get("phone", "")
    
    # 检查考试次数限制
    attempts, highest_score, _ = check_user_exam_attempts(username, province, position)
    if attempts >= 2:
        return jsonify({
            "error": True,
            "message": f"您已完成 {attempts} 次考试，最高成绩为 {highest_score} 分。每人仅限 2 次考试机会。"
        }), 403

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
    
    # 使用北京时间（UTC+8）
    beijing_tz = timezone(timedelta(hours=8))
    beijing_now = datetime.now(beijing_tz)

    exam_sessions[session_id] = {
        "username": username,
        "province": province,
        "position": position,
        "phone": phone,
        "single": selected_single,
        "multiple": selected_multiple,
        "answers": {},
        "start_time": beijing_now.isoformat(),
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
    
    # 详细日志便于排查问题
    print(f"[{datetime.now()}] Submit exam request: session_id={session_id}, answers_count={len(answers)}")
    print(f"[{datetime.now()}] Active sessions: {list(exam_sessions.keys())}")

    if not session_id or session_id not in exam_sessions:
        return jsonify({"error": "考试会话不存在或已过期"}), 400

    session = exam_sessions[session_id]
    if session["status"] == "completed":
        return jsonify({"error": "该考试已完成提交"}), 400

    session["answers"] = answers
    session["status"] = "completed"
    # 使用北京时间（UTC+8）
    beijing_tz = timezone(timedelta(hours=8))
    session["end_time"] = datetime.now(beijing_tz).isoformat()

    # 评分
    single_score_total = 0
    multiple_score_total = 0
    single_correct = 0
    multiple_correct = 0
    single_wrong = 0
    multiple_wrong = 0
    details = []

    # 评分单选题（题号从1开始）
    for i, q in enumerate(session["single"], 1):
        user_answer = answers.get(f"single_{q['id']}")
        correct = user_answer is not None and user_answer == q["answer"]
        if correct:
            single_score_total += 2
            single_correct += 1
        else:
            single_wrong += 1
        details.append({
            "id": q["id"],
            "index": i,  # 题号（从1开始，连续编号）
            "type": "single",
            "question": q["question"],
            "options": q["options"],
            "answer": q["answer"],
            "user_answer": user_answer,
            "correct": correct,
            "explanation": q["explanation"]
        })

    # 评分多选题（题号从31开始，接在单选题后面）
    single_count = len(session["single"])
    for i, q in enumerate(session["multiple"], single_count + 1):
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
            "index": i,  # 题号（连续编号，接在单选题后面）
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
    
    # 持久化保存考试记录（使用北京时间）
    beijing_tz = timezone(timedelta(hours=8))
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
        "submit_time": datetime.now(beijing_tz).isoformat()
    }
    save_record_to_file(record)
    
    return jsonify(result)

@app.route("/admin")
def admin_page():
    resp = make_response(send_from_directory('.', 'admin.html'))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/api/admin/records", methods=["POST"])
def get_admin_records():
    data = request.json or {}
    password = data.get("password", "")
    if password != ADMIN_PASSWORD:
        return jsonify({"error": "密码错误"}), 401
    records = load_all_records()
    
    # 只保留每个人的最高成绩记录
    # 用 (username, province, position) 作为唯一标识
    best_records = {}
    for r in records:
        key = (r.get("username", ""), r.get("province", ""), r.get("position", ""))
        if key not in best_records:
            best_records[key] = r
        else:
            # 保留分数更高的记录
            if r.get("score", 0) > best_records[key].get("score", 0):
                best_records[key] = r
    
    # 转换为列表并按分数降序排列
    result_records = list(best_records.values())
    result_records.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    return jsonify({
        "total": len(result_records),
        "records": result_records
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

# 先读取本地数据
local_records = []
try:
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        local_records = json.load(f)
    print(f"[{datetime.now()}] 本地数据: {len(local_records)} 条记录")
except Exception as e:
    print(f"[{datetime.now()}] 读取本地数据失败: {e}")

# 尝试从GitHub恢复（但不覆盖本地已有数据）
print(f"[{datetime.now()}] 正在从GitHub恢复数据...")
records = git_load_records()
if records is not None and len(records) > 0:
    # 合并本地和GitHub数据（去重）
    existing_ids = {r.get("submit_time", "") + r.get("username", "") for r in local_records}
    new_records = [r for r in records if (r.get("submit_time", "") + r.get("username", "")) not in existing_ids]
    if new_records:
        local_records.extend(new_records)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(local_records, f, ensure_ascii=False, indent=2)
        print(f"[{datetime.now()}] 从GitHub合并了 {len(new_records)} 条新记录，总计 {len(local_records)} 条")
    else:
        print(f"[{datetime.now()}] GitHub数据与本地相同，无需合并")
elif records is not None and len(records) == 0:
    print(f"[{datetime.now()}] GitHub数据为空，保留本地 {len(local_records)} 条记录")
else:
    print(f"[{datetime.now()}] 从GitHub恢复失败，使用本地 {len(local_records)} 条记录")

# ============ 主入口 ============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
