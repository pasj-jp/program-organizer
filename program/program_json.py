"""Export shared program data using the original PASJ JSON format."""

import json
import re
from datetime import date

from .program_data import HEADERS, iter_program_rows


# 日本語→英語キーのマッピング（ここにない通常列は出力しない）
key_map = {
    "ログインID": "login_id",
    "演題登録番号": "submission_id",
    "参加登録番号": "registration_id",
    "講演番号": "talk_id",
    "セッション": "session",
    "確定発表形式": "confirmed_format",
    "開催日": "date",
    "発表時間": "time",
    "会場": "room",
    "姓": "last_name",
    "名": "first_name",
    "姓(かな)": "last_name_kana",
    "名(かな)": "first_name_kana",
    "姓(英語)": "last_name_en",
    "名(英語)": "first_name_en",
    "名(ミドルネーム)": "middle_name",
    "所属機関名": "affiliation",
    "部署名・学部名": "department",
    "発表形式": "presentation_type",
    "題目": "title_ja",
    "題目（english）": "title_en",
    "要旨": "abstract_ja",
    "発表希望カテゴリー（第１希望）": "category_1",
    "発表希望カテゴリー（第２希望）": "category_2",
    "年会賞への応募応募": "award_entry",
    "賞状の敬称": "honorific",
    "通信欄": "note",
    "著者情報": "author_text_html",
    "著者所属情報": "affiliation_text_html",
    "登録日時": "created_at",
    "更新日時": "updated_at",
}

# 英語キーの連名者フィールド（ここにない連名者列は出力しない）
coauthor_fields = {
    "区分": "role",
    "姓": "last_name",
    "名": "first_name",
    "姓カナ": "last_name_kana",
    "名カナ": "first_name_kana",
    "姓英語": "last_name_en",
    "名英語": "first_name_en",
    "ミドルネーム": "middle_name",
    "所属": "affiliation",
}

COAUTHOR_PATTERN = re.compile(r"連名者\[(\d+)\](.+)")


def cell_to_string(value):
    """CSV を介した場合と同様に、セル値を文字列へそろえる。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def convert_row(row):
    converted = {}
    coauthors = []

    for key, value in row.items():
        if not key:
            continue

        if key == "開催日" and isinstance(value, date):
            value = f"{value.month}月{value.day}日"
        value = cell_to_string(value)
        match = COAUTHOR_PATTERN.fullmatch(key)
        if match:
            index = int(match.group(1))
            field_en = coauthor_fields.get(match.group(2))
            if field_en:
                while len(coauthors) < index:
                    coauthors.append({"index": len(coauthors) + 1})
                coauthors[index - 1][field_en] = value
        elif key in key_map:
            # 未定義の列を無視することで、従来の「余計な列を削除」を行う。
            converted[key_map[key]] = value

    coauthors = [
        coauthor
        for coauthor in coauthors
        if any(value.strip() for key, value in coauthor.items() if key != "index")
    ]
    converted["coauthors"] = coauthors
    return converted


def export_program_json(meeting):
    records = []
    for values in iter_program_rows(meeting):
        # As in the original converter, the leftmost duplicate column wins.
        row = {}
        for header, value in zip(HEADERS, values):
            row.setdefault(header, value)
        records.append(convert_row(row))
    return json.dumps(records, ensure_ascii=False, indent=4)
