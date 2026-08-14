"""開発・デモ用のダミーデータ投入スクリプト

    python -m app.seed            # 未投入なら投入、投入済みなら何もしない
    python -m app.seed --force    # 既存データを全削除してから再投入（開発用）

⚠ 実在の患者データは絶対に使用しないこと。ここにあるのはすべて架空の人物・架空の経過。
"""
import asyncio
import random
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import (
    Admission,
    AdmissionAssessment,
    Nurse,
    NursingNote,
    Patient,
)

rng = random.Random(20260811)  # 再現性のため固定シード

WARD_3F = "3F東病棟"
WARD_4F = "4F西病棟"

NURSES = [
    ("N001", "山田 花子", "ヤマダ ハナコ", WARD_3F, "nurse"),
    ("N002", "佐藤 美咲", "サトウ ミサキ", WARD_3F, "nurse"),
    ("N003", "高橋 健一", "タカハシ ケンイチ", WARD_4F, "nurse"),
    ("A001", "管理 太郎", "カンリ タロウ", "管理部", "admin"),
]

# ---------------------------------------------------------------------------
# 患者シナリオ（架空）
# ---------------------------------------------------------------------------
SCENARIOS = [
    {
        "patient_no": "P00123",
        "name": "田中 太郎",
        "name_kana": "タナカ タロウ",
        "birth_date": date(1954, 3, 12),
        "sex": "男性",
        "ward": WARD_3F,
        "room": "305",
        "days": 16,
        "diagnosis": "右大腿骨頸部骨折　人工骨頭置換術後",
        "doctor": "整形外科　大西 医師",
        "assessment": {
            "allergies": ["ペニシリン"],
            "chronic_diseases": ["高血圧症"],
            "diet_restrictions": "特になし（常食・塩分6g/日）",
            "past_history": "60歳時に高血圧を指摘され内服加療中。喫煙歴なし。",
            "present_illness": "自宅の玄関先で転倒し右股関節痛のため救急搬送。"
            "右大腿骨頸部骨折と診断され、入院翌日に人工骨頭置換術を施行。",
            "adl": {"移動": "歩行器使用", "食事": "自立", "排泄": "見守り", "入浴": "一部介助"},
        },
        "vitals_base": {"bt": 36.7, "sbp": 130, "dbp": 78, "hr": 72, "spo2": 97, "rr": 16},
        "subjective": [
            "「傷の痛みは昨日より楽になった」と話される。",
            "「リハビリは疲れるが、歩けるようになりたい」と前向きな発言あり。",
            "「夜中に何度かトイレに起きた」との訴えあり。",
            "「杖でも歩けるようになったら家に帰りたい」と希望を話される。",
            "疼痛スケール NRS 3。「歩き始めが一番つらい」とのこと。",
        ],
        "objective": [
            "創部の発赤・腫脹なし、浸出液少量。ガーゼ交換施行。",
            "歩行器歩行にて病棟内2周実施、ふらつきなし。",
            "リハビリ室にて理学療法士による歩行訓練を40分実施。",
            "食事全量摂取。水分摂取量 1,200mL/日。",
            "排便あり（普通便）。腹部平坦・軟、腸蠕動音良好。",
            "夜間はセンサーマット使用中。離床センサーの作動なし。",
            "下肢の腫脹・熱感なし。ホーマンズ徴候陰性。",
        ],
        "assessment_text": [
            "疼痛は指示の鎮痛剤でコントロールできており、離床は順調に進んでいる。",
            "術後の経過は良好で、感染徴候は認めない。",
            "夜間頻尿によるふらつきがあり、転倒リスクは残存している。",
            "ADL は拡大傾向にあり、自宅退院に向けた準備を進められる段階。",
        ],
        "plan_text": [
            "疼痛時は指示のロキソプロフェンで対応。歩行訓練は明日も継続。",
            "夜間はセンサーマットの使用を継続し、トイレ移動時は必ず付き添う。",
            "創部の状態を毎日観察し、発赤・熱感があれば医師へ報告する。",
            "退院に向けて家屋状況を家族に確認し、MSW と情報共有する。",
        ],
        "free_input": [
            "痛み和らいだと。創部きれい。歩行器で2周OK。夜トイレ2回",
            "リハ40分。食事全量。排便あり。ふらつきなし",
            "NRS3。歩き始めつらいと。創部浸出液少量。ガーゼ交換",
        ],
    },
    {
        "patient_no": "P00124",
        "name": "鈴木 花",
        "name_kana": "スズキ ハナ",
        "birth_date": date(1938, 11, 2),
        "sex": "女性",
        "ward": WARD_3F,
        "room": "306",
        "days": 12,
        "diagnosis": "誤嚥性肺炎",
        "doctor": "呼吸器内科　森本 医師",
        "assessment": {
            "allergies": [],
            "chronic_diseases": ["アルツハイマー型認知症", "高血圧症"],
            "diet_restrictions": "嚥下調整食（コード3）・とろみ付き（中間のとろみ）",
            "past_history": "5年前よりアルツハイマー型認知症で通院中。3年前に肺炎で入院歴あり。",
            "present_illness": "数日前より発熱・湿性咳嗽が出現。食事中のむせ込みが増えており、"
            "誤嚥性肺炎の診断で入院。抗菌薬点滴投与を開始。",
            "adl": {"移動": "車椅子", "食事": "一部介助", "排泄": "全介助", "入浴": "全介助"},
        },
        "vitals_base": {"bt": 37.2, "sbp": 118, "dbp": 68, "hr": 84, "spo2": 95, "rr": 20},
        "subjective": [
            "「痰が出しにくい」と話される。",
            "発語は少ないが、問いかけにはうなずきで応答される。",
            "「ごはんはおいしい」と笑顔で話される。",
            "咳嗽時に「胸が苦しい」との訴えあり。",
        ],
        "objective": [
            "湿性咳嗽あり。白色痰を少量自己喀出。",
            "呼吸音は右下肺野で軽度の副雑音を聴取。",
            "嚥下調整食を7〜8割摂取。むせ込み1回あり、その後は問題なし。",
            "食事時は座位を90度に保持し、食後30分は座位を維持。",
            "口腔ケアを毎食後に実施。口腔内の乾燥は改善傾向。",
            "抗菌薬点滴を指示どおり投与。刺入部の発赤なし。",
        ],
        "assessment_text": [
            "解熱傾向にあり、抗菌薬の効果が得られていると考えられる。",
            "むせ込みは残存しており、誤嚥のリスクは依然として高い。",
            "食事摂取量は安定してきているが、脱水傾向に注意が必要。",
            "認知機能の低下があり、安静度の理解が得られにくい。",
        ],
        "plan_text": [
            "食事時の姿勢保持と食後30分の座位維持を継続する。",
            "口腔ケアを毎食後に実施し、誤嚥性肺炎の再発を予防する。",
            "SpO2 の変動と痰の性状を継続して観察する。",
            "言語聴覚士と連携し、嚥下機能の再評価を依頼する。",
        ],
        "free_input": [
            "37.2度。湿性咳嗽あり白色痰少量。食事8割、むせ1回。口腔ケア毎食後",
            "解熱傾向。SpO2 96%。嚥下食7割。座位保持30分実施",
            "痰出しにくいと訴え。右下肺で副雑音。点滴刺入部異常なし",
        ],
    },
    {
        "patient_no": "P00125",
        "name": "伊藤 健二",
        "name_kana": "イトウ ケンジ",
        "birth_date": date(1967, 6, 25),
        "sex": "男性",
        "ward": WARD_3F,
        "room": "302",
        "days": 9,
        "diagnosis": "2型糖尿病　血糖コントロール目的",
        "doctor": "内分泌内科　久保 医師",
        "assessment": {
            "allergies": ["そば"],
            "chronic_diseases": ["2型糖尿病", "脂質異常症"],
            "diet_restrictions": "糖尿病食 1,600kcal/日・塩分6g/日",
            "past_history": "45歳時に2型糖尿病を指摘。内服加療中も自己中断歴あり。",
            "present_illness": "健診で HbA1c 10.2% を指摘され、教育入院となる。"
            "インスリン導入と食事・運動療法の指導を目的に入院。",
            "adl": {"移動": "自立", "食事": "自立", "排泄": "自立", "入浴": "自立"},
        },
        "vitals_base": {"bt": 36.5, "sbp": 138, "dbp": 84, "hr": 76, "spo2": 98, "rr": 16},
        "subjective": [
            "「注射は思ったより痛くない」と話される。",
            "「仕事が忙しくて食事の時間が不規則だった」と振り返る発言あり。",
            "「家でも続けられるか不安」と表情を曇らせる。",
            "低血糖症状の自覚はなく、「特に変わりない」とのこと。",
        ],
        "objective": [
            "血糖自己測定を1日4回実施。手技は自立してきている。",
            "インスリン自己注射の手技を看護師の見守りのもとで実施。",
            "糖尿病食を全量摂取。間食の希望なし。",
            "病棟内の歩行運動を食後に20分実施。",
            "足病変の観察を実施。皮膚の亀裂・胼胝なし。",
        ],
        "assessment_text": [
            "血糖値は緩やかに低下しており、インスリン量は適切と考えられる。",
            "自己注射の手技は習得できつつあるが、退院後の継続に不安を抱えている。",
            "食事療法への理解は進んでいるが、外食時の対応が課題。",
            "低血糖の兆候は認めない。",
        ],
        "plan_text": [
            "自己注射・自己測定の手技を毎回確認し、自立を目指す。",
            "管理栄養士による外食時の食事指導を調整する。",
            "低血糖症状と対処方法について繰り返し説明する。",
            "退院後の生活を想定した1日のスケジュールを一緒に作成する。",
        ],
        "free_input": [
            "血糖自己測定4回、手技ほぼ自立。インスリン見守りで実施。食後歩行20分",
            "注射痛くないと。食事全量。低血糖症状なし。足の観察異常なし",
            "退院後続けられるか不安と発言。栄養指導の調整必要",
        ],
    },
    {
        "patient_no": "P00126",
        "name": "渡辺 里美",
        "name_kana": "ワタナベ サトミ",
        "birth_date": date(1979, 1, 18),
        "sex": "女性",
        "ward": WARD_3F,
        "room": "303",
        "days": 6,
        "diagnosis": "急性胆嚢炎　腹腔鏡下胆嚢摘出術後",
        "doctor": "消化器外科　林 医師",
        "assessment": {
            "allergies": [],
            "chronic_diseases": [],
            "diet_restrictions": "術後 脂質制限食から段階的に常食へ",
            "past_history": "特記すべき既往なし。",
            "present_illness": "右季肋部痛と発熱で受診し、急性胆嚢炎と診断。"
            "入院当日に腹腔鏡下胆嚢摘出術を施行。",
            "adl": {"移動": "自立", "食事": "自立", "排泄": "自立", "入浴": "シャワー可"},
        },
        "vitals_base": {"bt": 36.9, "sbp": 112, "dbp": 70, "hr": 78, "spo2": 98, "rr": 16},
        "subjective": [
            "「お腹の張りが少し楽になった」と話される。",
            "「早く仕事に戻りたい」と話される。",
            "創部痛について「動くときだけ痛む」とのこと。NRS 2。",
        ],
        "objective": [
            "創部4か所、発赤・浸出液なし。ドレーン抜去部も乾燥している。",
            "腹部平坦・軟、腸蠕動音良好。排ガスあり。",
            "食事は5分粥を全量摂取。悪心・嘔吐なし。",
            "病棟内歩行自立。ふらつきなし。",
        ],
        "assessment_text": [
            "術後経過は良好で、感染徴候や胆汁漏を疑う所見は認めない。",
            "疼痛は軽度で、日常生活動作に支障はない。",
            "食事は段階的に進められており、消化器症状も出現していない。",
        ],
        "plan_text": [
            "創部の観察を継続し、発赤・浸出液があれば医師へ報告する。",
            "食事形態を段階的に上げ、消化器症状の有無を観察する。",
            "退院指導（創部管理・食事・活動）を明日実施する。",
        ],
        "free_input": [
            "創部4か所異常なし。腹部軟、排ガスあり。5分粥全量。歩行自立",
            "NRS2、動くときだけ痛むと。悪心なし。シャワー浴実施",
        ],
    },
    {
        "patient_no": "P00201",
        "name": "中村 三郎",
        "name_kana": "ナカムラ サブロウ",
        "birth_date": date(1946, 9, 8),
        "sex": "男性",
        "ward": WARD_4F,
        "room": "412",
        "days": 14,
        "diagnosis": "慢性心不全　急性増悪",
        "doctor": "循環器内科　岡田 医師",
        "assessment": {
            "allergies": [],
            "chronic_diseases": ["慢性心不全", "心房細動", "慢性腎臓病"],
            "diet_restrictions": "心臓食　塩分6g/日・水分制限1,200mL/日",
            "past_history": "10年前に心筋梗塞。以後、慢性心不全で通院加療中。",
            "present_illness": "1週間前より労作時呼吸困難と下腿浮腫が増悪し入院。"
            "利尿薬の点滴投与を開始。",
            "adl": {"移動": "自立（心負荷に注意）", "食事": "自立", "排泄": "自立", "入浴": "見守り"},
        },
        "vitals_base": {"bt": 36.4, "sbp": 108, "dbp": 62, "hr": 88, "spo2": 95, "rr": 18},
        "objective": [
            "体重測定 毎朝実施。前日比 -0.4kg。",
            "下腿浮腫は軽減傾向。圧痕は残るが深さは浅くなっている。",
            "尿量 1,650mL/日。水分出納はマイナスバランス。",
            "夜間の起座呼吸なし。ベッドを30度挙上して就寝。",
            "心臓食を全量摂取。塩分制限について本人の理解は良好。",
        ],
        "subjective": [
            "「息切れは入院したときよりずっと楽になった」と話される。",
            "「足のむくみが取れてきた」と自覚あり。",
            "「水分制限がつらい」との訴えあり。",
            "「家では体重を毎日測っていなかった」と振り返る。",
        ],
        "assessment_text": [
            "利尿薬の効果が得られ、うっ血症状は改善傾向にある。",
            "水分制限へのストレスがあり、セルフケア継続への支援が必要。",
            "体重・尿量の推移は安定してきているが、腎機能への影響に注意を要する。",
        ],
        "plan_text": [
            "毎朝の体重測定と水分出納の記録を継続する。",
            "水分制限の目的を再度説明し、氷片の使用など苦痛緩和を提案する。",
            "退院に向けて、自宅での体重・血圧の自己管理方法を指導する。",
        ],
        "free_input": [
            "体重前日比-0.4kg。浮腫軽減。尿量1650。息切れ楽になったと",
            "水分制限つらいと訴え。起座呼吸なし。心臓食全量",
        ],
    },
    {
        "patient_no": "P00202",
        "name": "小林 陽子",
        "name_kana": "コバヤシ ヨウコ",
        "birth_date": date(1958, 4, 21),
        "sex": "女性",
        "ward": WARD_4F,
        "room": "415",
        "days": 21,
        "diagnosis": "脳梗塞（左中大脳動脈領域）　回復期リハビリテーション",
        "doctor": "脳神経内科　三宅 医師",
        "assessment": {
            "allergies": ["ヨード造影剤"],
            "chronic_diseases": ["高血圧症", "脂質異常症"],
            "diet_restrictions": "嚥下調整食（コード4）・塩分6g/日",
            "past_history": "50歳より高血圧で内服加療中。",
            "present_illness": "右片麻痺と失語で救急搬送。左中大脳動脈領域の脳梗塞と診断。"
            "急性期治療後、回復期リハビリテーション目的で当病棟へ転棟。",
            "adl": {"移動": "車椅子（移乗一部介助）", "食事": "自助具使用で自立",
                    "排泄": "一部介助", "入浴": "一部介助"},
        },
        "vitals_base": {"bt": 36.6, "sbp": 132, "dbp": 76, "hr": 70, "spo2": 98, "rr": 16},
        "subjective": [
            "発語はゆっくりだが、単語での意思表示は可能。「だいじょうぶ」と話される。",
            "「リハビリ、がんばる」と意欲的な発言あり。",
            "表情は穏やかで、家族の面会時には笑顔が見られる。",
            "疲労感を訴え、午後のリハビリを一部休息とする。",
        ],
        "objective": [
            "右上下肢の麻痺は BRS 上肢III・下肢IV。前日から変化なし。",
            "理学療法・作業療法・言語療法をそれぞれ40分実施。",
            "車椅子への移乗は手すり使用で一部介助にて実施。",
            "食事は自助具を使用し、自力で8割摂取。むせ込みなし。",
            "排泄はトイレ誘導にて実施。日中の失禁なし。",
        ],
        "assessment_text": [
            "麻痺の程度に大きな変化はないが、移乗動作の安定性は向上している。",
            "言語機能は緩やかに改善しており、意思疎通が取りやすくなっている。",
            "リハビリへの意欲は高いが、疲労の蓄積に注意が必要。",
            "自宅退院に向けて、家族への介助方法の指導が必要な段階。",
        ],
        "plan_text": [
            "移乗時は必ず看護師が付き添い、転倒を予防する。",
            "疲労の程度を観察し、リハビリの負荷をセラピストと調整する。",
            "家族へ移乗介助の方法を指導する機会を設ける。",
            "日中のトイレ誘導を継続し、排泄の自立を目指す。",
        ],
        "free_input": [
            "BRS上肢III下肢IV変化なし。PT/OT/ST各40分。移乗一部介助。食事8割",
            "リハビリがんばると発言。日中失禁なし。疲労感あり午後休息",
        ],
    },
    {
        # 退院済みの患者。担当一覧には出てこないが、患者マスタ検索では見つかる。
        # 退院サマリー生成（M4）のデモ用データも兼ねる。
        "patient_no": "P00118",
        "name": "松本 久美",
        "name_kana": "マツモト クミ",
        "birth_date": date(1962, 7, 30),
        "sex": "女性",
        "ward": WARD_3F,
        "room": "301",
        "days": 30,
        "discharged_after": 9,  # 入院 9 日目に退院
        "diagnosis": "急性虫垂炎　腹腔鏡下虫垂切除術後",
        "doctor": "消化器外科　林 医師",
        "assessment": {
            "allergies": [],
            "chronic_diseases": ["脂質異常症"],
            "diet_restrictions": "術後 流動食から段階的に常食へ",
            "past_history": "特記すべき既往なし。",
            "present_illness": "右下腹部痛と発熱で受診し、急性虫垂炎と診断。"
            "入院当日に腹腔鏡下虫垂切除術を施行。",
            "adl": {"移動": "自立", "食事": "自立", "排泄": "自立", "入浴": "シャワー可"},
        },
        "vitals_base": {"bt": 37.0, "sbp": 116, "dbp": 72, "hr": 80, "spo2": 98, "rr": 16},
        "subjective": [
            "「お腹の痛みはほとんどなくなった」と話される。",
            "「早く子どもの世話に戻りたい」と話される。",
            "創部痛について「押すと少し痛む程度」とのこと。NRS 1。",
        ],
        "objective": [
            "創部3か所、発赤・浸出液なし。乾燥している。",
            "腹部平坦・軟、腸蠕動音良好。排ガス・排便あり。",
            "食事は常食を全量摂取。悪心・嘔吐なし。",
            "病棟内歩行自立。ふらつきなし。",
            "解熱しており、術後の発熱は認めない。",
        ],
        "assessment_text": [
            "術後経過は良好で、感染徴候は認めない。",
            "疼痛は軽度で、日常生活動作に支障はない。",
            "食事も常食まで進んでおり、退院可能な状態と考えられる。",
        ],
        "plan_text": [
            "創部の観察を継続し、異常があれば医師へ報告する。",
            "退院指導（創部管理・活動制限・受診の目安）を実施する。",
            "退院後の外来受診日を確認し、本人へ説明する。",
        ],
        "free_input": [
            "創部3か所異常なし。腹部軟、排ガス排便あり。常食全量。歩行自立",
            "NRS1。解熱している。悪心なし。退院指導実施",
        ],
    },
]

# 患者マスタには登録されているが、入院歴が一度もない患者。
# 「入院していない患者は担当一覧に出てこない」ことの確認と、
# 新規入院登録のデモに使う。
MASTER_ONLY_PATIENTS = [
    {
        "patient_no": "P00301",
        "name": "山口 一郎",
        "name_kana": "ヤマグチ イチロウ",
        "birth_date": date(1951, 2, 14),
        "sex": "男性",
    },
    {
        "patient_no": "P00302",
        "name": "森 さくら",
        "name_kana": "モリ サクラ",
        "birth_date": date(1988, 12, 3),
        "sex": "女性",
    },
]


def _jitter(base: float, spread: float, digits: int = 0) -> float:
    v = base + rng.uniform(-spread, spread)
    return round(v, digits) if digits else round(v)


def _make_vitals(base: dict, day_index: int, total_days: int) -> dict:
    """回復に伴って少しずつ改善する方向にゆらぎを持たせる"""
    progress = day_index / max(total_days - 1, 1)  # 0.0 -> 1.0
    return {
        "bt": round(_jitter(base["bt"] - 0.4 * progress, 0.25, 1), 1),
        "bp": f"{int(_jitter(base['sbp'], 8))}/{int(_jitter(base['dbp'], 5))}",
        "hr": int(_jitter(base["hr"] - 4 * progress, 5)),
        "spo2": min(99, int(_jitter(base["spo2"] + 2 * progress, 1))),
        "rr": int(_jitter(base["rr"] - 1 * progress, 1)),
    }


def _build_soap(sc: dict, vitals: dict, day_index: int, total_days: int) -> str:
    subj = rng.choice(sc["subjective"])
    objs = rng.sample(sc["objective"], k=min(3, len(sc["objective"])))
    assess = rng.choice(sc["assessment_text"])
    plan = rng.choice(sc["plan_text"])

    vital_line = (
        f"体温{vitals['bt']}℃、血圧{vitals['bp']}mmHg、脈拍{vitals['hr']}回/分、"
        f"SpO2 {vitals['spo2']}%（room air）、呼吸数{vitals['rr']}回/分。"
    )
    obj_lines = "\n　　".join([vital_line] + objs)
    return (
        f"S）{subj}\n"
        f"O）{obj_lines}\n"
        f"A）{assess}\n"
        f"P）{plan}"
    )


async def _clear_all(session) -> None:
    await session.execute(
        text(
            "TRUNCATE TABLE audit_logs, discharge_summaries, nursing_notes, "
            "admission_assessments, admissions, patients, nurses RESTART IDENTITY CASCADE"
        )
    )
    await session.commit()


async def seed(force: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        if force:
            print("[seed] --force: 既存データを削除します")
            await _clear_all(session)

        existing = await session.scalar(select(func.count()).select_from(Nurse))
        if existing:
            print(f"[seed] 既に {existing} 件の看護師が登録済みのためスキップします")
            return

        # ---------------- 看護師 ----------------
        nurse_objs: dict[str, Nurse] = {}
        pw = hash_password(settings.seed_password)
        for emp_no, name, kana, ward, role in NURSES:
            n = Nurse(
                employee_no=emp_no,
                name=name,
                name_kana=kana,
                password_hash=pw,
                ward=ward,
                role=role,
                is_active=True,
            )
            session.add(n)
            nurse_objs[emp_no] = n
        await session.flush()

        ward_nurses = {
            WARD_3F: [nurse_objs["N001"], nurse_objs["N002"]],
            WARD_4F: [nurse_objs["N003"]],
        }

        today = date.today()
        note_count = 0

        # ---------------- 患者・入院・記録 ----------------
        for sc in SCENARIOS:
            patient = Patient(
                patient_no=sc["patient_no"],
                name=sc["name"],
                name_kana=sc["name_kana"],
                birth_date=sc["birth_date"],
                sex=sc["sex"],
            )
            session.add(patient)
            await session.flush()

            # 退院済みシナリオは discharged_at を持つ
            discharged_after = sc.get("discharged_after")
            admitted_at = today - timedelta(days=sc["days"])
            admission = Admission(
                patient_id=patient.id,
                admitted_at=admitted_at,
                discharged_at=(
                    admitted_at + timedelta(days=discharged_after)
                    if discharged_after is not None
                    else None
                ),
                ward=sc["ward"],
                room=sc["room"],
                diagnosis=sc["diagnosis"],
                attending_doctor=sc["doctor"],
                status="discharged" if discharged_after is not None else "active",
            )
            session.add(admission)
            await session.flush()

            a = sc["assessment"]
            session.add(
                AdmissionAssessment(
                    admission_id=admission.id,
                    allergies=a["allergies"],
                    chronic_diseases=a["chronic_diseases"],
                    diet_restrictions=a["diet_restrictions"],
                    past_history=a["past_history"],
                    present_illness=a["present_illness"],
                    adl=a["adl"],
                )
            )

            total_days = sc["days"]
            authors = ward_nurses[sc["ward"]]
            # 入院翌日から昨日（退院済みなら退院日）まで記録を作成。
            # 当日分は看護師がこれから書く想定なので作らない。
            last_index = discharged_after if discharged_after is not None else total_days
            for i in range(1, last_index + 1):
                rec_date = admitted_at + timedelta(days=i)
                if rec_date >= today:
                    break
                vitals = _make_vitals(sc["vitals_base"], i, total_days)
                author = authors[i % len(authors)]
                session.add(
                    NursingNote(
                        admission_id=admission.id,
                        record_date=rec_date,
                        shift="日勤",
                        format="SOAP",
                        vitals=vitals,
                        input_structured={
                            "食事": rng.choice(["全量", "8割", "半量"]),
                            "排便": rng.choice(["あり", "なし"]),
                            "睡眠": rng.choice(["良好", "中途覚醒あり"]),
                        },
                        input_free=rng.choice(sc["free_input"]),
                        content_ai=None,  # 過去記録は人手で書かれた想定
                        content_final=_build_soap(sc, vitals, i, total_days),
                        status="confirmed",
                        author_id=author.id,
                        confirmed_at=datetime.combine(
                            rec_date, datetime.min.time(), tzinfo=timezone.utc
                        )
                        + timedelta(hours=8),
                    )
                )
                note_count += 1

        # ---------------- 入院歴のない患者（患者マスタのみ）----------------
        # 「入院していない患者は担当一覧に出てこない」ことと、
        # 新規入院登録の動作を確認するためのデータ。
        for mp in MASTER_ONLY_PATIENTS:
            session.add(Patient(**mp))

        await session.commit()

        print(
            f"[seed] 投入完了: 看護師 {len(NURSES)} 名 / "
            f"患者 {len(SCENARIOS) + len(MASTER_ONLY_PATIENTS)} 名"
            f"（うち入院中 {sum(1 for s in SCENARIOS if s.get('discharged_after') is None)} 名 / "
            f"退院済 {sum(1 for s in SCENARIOS if s.get('discharged_after') is not None)} 名 / "
            f"入院歴なし {len(MASTER_ONLY_PATIENTS)} 名） / "
            f"看護記録 {note_count} 件"
        )
        print(f"[seed] ログイン例: 職員番号 N001 / パスワード {settings.seed_password}")


def main() -> None:
    if not settings.seed_on_startup and "--force" not in sys.argv:
        print("[seed] SEED_ON_STARTUP=false のためスキップします")
        return
    asyncio.run(seed(force="--force" in sys.argv))


if __name__ == "__main__":
    main()
