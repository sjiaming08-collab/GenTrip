#!/usr/bin/env python3
"""生成 Tier-1 字段格式的 Mock POI fixtures（点评开放接口字段名）。"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "fixtures" / "pois.json"
COUNT = 1000
SEED = 42

DISTRICTS: list[tuple[str, float, float, float, float]] = [
    ("徐汇区", 31.162, 31.215, 121.428, 121.468),
    ("静安区", 31.218, 31.238, 121.442, 121.478),
    ("浦东新区", 31.152, 31.255, 121.478, 121.595),
    ("黄浦区", 31.215, 31.245, 121.468, 121.505),
]

CATEGORIES = [
    "本帮菜",
    "川菜",
    "日料",
    "西餐",
    "咖啡",
    "甜品",
    "酒吧",
    "火锅",
    "烧烤",
    "小吃快餐",
    "文化",
    "博物馆",
    "观光",
    "购物",
    "公园",
]

NAME_PREFIX = [
    "老",
    "小",
    "金",
    "福",
    "盛",
    "悦",
    "尚",
    "拾",
    "漫",
    "云",
    "江南",
    "海上",
    "里弄",
    "梧桐",
]

NAME_SUFFIX = [
    "酒家",
    "小馆",
    "食堂",
    "咖啡",
    "茶室",
    "书坊",
    "工坊",
    "市集",
    "画廊",
    "书店",
    "步道",
    "广场",
    "商场",
    "百货",
]

STREETS = [
    "天平路",
    "衡山路",
    "永康路",
    "武康路",
    "南京西路",
    "淮海中路",
    "巨鹿路",
    "张园路",
    "滨江大道",
    "世纪大道",
    "南京东路",
    "外滩中山东一路",
    "豫园路",
    "新天地兴业路",
    "徐家汇路",
    "龙华路",
    "前滩大道",
]

BRANCH_SUFFIX = ["店", "分店", "旗舰店", "概念店", "体验店", ""]

BUSINESS_HOURS = [
    "09:00-21:00",
    "10:00-22:00",
    "10:30-22:30",
    "11:00-23:00",
    "08:30-20:30",
    "07:00-19:00",
    "12:00-02:00",
    "全天",
]


def _price_for_category(category: str) -> int:
    if category in ("观光", "公园", "文化", "博物馆"):
        return random.choice([0, 0, 0, 20, 30])
    if category in ("咖啡", "甜品", "小吃快餐"):
        return random.randint(25, 80)
    if category in ("酒吧", "西餐", "日料"):
        return random.randint(120, 320)
    if category == "购物":
        return random.choice([0, 0, 80, 150])
    return random.randint(45, 180)


def _star_for_category(category: str) -> float:
    base = {
        "博物馆": 4.6,
        "观光": 4.5,
        "公园": 4.4,
        "咖啡": 4.3,
        "本帮菜": 4.2,
    }.get(category, 4.1)
    return round(min(5.0, max(3.2, random.gauss(base, 0.35))), 1)


def generate_record(index: int) -> dict:
    district, lat_min, lat_max, lng_min, lng_max = random.choice(DISTRICTS)
    category = random.choice(CATEGORIES)
    street = random.choice(STREETS)
    house_no = random.randint(1, 999)

    name = f"{random.choice(NAME_PREFIX)}{random.choice(NAME_SUFFIX)}"
    branch_name = ""
    if random.random() < 0.55:
        branch_name = f"{district.replace('区', '')}{random.choice(BRANCH_SUFFIX)}"

    return {
        "openshopid": f"mock_{index:06d}",
        "openstatus": 0 if random.random() < 0.03 else 1,
        "name": name,
        "branch_name": branch_name,
        "city": "上海",
        "address": f"上海市{district}{street}{house_no}号",
        "latitude": round(random.uniform(lat_min, lat_max), 6),
        "longitude": round(random.uniform(lng_min, lng_max), 6),
        "categories": [category],
        "star": _star_for_category(category),
        "avgprice": _price_for_category(category),
        "business_hour": random.choice(BUSINESS_HOURS),
    }


def main() -> None:
    random.seed(SEED)
    records = [generate_record(i + 1) for i in range(COUNT)]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")
    online = sum(1 for r in records if r["openstatus"] == 1)
    print(f"Wrote {len(records)} records to {OUTPUT} ({online} online)")


if __name__ == "__main__":
    main()
