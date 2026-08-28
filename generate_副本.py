import json, os, openpyxl, datetime, hashlib, glob

# 自动定位脚本所在目录（兼容本地 macOS 和 GitHub Actions Ubuntu Runner）
WORK = os.path.dirname(os.path.abspath(__file__))

# 自动查找脚本目录下的主 Excel 文件（避开 _副本 和【中金】等辅助 xlsx）
def _find_xlsx():
    # 优先级 1：环境变量
    env_path = os.environ.get('BKNG_XLSX')
    if env_path and os.path.exists(env_path):
        return env_path
    # 优先级 2：脚本目录下名为 BKNG-EXPE-ABNB业绩*.xlsx 且不含 _副本/【中金】 的文件
    candidates = []
    for f in glob.glob(os.path.join(WORK, 'BKNG-EXPE-ABNB业绩*.xlsx')):
        base = os.path.basename(f)
        if '_副本' in base or '【中金' in base:
            continue
        candidates.append(f)
    if candidates:
        # 选最新修改的
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]
    # 优先级 3：本地 dev 绝对路径回退
    fallback = '/Users/feifei/Documents/BKNG-EXPE-ABNB业绩/BKNG-EXPE-ABNB业绩20260811.xlsx'
    if os.path.exists(fallback):
        return fallback
    raise FileNotFoundError(
        f"未在 {WORK} 找到 BKNG-EXPE-ABNB业绩*.xlsx 文件。"
        f"请把 Excel 财务数据放到脚本同目录，或设置环境变量 BKNG_XLSX。"
    )

XLSX = _find_xlsx()
print(f"[generate] 使用 Excel: {XLSX}")

# ── 1. Load quarterly data ──
with open(f'{WORK}/dashboard_data_副本.json') as f:
    RAW = json.load(f)

# Rename take_rate keys: "Booking take rate" -> "Booking"
if 'take_rate' in RAW:
    tr_rename = {}
    for k, v in RAW['take_rate'].items():
        new_k = k.replace(' take rate', '').replace(' Take Rate', '')
        tr_rename[new_k] = v
    RAW['take_rate'] = tr_rename

# ── 2. Build ANN_DATA (2018-2025 actuals) ──
ann_rev = {
    "Booking":  [14527, 15066, 6796, 10958, 17090, 21365, 23739, 26917],
    "Expedia":  [11223, 12067, 5199, 8598, 11667, 12839, 13691, 14733],
    "Airbnb":   [3652, 4805, 3378, 5992, 8399, 9917, 11102, 12241],
}
ann_ebitda = {
    "Booking":  [5729, 5855, 879, 2904, 5295, 7112, 8306, 9937],
    "Expedia":  [None, 2134, -368, 1477, 2321, 2680, 2934, 3501],
    "Airbnb":   [171, -253, -251, 1593, 2902, 3653, 4041, 4297],
}
# Gross Bookings (US$ mn) from FT sheets
ann_gb = {
    "Booking":  [92733, 96443, 35394, 76586, 121252, 150627, 165580, 186104],
    "Expedia":  [99727, 107873, 36796, 72425, 95049, 104079, 110921, 119590],
    "Airbnb":   [29441, 37963, 23897, 46877, 63220, 73258, 81784, 91273],
}

def yoy(arr):
    r = []
    for i, v in enumerate(arr):
        if i == 0 or v is None or arr[i-1] is None or arr[i-1] == 0:
            r.append(None)
        else:
            r.append((v - arr[i-1]) / arr[i-1])
    return r

def vs2019(arr):
    """Compute ratio vs 2019 (index 1)."""
    r = []
    base = arr[1]  # 2019
    for i, v in enumerate(arr):
        if v is None or base is None or base == 0:
            r.append(None)
        else:
            r.append(v / base)
    return r

def margin(ebitda_arr, rev_arr):
    r = []
    for e, rv in zip(ebitda_arr, rev_arr):
        if e is None or rv is None or rv == 0:
            r.append(None)
        else:
            r.append(e / rv)
    return r

# Share (份额) = company / sum of 3 companies
def compute_share(data_dict):
    result = {}
    for c in ["Booking", "Expedia", "Airbnb"]:
        result[c] = []
        for i in range(8):
            total = sum(data_dict[cc][i] for cc in ["Booking", "Expedia", "Airbnb"]
                       if data_dict[cc][i] is not None)
            if data_dict[c][i] is not None and total > 0:
                result[c].append(data_dict[c][i] / total)
            else:
                result[c].append(None)
    return result

# --- Load Excel workbook (needed for contribution data and room nights) ---
wb = openpyxl.load_workbook(XLSX, data_only=True)
ws_contrib = wb['业绩对比 output']

# Room Nights (mn) from 业绩对比 output sheet rows 67-69, cols 84-91
ann_rn = {}
rn_rows = {"Booking": 67, "Expedia": 68, "Airbnb": 69}
for co, row in rn_rows.items():
    vals = []
    for c in range(84, 92):
        v = ws_contrib.cell(row, c).value
        vals.append(round(v, 1) if isinstance(v, (int, float)) else None)
    ann_rn[co] = vals

# ADR = Gross Bookings / Room Nights (US$)
ann_adr = {}
for c in ["Booking", "Expedia", "Airbnb"]:
    ann_adr[c] = []
    for i in range(8):
        if ann_gb[c][i] is not None and ann_rn[c][i] is not None and ann_rn[c][i] != 0:
            ann_adr[c].append(round(ann_gb[c][i] / ann_rn[c][i], 1))
        else:
            ann_adr[c].append(None)

ann_gb_share = compute_share(ann_gb)
ann_rn_share = compute_share(ann_rn)

# Take rate = Revenue / GMV
ann_tr = {}
for c in ["Booking", "Expedia", "Airbnb"]:
    ann_tr[c] = [ann_rev[c][i] / ann_gb[c][i] if ann_gb[c][i] else None for i in range(8)]

# --- Read contribution data directly from Excel ---
# CE=col83 (labels), CF-CM=cols 84-91 (2018-2025)
def read_pct_rows(row_list):
    """Read percentage data from Excel rows, return {label: [8 values as %]}"""
    result = {}
    for r in row_list:
        label = ws_contrib.cell(r, 83).value
        vals = []
        for c in range(84, 92):
            v = ws_contrib.cell(r, c).value
            vals.append(round(v * 100, 1) if isinstance(v, (int, float)) else None)
        result[label] = vals
    return result

# BKNG by products (rows 46-48): Hotel, Air, Rental Cars & Other
bkng_prod_raw = read_pct_rows([46, 47, 48])
bkng_prod_pct = {}
bkng_label_map = {
    "Hotel Gross Bookings": "Hotel",
    "Air Gross Bookings": "Air",
    "Rental Cars & Other Gross Bookings": "Rental Cars & Other",
}
for old_k, new_k in bkng_label_map.items():
    if old_k in bkng_prod_raw:
        bkng_prod_pct[new_k] = bkng_prod_raw[old_k]

# EXPE by products (rows 55-57): Lodging, Air, Other - keep as 3 separate items
expe_prod_raw = read_pct_rows([55, 56, 57])
expe_prod_pct = {}
# Normalize labels
expe_label_map = {
    "Lodging gross bookings": "Lodging",
    "Air gross bookings": "Air",
    "Other Gross Bookings": "Other",
}
for old_k, new_k in expe_label_map.items():
    if old_k in expe_prod_raw:
        expe_prod_pct[new_k] = expe_prod_raw[old_k]

# BKNG by region (rows 225-228): US, EU, Asia, Others
bkng_region_pct = read_pct_rows([225, 226, 227, 228])

# ABNB by region pct (rows 62-65): NA, EMEA, LA, APAC
abnb_region_pct_raw = read_pct_rows([62, 63, 64, 65])
# Shorten labels for chart display
abnb_region_pct = {}
label_map = {
    "North America": "North America",
    "Europe, the Middle East, and Africa": "EMEA",
    "Latin America ": "Latin America",
    "Asia Pacific ": "Asia Pacific",
}
for old_k, new_k in label_map.items():
    if old_k in abnb_region_pct_raw:
        abnb_region_pct[new_k] = abnb_region_pct_raw[old_k]

# BKNG DI pct (rows 250-251): Domestic, International
bkng_di_pct = read_pct_rows([250, 251])

# EXPE DI pct (rows 258-259): Domestic, International
expe_di_pct = read_pct_rows([258, 259])

# ABNB DI pct (rows 254-255): Domestic, International - data only for 2021-2025
# Year labels at row 247, cols 87-91
abnb_di_years = []
for c in range(87, 92):
    v = ws_contrib.cell(247, c).value
    abnb_di_years.append(str(int(v)) if isinstance(v, (int, float)) else str(v) if v else "")

abnb_di_raw = {}
for r in [254, 255]:
    label = ws_contrib.cell(r, 83).value
    vals = []
    for c in range(87, 92):
        v = ws_contrib.cell(r, c).value
        vals.append(round(v * 100, 1) if isinstance(v, (int, float)) else None)
    abnb_di_raw[label] = vals

# Pad with None for 2018-2020 (first 3 years) to match 8-year structure
abnb_di_pct = {}
for k, v in abnb_di_raw.items():
    abnb_di_pct[k] = [None, None, None] + v

abnb_di_years_full = ["2018", "2019", "2020"] + abnb_di_years

# Compute abs from pct × total (for data completeness)
def pct_to_abs(pct_dict, total_arr):
    result = {}
    for k, pcts in pct_dict.items():
        result[k] = [round(p * t / 100, 1) if p is not None and t is not None else None
                     for p, t in zip(pcts, total_arr)]
    return result

bkng_region_abs = pct_to_abs(bkng_region_pct, ann_rn["Booking"])
abnb_region_abs = pct_to_abs(abnb_region_pct, ann_rn["Airbnb"])
bkng_di_abs = pct_to_abs(bkng_di_pct, ann_rn["Booking"])
expe_di_abs = pct_to_abs(expe_di_pct, ann_rev["Expedia"])

ann_rev_share = compute_share(ann_rev)

ANN_DATA = {
    "revenue": {c: {"abs": ann_rev[c], "yoy": yoy(ann_rev[c]), "vs2019": vs2019(ann_rev[c]), "share": ann_rev_share[c]} for c in ann_rev},
    "ebitda":  {c: {"abs": ann_ebitda[c], "yoy": yoy(ann_ebitda[c])} for c in ann_ebitda},
    "ebitda_margin": {c: margin(ann_ebitda[c], ann_rev[c]) for c in ann_ebitda},
    "gb":      {c: {"abs": ann_gb[c], "yoy": yoy(ann_gb[c]), "vs2019": vs2019(ann_gb[c]), "share": ann_gb_share[c]} for c in ann_gb},
    "rn":      {c: {"abs": ann_rn[c], "yoy": yoy(ann_rn[c]), "vs2019": vs2019(ann_rn[c]), "share": ann_rn_share[c]} for c in ann_rn},
    "adr":     {c: {"abs": ann_adr[c], "yoy": yoy(ann_adr[c]), "vs2019": vs2019(ann_adr[c])} for c in ann_adr},
    "take_rate": ann_tr,
    "by_products": {
        "bkng": bkng_prod_pct,
        "expe": expe_prod_pct,
    },
    "by_region": {
        "bkng": {"pct": bkng_region_pct, "abs": bkng_region_abs},
        "abnb": {"pct": abnb_region_pct, "abs": abnb_region_abs},
    },
    "domestic_intl": {
        "bkng": {"pct": bkng_di_pct, "abs": bkng_di_abs},
        "expe": {"pct": expe_di_pct, "abs": expe_di_abs},
        "abnb": {"pct": abnb_di_pct, "abs": pct_to_abs(abnb_di_pct, ann_rn["Airbnb"])},
    },
}

# ── 3. Extract MKT_DATA from Excel ──
# wb already loaded above

# 3a. Extract 4 new metrics from 业绩对比 output sheet (rows 136-147, cols AX-CA = 50-79)
ws_comp = wb['业绩对比 output']
companies_list = ["Booking", "Expedia", "Airbnb"]
metric_rows = {
    "gpm":            [136, 137, 138],
    "sales_marketing": [139, 140, 141],
    "ga":             [142, 143, 144],
    "tech_content":   [145, 146, 147],
}

for key, rows in metric_rows.items():
    RAW[key] = {}
    for i, row in enumerate(rows):
        vals = []
        for col in range(50, 80):  # AX(50)=1Q19 to CA(79)=2Q26
            v = ws_comp.cell(row, col).value
            vals.append(round(v * 100, 1) if isinstance(v, (int, float)) else None)
        RAW[key][companies_list[i]] = vals
    print(f"Extracted {key}: {list(RAW[key].keys())}")

# 3b. Valuation table from 估值 sheet
ws_val = wb['估值']
valuation = []
for r in range(3, 6):
    ticker = ws_val.cell(r, 1).value or ""
    comp = ws_val.cell(r, 2).value or ""
    net_cash = ws_val.cell(r, 4).value
    ev = ws_val.cell(r, 5).value
    sh_ret = ws_val.cell(r, 6).value
    ngnp24 = ws_val.cell(r, 7).value
    ngnp25 = ws_val.cell(r, 8).value
    # Clean
    net_cash = net_cash if isinstance(net_cash, (int, float)) else None
    ev = ev if isinstance(ev, (int, float)) else None
    sh_ret = sh_ret if isinstance(sh_ret, (int, float)) else None
    ngnp24 = ngnp24 if isinstance(ngnp24, (int, float)) else None
    ngnp25 = ngnp25 if isinstance(ngnp25, (int, float)) else None
    valuation.append([ticker, comp, None, net_cash, ev, sh_ret, ngnp24, ngnp25])

# 3b. OCC recovery from 全球酒店OCC恢复情况
ws_occ = wb['全球酒店OCC恢复情况']
occ_labels = []
occ_2020, occ_2021, occ_2022 = [], [], []
for r in range(2, 30):
    month_label = ws_occ.cell(r, 15).value  # col O
    if month_label is None:
        dt = ws_occ.cell(r, 9).value  # col I date
        if dt:
            month_label = dt.strftime("%b")
        else:
            continue
    occ_labels.append(str(month_label))
    v2020 = ws_occ.cell(r, 16).value  # col P
    v2021 = ws_occ.cell(r, 17).value  # col Q
    v2022 = ws_occ.cell(r, 18).value  # col R
    occ_2020.append(v2020 if isinstance(v2020, (int, float)) else None)
    occ_2021.append(v2021 if isinstance(v2021, (int, float)) else None)
    occ_2022.append(v2022 if isinstance(v2022, (int, float)) else None)

occ_data = {
    "labels": occ_labels,
    "series": [
        {"name": "2020 vs 2019", "data": occ_2020, "color": "#EA4335"},
        {"name": "2021 vs 2019", "data": occ_2021, "color": "#FBBC04"},
        {"name": "2022 vs 2019", "data": occ_2022, "color": "#4285F4"},
    ]
}

# 3c. Buyback programs from 回购计划统计
ws_bb = wb['回购计划统计']

# Columns to keep (1-indexed): skip B=2(股票代码) and H=8(截止日期)
# Keep: C=3 公司名称, D=4 宣布回购金额, E=5 已回购金额, F=6 完成情况,
#        G=7 宣布日期, I=9 详情, J=10 执行进度, K=11 未回购金额,
#        L=12 市值, M=13 单位, N=14 未回购金额占市值比
KEEP_COLS = [3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14]

# Column index positions in the output (0-indexed after filtering)
# Original c=12(市值) → output index 8; c=14(占比) → output index 10; c=11(未回购) → output index 7

# Company row groups (Excel row numbers)
COMPANY_GROUPS = [
    [3, 4, 5],       # BOOKING
    [6, 7, 8],       # EXPEDIA
    [9, 10, 11, 12], # AIRBNB
]

buyback_headers = []
for c in KEEP_COLS:
    buyback_headers.append(str(ws_bb.cell(2, c).value) if ws_bb.cell(2, c).value else "")

buyback_data = []
for group in COMPANY_GROUPS:
    # Get market cap from first row of group (only row that has it)
    first_row = group[0]
    mc_val = ws_bb.cell(first_row, 12).value
    mc = float(mc_val) if mc_val is not None else None

    for r in group:
        row_data = []
        for c in KEEP_COLS:
            v = ws_bb.cell(r, c).value
            # Check special columns FIRST before None check
            if c == 14:  # 未回购金额占市值比 — always recalculate
                unrep_val = ws_bb.cell(r, 11).value
                unrep = float(unrep_val) if unrep_val is not None else 0
                if mc and mc > 0:
                    row_data.append(f"{(unrep/mc)*100:.2f}%")
                else:
                    row_data.append("")
            elif c == 12:  # 市值 — fill on every row of the group
                row_data.append(f"{mc:.0f}" if mc == int(mc) else f"{mc:.1f}")
            elif v is None:
                row_data.append("")
            elif isinstance(v, datetime.datetime):
                row_data.append(v.strftime("%Y-%m-%d"))
            elif c == 6:  # 完成情况 - always format as percentage
                row_data.append(f"{float(v)*100:.0f}%")
            elif isinstance(v, float):
                row_data.append(f"{v:.0f}" if v == int(v) else f"{v:.1f}")
            elif isinstance(v, int):
                row_data.append(str(v))
            else:
                row_data.append(str(v))
        buyback_data.append(row_data)

# 3d. Quarterly detail from 季度明细
ws_q = wb['季度明细']
# Read all data: rows 4-22, columns B-AM (2-39)
quarterly_data = []
for r in range(4, 23):
    row_data = []
    for c in range(2, 40):
        v = ws_q.cell(r, c).value
        if v is None:
            row_data.append("")
        elif isinstance(v, float):
            if v == int(v):
                row_data.append(str(int(v)))
            else:
                row_data.append(f"{v:.2f}")
        else:
            row_data.append(str(v))
    quarterly_data.append(row_data)

# 3e. Q2 2026 highlights from FT sheets
# Hardcoded row numbers (labels are in col B, not col A)
# FT column mapping: col35=2Q25, col40=2Q26
ft_rows = {
    "Booking":  {"sheet": "FT-BKNG", "rev": 4, "ebitda": 29, "margin": 30, "gmv": 34},
    "Expedia":  {"sheet": "FT-EXPE", "rev": 4, "ebitda": 79, "margin": 84, "gmv": 88},
    "Airbnb":   {"sheet": "FT-ABNB", "rev": 4, "ebitda": 27, "margin": 28, "gmv": 32},
}

ft_data = {}
for name, cfg in ft_rows.items():
    ws = wb[cfg["sheet"]]
    rev_2q26 = ws.cell(cfg["rev"], 40).value
    rev_2q25 = ws.cell(cfg["rev"], 35).value  # col35=2Q25
    ebitda_2q26 = ws.cell(cfg["ebitda"], 40).value
    margin_2q26 = ws.cell(cfg["margin"], 40).value
    gmv_2q26 = ws.cell(cfg["gmv"], 40).value

    rev_yoy = None
    if isinstance(rev_2q26, (int, float)) and isinstance(rev_2q25, (int, float)) and rev_2q25 != 0:
        rev_yoy = round((rev_2q26 - rev_2q25) / rev_2q25 * 100, 1)

    ft_data[name] = {
        "rev": round(rev_2q26) if isinstance(rev_2q26, (int, float)) else None,
        "rev_yoy": rev_yoy,
        "ebitda": round(ebitda_2q26) if isinstance(ebitda_2q26, (int, float)) else None,
        "margin": round(margin_2q26 * 100, 1) if isinstance(margin_2q26, (int, float)) else None,
        "margin_pct": round(margin_2q26, 4) if isinstance(margin_2q26, (int, float)) else None,
        "gb": round(gmv_2q26 / 1000, 1) if isinstance(gmv_2q26, (int, float)) else None,
    }
    print(f"{name}: rev={rev_2q26}, ebitda={ebitda_2q26}, margin={margin_2q26}, gmv={gmv_2q26}")

# ── 3b. Load stock price data from cache only ──
STOCK_CACHE = f'{WORK}/stock_prices_副本.json'

def load_cached_prices():
    """Load stock prices from cache file (never re-fetch here)."""
    try:
        with open(STOCK_CACHE) as f:
            data = json.load(f)
            # Filter out non-ticker keys like 'last_updated'
            ticker_keys = {k: v for k, v in data.items() if k in ('BKNG', 'EXPE', 'ABNB', '^GSPC')}
            if ticker_keys:
                print(f"  Loaded stock cache: {list(ticker_keys.keys())}")
                return ticker_keys
            return None
    except Exception as e:
        print(f"  Stock cache load failed: {e}")
        return None

print("Loading stock prices from cache...")
stock_prices = load_cached_prices()

# Historical events with time ranges for timeline annotation
HISTORICAL_EVENTS = [
    {"start": "2020-01-01", "end": "2022-12-31", "label": "Covid", "color": "#E57373"},
    {"start": "2022-02-01", "end": "2022-06-30", "label": "俄乌战争", "color": "#FFB74D"},
    {"start": "2023-10-01", "end": "2024-03-31", "label": "以色列与哈马斯战争", "color": "#BA68C8"},
    {"start": "2025-06-01", "end": "2025-08-31", "label": "以色列与伊朗十二日战争", "color": "#64B5F6"},
    {"start": "2026-03-01", "end": "2026-06-30", "label": "美以与伊朗战争", "color": "#81C784"},
]

# Approximate quarterly earnings release dates
EARNINGS_DATES = [
    # 2024
    {"date": "2024-02-27", "company": "BKNG", "quarter": "4Q23"},
    {"date": "2024-02-27", "company": "EXPE", "quarter": "4Q23"},
    {"date": "2024-03-12", "company": "ABNB", "quarter": "4Q23"},
    {"date": "2024-04-30", "company": "BKNG", "quarter": "1Q24"},
    {"date": "2024-05-16", "company": "EXPE", "quarter": "1Q24"},
    {"date": "2024-05-07", "company": "ABNB", "quarter": "1Q24"},
    {"date": "2024-07-30", "company": "BKNG", "quarter": "2Q24"},
    {"date": "2024-08-08", "company": "EXPE", "quarter": "2Q24"},
    {"date": "2024-08-06", "company": "ABNB", "quarter": "2Q24"},
    {"date": "2024-10-29", "company": "BKNG", "quarter": "3Q24"},
    {"date": "2024-11-07", "company": "EXPE", "quarter": "3Q24"},
    {"date": "2024-11-12", "company": "ABNB", "quarter": "3Q24"},
    # 2025
    {"date": "2025-02-25", "company": "BKNG", "quarter": "4Q24"},
    {"date": "2025-02-27", "company": "EXPE", "quarter": "4Q24"},
    {"date": "2025-03-11", "company": "ABNB", "quarter": "4Q24"},
    {"date": "2025-04-29", "company": "BKNG", "quarter": "1Q25"},
    {"date": "2025-05-15", "company": "EXPE", "quarter": "1Q25"},
    {"date": "2025-05-06", "company": "ABNB", "quarter": "1Q25"},
    {"date": "2025-07-29", "company": "BKNG", "quarter": "2Q25"},
    {"date": "2025-08-07", "company": "EXPE", "quarter": "2Q25"},
    {"date": "2025-08-05", "company": "ABNB", "quarter": "2Q25"},
    {"date": "2025-10-28", "company": "BKNG", "quarter": "3Q25"},
    {"date": "2025-11-06", "company": "EXPE", "quarter": "3Q25"},
    {"date": "2025-11-11", "company": "ABNB", "quarter": "3Q25"},
    # 2026
    {"date": "2026-02-24", "company": "BKNG", "quarter": "4Q25"},
    {"date": "2026-02-26", "company": "EXPE", "quarter": "4Q25"},
    {"date": "2026-03-10", "company": "ABNB", "quarter": "4Q25"},
    {"date": "2026-04-28", "company": "BKNG", "quarter": "1Q26"},
    {"date": "2026-05-14", "company": "EXPE", "quarter": "1Q26"},
    {"date": "2026-05-05", "company": "ABNB", "quarter": "1Q26"},
    {"date": "2026-08-04", "company": "BKNG", "quarter": "2Q26"},
    {"date": "2026-08-05", "company": "EXPE", "quarter": "2Q26"},
    {"date": "2026-08-06", "company": "ABNB", "quarter": "2Q26"},
]

# Extract earnings guidance from Compare sheet row 68
ws_compare = wb['Compare']
GUIDANCE_COLS = {
    "BKNG": {6: "1Q24", 7: "2Q24", 8: "3Q24", 9: "4Q24", 10: "1Q25", 11: "2Q25", 12: "3Q25", 13: "4Q25", 14: "1Q26", 15: "2Q26"},
    "EXPE": {19: "1Q24", 20: "2Q24", 21: "3Q24", 22: "4Q24", 23: "1Q25", 24: "2Q25", 25: "3Q25", 26: "4Q25", 27: "1Q26", 28: "2Q26"},
    "ABNB": {32: "1Q24", 33: "2Q24", 34: "3Q24", 35: "4Q24", 36: "1Q25", 37: "2Q25", 38: "3Q25", 39: "4Q25", 40: "1Q26", 41: "2Q26"},
}

def classify_guidance(text):
    """Classify guidance as up/down/neutral based on stock price direction, not fundamentals"""
    if not text:
        return "neutral", ""
    import re
    # Extract percentage with optional sign
    pct_match = re.search(r'([+-]?)\d+\.?\d*%', text)
    pct = pct_match.group(0) if pct_match else ""
    # If percentage has explicit sign, use it directly
    if pct.startswith('-'):
        return "down", pct
    if pct.startswith('+'):
        return "up", pct
    # No sign: look for stock price direction keywords (more reliable than "超预期")
    if any(kw in text for kw in ['下跌', '暴跌', '略跌', '暴跌', '下跌', '大跌']):
        # Add negative sign to pct if present
        if pct and not pct.startswith('-'):
            pct = '-' + pct
        return "down", pct
    if any(kw in text for kw in ['上涨', '暴涨']):
        # Add positive sign to pct if present
        if pct and not pct.startswith('+'):
            pct = '+' + pct
        return "up", pct
    # Fallback to fundamental keywords
    if any(kw in text for kw in ['超预期', '不错']):
        return "up", pct
    if any(kw in text for kw in ['不达', '低于', 'miss', '下调']):
        return "down", pct
    return "neutral", pct

earnings_guidance = []
for company, cols in GUIDANCE_COLS.items():
    for col, quarter in cols.items():
        text = ws_compare.cell(68, col).value
        if text and isinstance(text, str) and len(text) > 1:
            gtype, pct = classify_guidance(text)
            earnings_guidance.append({
                "company": company,
                "quarter": quarter,
                "text": text,
                "type": gtype,
                "pct": pct
            })

# 仅补充 Excel 中没有文本的季度（1Q24、2Q26），不覆盖已有文本
# Excel 已有文本：BKNG(2Q24~1Q26)、EXPE(2Q24~1Q26)、ABNB(2Q24~1Q26)
# Excel 无文本：1Q24(三家)、2Q26(三家，仅有数字)
GUIDANCE_OVERRIDES = {
    # 1Q24 — Excel row 68 为 None，需要新建
    # Source: BBG(Excel) BKNG rev+3.9%/NI+44.9%/EBITDA+25.3%; EXPE rev+3.0%/NI n.m./EBITDA+43.4%; ABNB rev+4.0%/NI+89.8%/EBITDA+29.9%
    # Source: 盘后涨跌幅: BKNG +9%(investing.com), EXPE -15%(gurufocus.com), ABNB -8%(Wolf of Harcourt Street)
    ("BKNG", "1Q24"): ("1Q业绩超预期，营收$44亿(+17%)，EPS($20.39,+76%)，盘后+9%", "up", "+9%"),
    ("EXPE", "1Q24"): ("1Q营收$29亿(+8%)超预期，EPS($0.21)转盈，但下调全年指引，盘后-15%", "down", "-15%"),
    ("ABNB", "1Q24"): ("1Q业绩超预期，营收$21亿(+18%)，EPS($0.41,+127%)，盘后-8%", "down", "-8%"),
    # 2Q26 — Excel row 68 为数字(0.05/0.02/0.08)，无文本
    # Source: BBG(Excel) BKNG rev+2.3%/NI+3.3%; EXPE rev+3.5%/NI+11.2%; ABNB rev+0.8%/NI+7.0%
    # Source: 盘后涨跌幅: BKNG +5.6%(Zacks), EXPE +9%(Zacks), ABNB +10%(Zacks/tikr)
    ("BKNG", "2Q26"): ("2Q业绩超预期，营收$73.5亿(+8%)，EPS($2.54,+15%)，盘后+5.6%", "up", "+5.6%"),
    ("EXPE", "2Q26"): ("2Q业绩超预期，营收$43.2亿(+14%)，EPS($5.76,+36%)，盘后+9%", "up", "+9%"),
    ("ABNB", "2Q26"): ("2Q业绩超预期，营收$36.1亿(+16.5%)，EPS($1.37,+33%)，盘后+10%", "up", "+10%"),
}
for i, g in enumerate(earnings_guidance):
    key = (g["company"], g["quarter"])
    if key in GUIDANCE_OVERRIDES:
        text, gtype, pct = GUIDANCE_OVERRIDES[key]
        earnings_guidance[i] = {"company": key[0], "quarter": key[1], "text": text, "type": gtype, "pct": pct}

# 补充 Excel 中未存储为文本的条目（如 1Q24、2Q26）
existing_keys = {(g["company"], g["quarter"]) for g in earnings_guidance}
for key, (text, gtype, pct) in GUIDANCE_OVERRIDES.items():
    if key not in existing_keys:
        earnings_guidance.append({"company": key[0], "quarter": key[1], "text": text, "type": gtype, "pct": pct})

print(f"Earnings guidance entries: {len(earnings_guidance)}")

print(f"Stock prices: {'OK' if stock_prices else 'FAILED'}")
print(f"Historical events: {len(HISTORICAL_EVENTS)}")
print(f"Earnings dates: {len(EARNINGS_DATES)}")

# ── 3f. Load news data ──
NEWS_CACHE = f'{WORK}/news_data_副本.json'
news_data = None
try:
    if os.path.exists(NEWS_CACHE):
        with open(NEWS_CACHE) as f:
            news_data = json.load(f)
        intl_sec = len(news_data.get('international', {}).get('sec_filings', []))
        intl_ind = len(news_data.get('international', {}).get('industry_news', []))
        dom_total = sum(len(v) for v in news_data.get('domestic', {}).values() if isinstance(v, list))
        print(f"News data loaded: {intl_sec} SEC filings, {intl_ind} intl news, {dom_total} domestic items")
    else:
        print(f"News cache not found: {NEWS_CACHE}")
except Exception as e:
    print(f"News data load failed: {e}")

MKT_DATA = {
    "valuation": valuation,
    "occ": occ_data,
    "buyback_headers": buyback_headers,
    "buyback_data": buyback_data,
    "quarterly_data": quarterly_data,
    "q2_highlights": ft_data,
    "stock_prices": stock_prices,
    "events": HISTORICAL_EVENTS,
    "earnings_dates": EARNINGS_DATES,
    "earnings_guidance": earnings_guidance,
    "news_data": news_data,
}

# ── 4. Generate final HTML ──
with open(f'{WORK}/template_副本.html') as f:
    html = f.read()

# Load ST data first
ST_DATA_PATH = f'{WORK}/st_data_副本.json'
try:
    with open(ST_DATA_PATH) as f:
        st_data = json.load(f)
    print(f"ST data loaded: {len(st_data.get('by_country',{}).get('continents',{}))} continents, {len(st_data.get('by_country',{}).get('countries',{}))} countries, {len(st_data.get('by_app',{}).get('apps',[]))} apps")
except Exception as e:
    print(f"ST data load failed: {e}")
    st_data = {}

# ── 方案: 外部静态文件 + 同源预加载 ──
# 计算内容哈希用于缓存版本号（内容变了自动失效缓存）
echarts_path = f'{WORK}/echarts.min.js'
st_js_path = f'{WORK}/st_data.js'

# 先构建 st_data.js 内容（需要先于哈希计算）
st_json = json.dumps(st_data, ensure_ascii=False, separators=(',', ':'))
st_js_content = 'window.ST_DATA=' + st_json + ';'

# 写临时 st_data.js 用于哈希
with open(st_js_path, 'w') as f:
    f.write(st_js_content)

# 计算哈希
echarts_hash = hashlib.md5(open(echarts_path, 'rb').read()).hexdigest()[:8]
st_hash = hashlib.md5(open(st_js_path, 'rb').read()).hexdigest()[:8]

# 替换模板占位符
html = html.replace('<!--__ECHARTS_PRELOAD__-->',
    f'<link rel="preload" as="script" href="echarts.min.js?v={echarts_hash}">'
    f'<link rel="preload" as="script" href="st_data.js?v={st_hash}">')

html = html.replace('<!--__ECHARTS__-->',
    f'<script src="echarts.min.js?v={echarts_hash}"></script>')

html = html.replace('<!--__ST_DATA_INLINE__-->',
    f'<script src="st_data.js?v={st_hash}"></script>')

print(f"echarts.min.js: external, v={echarts_hash}, preloaded")
print(f"st_data.js: external, v={st_hash}, preloaded, {len(st_json):,} chars")

# Replace placeholders (compact separators to shrink the HTML)
raw_json = json.dumps(RAW, ensure_ascii=False, separators=(',', ':'))
ann_json = json.dumps(ANN_DATA, ensure_ascii=False, separators=(',', ':'))
mkt_json = json.dumps(MKT_DATA, ensure_ascii=False, separators=(',', ':'))

html = html.replace('/*__DATA_PLACEHOLDER__*/{}', raw_json)
html = html.replace('/*__ANN_PLACEHOLDER__*/{}', ann_json)
html = html.replace('/*__MKT_PLACEHOLDER__*/{}', mkt_json)

out_path = f'{WORK}/dashboard.html'
with open(out_path, 'w') as f:
    f.write(html)

# ── 部署: 确保所有文件一起部署，避免版本不一致 ──
import shutil
deploy_dir = f'{WORK}/deploy'
# GitHub Actions 全新 checkout 时 deploy/ 不存在（被 .gitignore 忽略），自动创建
os.makedirs(deploy_dir, exist_ok=True)

# 清空 deploy 目录中的旧文件
for fname in ['index.html', 'dashboard.html', 'echarts.min.js', 'st_data.js']:
    fpath = f'{deploy_dir}/{fname}'
    if os.path.exists(fpath):
        os.remove(fpath)

# 复制主 HTML
shutil.copy2(out_path, f'{deploy_dir}/index.html')
shutil.copy2(out_path, f'{deploy_dir}/dashboard.html')

# 复制 echarts.min.js
shutil.copy2(f'{WORK}/echarts.min.js', f'{deploy_dir}/echarts.min.js')

# 生成并复制 st_data.js
st_js_out = f'{WORK}/st_data.js'
with open(st_js_out, 'w') as f:
    f.write(st_js_content)
shutil.copy2(st_js_out, f'{deploy_dir}/st_data.js')

print(f"Deploy assets (all {os.listdir(deploy_dir)} files copied together)")

print(f"\nGenerated: {out_path}")
print(f"HTML size: {len(html):,} bytes ({len(html)/1024:.0f} KB)")
print(f"echarts.min.js: {os.path.getsize(f'{WORK}/echarts.min.js'):,} bytes")
print(f"st_data.js: {len(st_json):,} bytes")
print(f"RAW keys: {list(RAW.keys())}")
print(f"ANN_DATA keys: {list(ANN_DATA.keys())}")
print(f"MKT_DATA keys: {list(MKT_DATA.keys())}")
print(f"Valuation rows: {len(valuation)}")
print(f"OCC labels: {len(occ_labels)}")
print(f"Buyback headers: {len(buyback_headers)}")
print(f"Buyback data rows: {len(buyback_data)}")
print(f"Quarterly data rows: {len(quarterly_data)}")
print(f"Q2 highlights: {list(ft_data.keys())}")
