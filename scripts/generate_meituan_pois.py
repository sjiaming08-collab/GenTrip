"""Generate ~600 high-diversity POIs in meituan format for backend/fixtures/pois.json."""

import json, random, math
from pathlib import Path

random.seed(42)

# ── Districts with many business areas ──
DISTRICTS = {
    "徐汇区": {
        "areas": [
            ("衡山路/复兴西路", (31.208,121.446), 1800),
            ("徐家汇",           (31.192,121.438), 2800),
            ("田林/漕河泾",       (31.175,121.410), 3000),
            ("安福路/武康路",     (31.210,121.442), 1400),
            ("龙华",            (31.175,121.453), 2500),
            ("上海南站",         (31.155,121.430), 3000),
        ],
    },
    "静安区": {
        "areas": [
            ("静安寺",           (31.224,121.446), 2000),
            ("南京西路",         (31.230,121.457), 2500),
            ("大悦城/不夜城",     (31.245,121.455), 2000),
            ("巨鹿路/富民路",     (31.219,121.450), 1200),
            ("大宁",            (31.275,121.450), 3000),
        ],
    },
    "黄浦区": {
        "areas": [
            ("人民广场",         (31.230,121.473), 2000),
            ("外滩",            (31.240,121.490), 2200),
            ("新天地",           (31.217,121.470), 1500),
            ("老西门/豫园",      (31.220,121.480), 1800),
            ("南京东路",         (31.238,121.480), 2000),
        ],
    },
    "浦东新区": {
        "areas": [
            ("陆家嘴",           (31.236,121.500), 2800),
            ("世纪公园/花木",     (31.210,121.545), 3000),
            ("张江",            (31.210,121.610), 4500),
            ("八佰伴/塘桥",       (31.215,121.520), 2500),
            ("前滩",            (31.155,121.480), 3000),
        ],
    },
}

# ── Categories: (sub_category, min_price, max_price, duration_min, parent_category) ──
# Wider price ranges for more differentiation
DINING = [
    ("本帮江浙菜",   60,350, 75, "美食"),
    ("本帮江浙菜",   40,180, 75, "美食"),   # duplicate for volume with lower tier
    ("川菜/湘菜",    40,200, 60, "美食"),
    ("粤菜/港式",    60,350, 60, "美食"),
    ("日料",        80,500, 75, "美食"),
    ("日料",        30,120, 45, "美食"),     # ramen/izakaya tier
    ("西餐/牛排馆",   80,400, 90, "美食"),
    ("东南亚菜",     50,200, 60, "美食"),
    ("火锅/串串",    60,200, 90, "美食"),
    ("砂锅/煲仔",     30,120, 45, "美食"),
    ("面馆",         15,60,  30, "美食"),
    ("小吃快餐",      15,50,  25, "美食"),
    ("轻食/健康餐",   40,100, 40, "美食"),
    ("云南菜/贵州菜",  35,100, 45, "美食"),
    ("烧烤/烤肉",     50,180, 75, "美食"),
    ("海鲜/蟹宴",    120,600, 90, "美食"),
    ("西北菜/新疆菜",  40,120, 60, "美食"),
    ("东北菜",       35,100, 60, "美食"),
]

CAFE = [
    ("咖啡厅",       20,80,  40, "休闲餐饮"),
    ("精品咖啡",     30,100, 45, "休闲餐饮"),
    ("茶馆/茶室",    40,160, 60, "休闲餐饮"),
    ("甜品/烘焙",    25,80,  35, "休闲餐饮"),
    ("冰淇淋/ gelato",20,55, 20, "休闲餐饮"),
    ("酒吧/清吧",    60,250, 90, "休闲餐饮"),
    ("精酿啤酒吧",   70,200, 75, "休闲餐饮"),
]

SIGHTSEEING = [
    ("博物馆/美术馆",   0,100, 90, "景点"),
    ("公园/绿地",      0,0,   60, "景点"),
    ("城市街区漫步",    0,0,   50, "景点"),
    ("城市地标/观景台", 0,120, 30, "景点"),
    ("滨江步道",       0,0,   60, "景点"),
    ("历史建筑/名人故居", 0,60, 45, "景点"),
    ("教堂/寺庙",      0,0,   30, "景点"),
]

SHOPPING = [
    ("购物中心/百货",   0,0, 120, "购物"),
    ("买手店/集合店",   0,0,  50, "购物"),
    ("书店/文创",      0,50, 60, "购物"),
    ("古着/ vintage",  0,0,  40, "购物"),
]

LEISURE = [
    ("剧场/脱口秀",    80,400, 120, "休闲娱乐"),
    ("Livehouse",    80,250, 120, "休闲娱乐"),
    ("电影院",       40,100, 120, "休闲娱乐"),
    ("密室/剧本杀",   80,200, 120, "休闲娱乐"),
    ("KTV",         60,200, 120, "休闲娱乐"),
]

CULTURE_ART = [
    ("艺术展馆/美术展览", 0,120, 90, "文化艺术"),
    ("画廊/艺术空间",    0,80,  70, "文化艺术"),
    ("文化中心/公共空间", 0,60,  60, "文化艺术"),
    ("手作工坊/陶艺",    80,260, 100, "文化艺术"),
]

LIFE_SERVICE = [
    ("按摩/足疗",       80,260, 90, "按摩足疗"),
    ("中式推拿/理疗",   120,360, 80, "按摩足疗"),
    ("SPA/精油护理",   220,680, 120, "按摩足疗"),
    ("美容美体/皮肤管理", 180,580, 100, "美容美体"),
    ("美甲美睫",       120,360, 80, "美容美体"),
]

SPORTS = [
    ("健身房/团课",      60,180, 90, "体育运动"),
    ("攀岩馆/抱石",      80,180, 120, "体育运动"),
    ("羽毛球馆",         40,120, 120, "体育运动"),
    ("网球场",           60,180, 120, "体育运动"),
    ("游泳馆",           50,160, 90, "体育运动"),
    ("保龄球馆",         60,180, 100, "体育运动"),
    ("室内滑雪/滑冰",    120,380, 120, "体育运动"),
]

GAMING = [
    ("电玩城/街机",      60,180, 90, "电玩游戏"),
    ("电竞馆",           50,160, 120, "电玩游戏"),
    ("桌游馆",           60,160, 120, "电玩游戏"),
    ("VR体验馆",         80,220, 90, "电玩游戏"),
    ("密室/剧本杀",      100,280, 150, "电玩游戏"),
]

FAMILY = [
    ("亲子乐园",         80,240, 120, "亲子游乐"),
    ("儿童运动馆",       100,260, 100, "亲子游乐"),
    ("科学体验馆",       60,180, 90, "亲子游乐"),
]

ALL_CATS = DINING + CAFE + SIGHTSEEING + SHOPPING + LEISURE
EXPANSION_CATEGORIES = CULTURE_ART + LIFE_SERVICE + SPORTS + GAMING + FAMILY + [
    ("奥特莱斯", 0, 0, 150, "商场"),
    ("生活方式商场", 0, 0, 100, "商场"),
]

# ── Rich name pools ──
FOOD_NAMES = [
    ("梧桐里小馆",""),("南丹路砂锅局",""),("永嘉庭私房菜",""),("衡山雅集",""),("天平小厨",""),
    ("襄阳路上的面",""),("富民阁",""),("长乐食堂",""),("安福小馆",""),("武康庭",""),
    ("静安小厨",""),("愚园里",""),("铜仁阁",""),("华亭食府",""),("方浜记",""),
    ("东平路本帮",""),("多伦雅集",""),("丽园楼",""),("局门老店",""),("进贤路小吃",""),
    ("巨鹿路小馆",""),("永福庭",""),("宛平家宴",""),("岳阳楼记",""),("淮海食堂",""),
    ("南昌路面馆",""),("陕南私厨",""),("淡水食集",""),("建业里",""),("皋兰小馆",""),
    ("香山苑",""),("桃江小厨",""),("太原别院",""),("延庆弄堂菜",""),("汾阳阁",""),
    ("新华食坊",""),("瑞金小馆",""),("打浦桥味道",""),("五里桥私房",""),("半淞园食集",""),
    ("老西门厨房",""),("田子坊小馆",""),("陆家浜面馆",""),("中华路排挡",""),("复兴中路食府",""),
    ("世纪汇美食",""),("潍坊食堂",""),("塘桥小馆",""),("花木人家",""),("张江小厨",""),
    # 新增50个
    ("吴江路小吃",""),("云南南路美食",""),("乍浦路面馆",""),("浙江中路排挡",""),("山海关路食堂",""),
    ("茂名北路小馆",""),("石门一路味道",""),("威海路私房",""),("奉贤路食集",""),("南阳路厨房",""),
    ("北京西路食府",""),("新闸路小厨",""),("武定路小馆",""),("康定路食堂",""),("万航渡路私房",""),
    ("镇宁路味道",""),("江苏路食集",""),("华山路小馆",""),("兴国路私厨",""),("泰安路厨房",""),
    ("余庆路食堂",""),("广元路小馆",""),("宜山路食府",""),("桂林路排挡",""),("钦州路面馆",""),
    ("虹桥路美食",""),("番禺路小厨",""),("定西路食堂",""),("武夷路味道",""),("仙霞路食府",""),
    ("黄金城道私房",""),("水城路小馆",""),("芳甸路食堂",""),("锦绣路美食",""),("碧云路私厨",""),
    ("金桥路小馆",""),("博山路面馆",""),("崮山路食堂",""),("羽山路味道",""),("民生路食集",""),
    ("商城路小厨",""),("东昌路厨房",""),("浦电路食堂",""),("蓝村路排挡",""),("东方路食府",""),
    ("临沂路美食",""),("云台路小馆",""),("洪山路面馆",""),("昌里路私房",""),("上南路食堂",""),
]
FOOD_CUISINE_PREFIX = {
    "本帮江浙菜": ["老上海","弄堂","石库门","本帮","沪上"],
    "川菜/湘菜":  ["蜀味","巴适","辣","蓉城","湘聚"],
    "粤菜/港式":  ["港九","粤珍","南国","烧腊","潮"],
    "日料":      ["鮨","酒吞","鸟","一幸","鳗"],
    "西餐/牛排馆": ["BISTRO","牛排","扒房","法式","意"],
    "东南亚菜":   ["南洋","泰","越","蕉叶","咖喱"],
    "火锅/串串":  ["重庆","串","麻辣","涮","锅"],
    "海鲜/蟹宴":  ["蟹","东海","渔","海鲜","舟山"],
    "烧烤/烤肉":  ["烤","炭火","炙","韩式","铁板"],
}

CAFE_NAMES = [
    ("M Stand",""),("Seesaw Coffee",""),("Manner",""),("% Arabica",""),("Peet's",""),
    ("永康咖啡",""),("进贤路COFFEE",""),("巨鹿喫茶",""),("南阳咖啡研习社",""),("思南豆仓",""),
    ("淡水冲煮店",""),("襄阳咖啡馆",""),("陕南手冲",""),("建国咖啡屋",""),("皋兰路CAFE",""),
    ("天平咖啡",""),("高安路珈琲",""),("永嘉路茶馆",""),("武康庭茶室",""),("复兴弄堂茶",""),
    ("Tequila Espresso",""),("Metal Hands",""),("O.P.S.",""),("Gregorius",""),("Rumors",""),
    ("山余咖啡",""),("Onirii",""),("GABEE.",""),("老麦咖啡馆",""),("paras",""),
    ("Beautiful Concept",""),("月球咖啡",""),("珈琲光景",""),("三顿半返航点",""),("DOUBLE WIN",""),
    ("Uncle No Name",""),("Bread etc",""),("Baker&Spice",""),("Al's Diner",""),("Spread the Bagel",""),
]

SIGHT_NAMES = [
    ("复兴公园",""),("新华路历史街区",""),("瑞金宾馆花园",""),("延庆路",""),("桃江路",""),
    ("岳阳路梧桐区",""),("东湖路",""),("汾阳路音乐街区",""),("太原别墅",""),("永嘉庭",""),
    ("上海博物馆",""),("当代艺术馆",""),("龙美术馆",""),("余德耀美术馆",""),("西岸美术馆",""),
    ("外滩观景平台",""),("陆家嘴滨江",""),("徐汇滨江步道",""),("前滩公园",""),("世纪公园",""),
    ("静安公园",""),("复兴岛",""),("苏州河步道",""),("多伦路文化名人街",""),("思南公馆",""),
    ("震旦博物馆",""),("复星艺术中心",""),("浦东美术馆",""),("民生现代美术馆",""),("teamLab",""),
    ("长风公园",""),("桂林公园",""),("漕溪公园",""),("人民公园",""),("襄阳公园",""),
    ("衡山公园",""),("徐家汇天主堂",""),("董家渡天主堂",""),("国际礼拜堂",""),("静安寺",""),("玉佛寺",""),
    ("新场古镇",""),("召稼楼",""),("三林塘",""),("七宝老街",""),
]

SHOP_NAMES = [
    ("iapm环贸",""),("港汇恒隆",""),("兴业太古汇",""),("新天地南里",""),("来福士",""),
    ("芮欧百货",""),("K11",""),("静安嘉里中心",""),("前滩太古里",""),("ifc国金",""),
    ("衡山坊",""),("武康庭市集",""),("安福路买手店",""),("多抓鱼循环商店",""),("茑屋书店",""),
    ("思南书局",""),("香蕉鱼书店",""),("潮流买手店",""),("古着仓库",""),("文创集合店",""),
]

LEISURE_NAMES = [
    ("上海大剧院",""),("上剧场",""),("文化广场",""),("兰心大戏院",""),("美琪大戏院",""),
    ("育音堂",""),("MAO Livehouse",""),("万代南梦宫",""),("ModernSky Lab",""),("VAS",""),
    ("SFC上影",""),("百丽宫影城",""),("MOViE MOViE",""),("大光明电影院",""),("和平影都",""),
    ("屋有岛密室",""),("X先生",""),("纯K",""),("好乐迪",""),("星聚会KTV",""),
]

CULTURE_NAMES = [
    ("西岸艺术空间",""),("衡复文化中心",""),("弄堂画廊",""),("苏州河艺术仓",""),
    ("浦东当代艺术馆",""),("外滩公共艺术中心",""),("武康路陶艺工坊",""),("思南手作实验室",""),
]
SERVICE_NAMES = [
    ("云栖足道",""),("梧桐里推拿馆",""),("静安精油SPA",""),("西岸理疗中心",""),
    ("衡山路皮肤管理",""),("陆家嘴美甲美睫",""),("前滩养生馆",""),("愚园路采耳馆",""),
]
SPORTS_NAMES = [
    ("徐汇抱石馆",""),("静安羽毛球中心",""),("前滩运动公园",""),("陆家嘴游泳馆",""),
    ("西岸网球中心",""),("南京西路健身工场",""),("浦东保龄球馆",""),("张江冰雪空间",""),
]
GAME_NAMES = [
    ("万代游戏中心",""),("前滩电竞空间",""),("静安桌游社",""),("外滩VR体验馆",""),
    ("新天地密室研究所",""),("徐家汇街机厅",""),("张江剧本杀馆",""),
]
FAMILY_NAMES = [
    ("小小探索家儿童乐园",""),("亲子运动星球",""),("浦东科学体验馆",""),
    ("徐汇儿童攀岩馆",""),("静安亲子艺术屋",""),("黄浦自然实验室",""),
]

ALL_NAMES = FOOD_NAMES + CAFE_NAMES + SIGHT_NAMES + SHOP_NAMES + LEISURE_NAMES

# ── Tag pools ──
TAGS = {
    "fine_dining":   ["约会圣地","仪式感","景观位","可预约","包间","黑珍珠"],
    "casual_dining": ["朋友聚餐","性价比","口味稳定","地道","排队","深夜食堂"],
    "quick_dining":  ["平价","快餐","出餐快","一人食","外卖"],
    "cafe":          ["安静","有插座","适合办公","宠物友好","户外座位","手冲","精品豆","下午茶","brunch"],
    "bar":           ["氛围好","特调","happy hour","深夜","小众"],
    "outdoor":       ["免费","户外","适合散步","拍照出片","亲子友好","野餐"],
    "culture":       ["文化","室内","需预约","知识性","导览"],
    "shopping":      ["购物","品牌齐全","地铁直达","有餐饮","停车方便"],
    "entertainment": ["沉浸式","互动","提前购票","适合聚会"],
    "service":       ["预约制","放松减压","私密","服务细致","工作日优惠"],
    "sports":        ["需预约","运动友好","淋浴间","装备租赁","适合朋友"],
    "gaming":        ["沉浸式","多人互动","适合聚会","预约优先","雨天友好"],
    "family":        ["亲子友好","室内","周末热门","互动体验","适合儿童"],
}

def tag_pool(cat_name, price, rating):
    pools = []
    if any(w in cat_name for w in ("本帮江浙菜","粤菜","日料","西餐","海鲜")):
        if rating >= 4.5 and price >= 150: pools.append("fine_dining")
        else: pools.append("casual_dining")
    elif any(w in cat_name for w in ("川菜","火锅","烧烤","串串")):
        pools.append("casual_dining")
    elif any(w in cat_name for w in ("面馆","小吃","快餐","砂锅","云南菜","东北菜","西北菜")):
        pools.append("quick_dining")
    elif any(w in cat_name for w in ("咖啡","精品咖啡")):
        pools.append("cafe")
    elif any(w in cat_name for w in ("茶")):
        pools.append("cafe")
    elif any(w in cat_name for w in ("酒吧","啤酒")):
        pools.append("bar")
    elif any(w in cat_name for w in ("公园","绿地","步道","街区","建筑","教堂")):
        pools.append("outdoor")
    elif any(w in cat_name for w in ("博物馆","美术馆","展馆","画廊","艺术","文化中心","手作")):
        pools.append("culture")
    elif any(w in cat_name for w in ("购物","百货","奥特莱斯","生活方式","买手","古着","书店")):
        pools.append("shopping")
    elif any(w in cat_name for w in ("按摩","足疗","推拿","SPA","美容","美甲")):
        pools.append("service")
    elif any(w in cat_name for w in ("健身","攀岩","羽毛球","网球","游泳","保龄球","滑雪","滑冰")):
        pools.append("sports")
    elif any(w in cat_name for w in ("电玩城","电竞","桌游","VR","密室","剧本杀")):
        pools.append("gaming")
    elif any(w in cat_name for w in ("亲子","儿童","科学体验")):
        pools.append("family")
    elif any(w in cat_name for w in ("剧场","Livehouse","电影院","KTV")):
        pools.append("entertainment")
    tags = set()
    for p in (pools or ["casual_dining"]):
        tags.update(random.sample(TAGS[p], min(3, len(TAGS[p]))))
    return list(tags)


def get_name(cat_name, district, idx):
    """Pick a name appropriate for the category."""
    pool = FOOD_NAMES
    if any(w in cat_name for w in ("咖啡","精品咖啡","茶","甜品","冰淇淋","酒吧","啤酒")):
        pool = CAFE_NAMES
    elif any(w in cat_name for w in ("博物馆","美术馆","公园","绿地","街区","地标","滨江","建筑","教堂")):
        pool = SIGHT_NAMES
    elif any(w in cat_name for w in ("展馆","画廊","艺术","文化中心","手作")):
        pool = CULTURE_NAMES
    elif any(w in cat_name for w in ("购物","百货","奥特莱斯","生活方式","买手","古着","书店","文创")):
        pool = SHOP_NAMES
    elif any(w in cat_name for w in ("按摩","足疗","推拿","SPA","美容","美甲")):
        pool = SERVICE_NAMES
    elif any(w in cat_name for w in ("健身","攀岩","羽毛球","网球","游泳","保龄球","滑雪","滑冰")):
        pool = SPORTS_NAMES
    elif any(w in cat_name for w in ("电玩城","电竞","桌游","VR","密室","剧本杀")):
        pool = GAME_NAMES
    elif any(w in cat_name for w in ("亲子","儿童","科学体验")):
        pool = FAMILY_NAMES
    elif any(w in cat_name for w in ("剧场","Livehouse","电影院","KTV")):
        pool = LEISURE_NAMES

    name, _ = random.choice(pool)

    # Add cuisine prefix for dining (like "蜀味·", "鮨·")
    if pool is FOOD_NAMES and cat_name in FOOD_CUISINE_PREFIX:
        if random.random() < 0.25:
            pfx = random.choice(FOOD_CUISINE_PREFIX[cat_name])
            name = f"{pfx}·{name}"

    return name


def gen_ugc_text(cat_name, rating, price):
    """Generate diverse UGC summaries."""
    templates = {
        "fine": [
            f"环境和菜品都很精致，{'非常适合重要场合' if price > 200 else '性价比意外的可以'}。",
            f"口味稳定，服务在线，{'唯一的缺点就是贵' if price > 250 else '价格还算公道'}。",
            f"回头客很多，{'工作日中午都要排队' if rating > 4.5 else '建议预约'}。",
        ],
        "casual": [
            f"{'味道很正宗，' if rating > 4.3 else '味道中规中矩，'}适合日常和朋友一起来，人均{price}元左右。",
            f"分量实在，上菜也快，{'就是周末人太多' if rating > 4.4 else '整体体验还行'}。",
            f"性价比很高的一家店，{random.choice(['虽然没有特别惊艳的菜','招牌菜值得一试','环境一般但味道好'])}。",
        ],
        "cafe": [
            f"咖啡豆品质不错，{'手冲很有水准' if '精品' in cat_name else '意式稳定出品'}。环境{random.choice(['适合办公','适合聊天','偏安静'])}。",
            f"{'网红打卡地，' if rating > 4.4 else ''}咖啡{random.choice(['颜值在线','味道还OK','偏贵但值得'])}，brunch也不错。",
            f"这家开了好几年了，{'熟客很多' if rating > 4.5 else '主要是周边居民'}，出品稳定。",
        ],
        "sight": [
            f"{random.choice(['周末人很多','工作日去很安静','免费的很良心'])}，{random.choice(['适合拍照','适合散步','适合发呆'])}。",
            f"上海{'经典' if rating > 4.5 else '小众'}景点，{random.choice(['交通方便','离地铁有点远但值得','建议骑车或步行前往'])}。",
        ],
        "shop": [
            f"{'人气很旺，' if rating > 4.4 else ''}{random.choice(['品牌齐全','环境不错','逛的人不多很舒服'])}。",
        ],
        "entertainment": [
            f"{random.choice(['效果很震撼','性价比不错','适合朋友一起去'])}，{random.choice(['建议提前买票','现场体验更好','座位建议选中后排'])}。",
        ],
    }

    if any(w in cat_name for w in ("本帮江浙菜","粤菜","日料","西餐","海鲜")):
        return random.choice(templates["fine"])
    elif any(w in cat_name for w in ("川菜","火锅","烧烤","面馆","小吃","砂锅","云南","东北","西北")):
        return random.choice(templates["casual"])
    elif any(w in cat_name for w in ("咖啡","精品咖啡","茶","甜品","酒吧","啤酒")):
        return random.choice(templates["cafe"])
    elif any(w in cat_name for w in ("公园","博物馆","美术馆","街区","地标","滨江","建筑","教堂")):
        return random.choice(templates["sight"])
    elif any(w in cat_name for w in ("购物","百货","买手","古着","书店")):
        return random.choice(templates["shop"])
    else:
        return random.choice(templates["entertainment"])


def gen_opening(cat_name):
    """Diverse opening hours."""
    if any(w in cat_name for w in ("酒吧","啤酒","Livehouse")):
        return random.choice([
            [{"days":"Mon-Sun","open":"18:00","close":"02:00"}],
            [{"days":"Tue-Sun","open":"19:00","close":"03:00"}],
            [{"days":"Wed-Sun","open":"18:00","close":"01:00"}],
        ])
    elif any(w in cat_name for w in ("公园","绿地","步道","街区")):
        return [{"days":"Mon-Sun","open":"05:00","close":"22:00"}]
    elif any(w in cat_name for w in ("博物馆","美术馆")):
        return [{"days":"Tue-Sun","open":"10:00","close":"18:00"}]
    elif any(w in cat_name for w in ("购物","百货")):
        return [{"days":"Mon-Sun","open":"10:00","close":"22:00"}]
    elif any(w in cat_name for w in ("剧场","电影院","KTV")):
        return [{"days":"Mon-Sun","open":"10:00","close":"23:00"}]
    elif any(w in cat_name for w in ("面馆","小吃","快餐")):
        return [{"days":"Mon-Sun","open":"06:30","close":"21:00"}]
    elif any(w in cat_name for w in ("咖啡","甜品","冰淇淋")):
        return [{"days":"Mon-Sun","open":"08:00","close":"22:00"}]
    else:
        return random.choice([
            [{"days":"Mon-Sun","open":"10:30","close":"14:00"},{"days":"Mon-Sun","open":"17:00","close":"21:30"}],
            [{"days":"Mon-Sun","open":"11:00","close":"22:00"}],
            [{"days":"Mon-Sun","open":"10:00","close":"14:30"},{"days":"Mon-Sun","open":"16:30","close":"22:00"}],
        ])


def gen_queue(cat_name, rating, area):
    """Realistic queue times — varies by area popularity."""
    is_hot_area = area in ("衡山路/复兴西路","静安寺","外滩","新天地","陆家嘴","南京西路","安福路/武康路")
    hot_bonus = 1.5 if is_hot_area else 1.0

    if rating > 4.5 and any(w in cat_name for w in ("本帮","火锅","日料","川菜","海鲜")):
        return {"weekday": int(random.randint(10,30)*hot_bonus), "weekend": int(random.randint(30,60)*hot_bonus), "rainy_day": int(random.randint(3,15))}
    elif "咖啡" in cat_name or "甜品" in cat_name:
        return {"weekday": int(random.randint(2,10)*hot_bonus), "weekend": int(random.randint(8,25)*hot_bonus), "rainy_day": int(random.randint(1,8))}
    elif rating > 4.3:
        return {"weekday": int(random.randint(5,15)*hot_bonus), "weekend": int(random.randint(10,30)*hot_bonus), "rainy_day": int(random.randint(2,10))}
    else:
        return {"weekday": random.randint(0,5), "weekend": random.randint(3,12), "rainy_day": random.randint(0,5)}


def create_poi(poi_id, dist_name, area_name, area_center, cat_def, idx):
    cat_name, min_p, max_p, dur, parent = cat_def
    lat, lng = jitter(*area_center)

    # Rating: normal-ish distribution centered on 4.2, spread 3.2-5.0
    rating = round(max(3.2, min(5.0, random.gauss(4.25, 0.45))), 1)
    # For sightseeing, bias higher
    if any(w in cat_name for w in ("公园","博物馆","街区","滨江","建筑","地标","教堂")):
        rating = round(max(3.5, min(5.0, random.gauss(4.4, 0.35))), 1)

    price = random.randint(min_p, max_p) if max_p > 0 else 0
    # Low-rated expensive places are rare — nudge price down for low ratings
    if rating < 3.8 and price > 150:
        price = int(price * 0.6)

    taste = round(min(5.0, max(2.0, rating + random.gauss(0, 0.25))), 1)
    env = round(min(5.0, max(2.0, rating + random.gauss(-0.1, 0.3))), 1)
    svc = round(min(5.0, max(2.0, rating + random.gauss(-0.15, 0.25))), 1)

    name = get_name(cat_name, dist_name, idx)
    tags = tag_pool(cat_name, price, rating)
    if rating < 3.8:
        tags = [t for t in tags if t not in ("口碑好","回头客多")] + (["价格低"] if price < 40 else [])

    # Signature items for dining
    sig_items = []
    if "本帮" in cat_name:
        sig_items = random.sample(["葱油鸡","响油鳝丝","桂花酒酿圆子","油爆虾","红烧肉","蟹粉豆腐","糖醋排骨","糟钵头"], 3)
    elif "川菜" in cat_name:
        sig_items = random.sample(["水煮鱼","回锅肉","麻婆豆腐","辣子鸡","口水鸡","夫妻肺片"], 3)
    elif "日料" in cat_name:
        sig_items = random.sample(["刺身拼盘","鳗鱼饭","天妇罗","寿司","烤牛舌","炸猪排"], 3) if price > 80 else random.sample(["拉面","丼饭","章鱼烧","炸鸡"], 2)

    review_count = int(10 ** random.uniform(1.5, 3.8))  # 30 ~ 6000
    monthly_sales = int(review_count * random.uniform(0.5, 3.0))

    return {
        "poi_id": poi_id,
        "data_tier": "synthetic_generated",
        "name": name,
        "brand_type": random.choice(["independent","independent","local_chain","chain"]),
        "category": parent,
        "sub_category": cat_name,
        "district": dist_name,
        "business_area": area_name,
        "address": f"上海市{dist_name}{area_name}附近",
        "location": {"lat": lat, "lng": lng},
        "avg_price": price,
        "rating": rating,
        "taste_score": taste,
        "environment_score": env,
        "service_score": svc,
        "review_count": review_count,
        "monthly_sales": monthly_sales,
        "popularity": max(20, min(99, int(50 + rating * 10 + random.randint(-15,15)))),
        "queue_minutes": gen_queue(cat_name, rating, area_name),
        "opening_hours": gen_opening(cat_name),
        "recommended_duration_min": dur + random.randint(-10,10),
        "reservation": random.choice(["not_required","not_required","not_required","recommended","required"]),
        "parking": random.choice(["street","mall_nearby","street","limited","none","none"]),
        "tags": tags,
        "signature_items": sig_items,
        "deals": [],
        "ugc_summary": gen_ugc_text(cat_name, rating, price),
        "review_snippets": [
            {"sentiment": "positive", "text": random.choice([
                f"确实不错，{'环境好味道也好' if rating>4.3 else '对得起这个价格'}。",
                f"已经是第{random.randint(2,5)}次来了，出品稳定。",
                f"朋友推荐的，{'没有失望' if rating>4.0 else '还行吧'}。",
                f"地理位置很方便，{'顺便逛逛挺好的' if '步道' not in cat_name and '街区' not in cat_name else '走走很舒服'}。",
            ])},
            {"sentiment": random.choice(["positive","mixed","mixed"]), "text": random.choice([
                f"{'排队太久了，' if rating>4.5 else ''}{'建议错峰去' if rating>4.5 else '周末人比较多'}。",
                f"味道可以但{'偏贵' if price>120 else '量有点少'}。",
                f"装修{'很用心' if env>4.3 else '中规中矩'}，服务{'很好' if svc>4.3 else '一般'}。",
                f"{'招牌很稳' if rating>4.3 else '中规中矩吧'}，{random.choice(['会再来','不一定再来','看情况'])}。",
            ])},
        ],
        "constraints": {
            "dietary": random.sample(["contains_meat","contains_seafood","contains_dairy","vegan_optional"], 2),
            "scene_fit": random.sample(["family","friends","date","solo","business"], random.randint(1,3)),
            "noise_level": random.choice(["low","medium_low","medium","medium_high","high"]),
            "outdoor_seating": random.choice([True, False, False]),
            "pet_friendly": random.choice([True, False, False, False]),
        },
    }


def jitter(lat, lng, max_m=0.004):
    d = max_m
    lat2 = lat + random.uniform(-d, d)
    lng2 = lng + random.uniform(-d, d)
    return round(max(31.12, min(31.35, lat2)), 6), round(max(121.38, min(121.65, lng2)), 6)


def main():
    out_path = Path(__file__).resolve().parents[1] / "backend" / "fixtures" / "pois.json"
    data_dir = Path(__file__).resolve().parents[1] / "data"

    all_pois = []
    counter = 1

    # Per-district generation with target distribution
    for dist_name, dist_info in DISTRICTS.items():
        target = {"徐汇区":280, "静安区":260, "黄浦区":260, "浦东新区":240}[dist_name]
        for i in range(target):
            area_name, area_center, _ = random.choice(dist_info["areas"])
            # Weighted category selection
            r = random.random()
            if r < 0.42:       pool = DINING
            elif r < 0.62:     pool = CAFE
            elif r < 0.80:     pool = SIGHTSEEING
            elif r < 0.92:     pool = SHOPPING
            else:              pool = LEISURE
            cat_def = random.choice(pool)

            prefix = {"徐汇区":"xh","静安区":"ja","黄浦区":"hp","浦东新区":"pd"}[dist_name]
            tag = cat_def[0].split("/")[0]
            poi_id = f"sh_{prefix}_{tag}_{counter:04d}"
            poi = create_poi(poi_id, dist_name, area_name, area_center, cat_def, counter)
            all_pois.append(poi)
            counter += 1

    # Add an independent category-expansion tranche without perturbing the
    # established synthetic baseline used by Golden Set route tests.
    for dist_name, dist_info in DISTRICTS.items():
        prefix = {"徐汇区":"xh","静安区":"ja","黄浦区":"hp","浦东新区":"pd"}[dist_name]
        for index, cat_def in enumerate(EXPANSION_CATEGORIES * 2):
            area_name, area_center, _ = dist_info["areas"][index % len(dist_info["areas"])]
            tag = cat_def[0].split("/")[0]
            poi_id = f"sh_{prefix}_{tag}_{counter:04d}"
            all_pois.append(create_poi(poi_id, dist_name, area_name, area_center, cat_def, counter))
            counter += 1

    # Prepend the 16 hand-crafted originals
    meituan_path = data_dir / "poi_seed_meituan_style.json"
    if meituan_path.exists():
        with meituan_path.open(encoding="utf-8") as f:
            original = json.load(f)
        orig_pois = original.get("pois", [])
        for poi in orig_pois:
            poi.setdefault("data_tier", "curated_seed")
        orig_ids = {p["poi_id"] for p in orig_pois}
        all_pois = orig_pois + [p for p in all_pois if p["poi_id"] not in orig_ids]

    output = {
        "schema_version": "poi_seed.v1",
        "city": "上海",
        "data_policy": {"source":"synthetic","note":"16 hand-crafted + ~600 auto-generated POIs in meituan format with high diversity."},
        "generated_for": ["POI retrieval","route optimization","replan demos"],
        "pois": all_pois,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── Stats ──
    print(f"Generated {len(all_pois)} POIs -> {out_path}")
    districts, cats, prices = {}, {}, []
    for p in all_pois:
        d = p["district"]; districts[d] = districts.get(d,0)+1
        c = p.get("sub_category","?"); cats[c] = cats.get(c,0)+1
        prices.append(p["avg_price"])
    print(f"Districts: {districts}")
    print(f"Categories: {len(cats)} types")
    for c,n in sorted(cats.items(), key=lambda x:-x[1]):
        print(f"  {c}: {n}")
    print(f"Price range: {min(prices)} - {max(prices)}, avg: {sum(prices)//len(prices)}")
    ratings = [p["rating"] for p in all_pois]
    print(f"Rating range: {min(ratings)} - {max(ratings)}, avg: {sum(ratings)/len(ratings):.2f}")


if __name__ == "__main__":
    main()
