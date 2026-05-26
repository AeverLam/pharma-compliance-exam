# -*- coding: utf-8 -*-
"""
《医药代表管理办法》解读培训 - 考试题库
题库从 questions.json 加载
"""
import json, os

_data = None

def _load():
    global _data
    if _data is None:
        path = os.path.join(os.path.dirname(__file__), 'questions.json')
        with open(path, 'r', encoding='utf-8') as f:
            _data = json.load(f)
    return _data

SINGLE_CHOICE_QUESTIONS = _load()["single"]
MULTIPLE_CHOICE_QUESTIONS = _load()["multiple"]

if __name__ == "__main__":
    print(f"Total single-choice questions: {len(SINGLE_CHOICE_QUESTIONS)}")
    print(f"Total multiple-choice questions: {len(MULTIPLE_CHOICE_QUESTIONS)}")
    print(f"Total questions: {len(SINGLE_CHOICE_QUESTIONS) + len(MULTIPLE_CHOICE_QUESTIONS)}")
