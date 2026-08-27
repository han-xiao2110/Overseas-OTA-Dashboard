#!/usr/bin/env python3
"""
Extract ST (Sensor Tower) user data from Excel and generate st_data_副本.json
for the dashboard's '用户数据（ST）' tab.

Data source: 【中金互联网】海外OTA用户数据2607_副本.xlsx
Sheets used:
  - MAU-（月）: Monthly MAU by app × region (10 apps per region)
  - DAU-（月均）: Monthly avg DAU by app × region (10 apps per region)
  - 下载量-（月）: Monthly downloads by region × app (10 apps per region)

Structure:
  Each region has 10 apps (mostly different per region, with 6 common global apps):
  Airbnb, Agoda, Booking.com, Expedia, Skyscanner, Trip.com + 4 local competitors.
  
  Layout per region:
    MAU/下载量 sheets: [Date col] + [10 app cols] + [Date col] + [10 share cols] = 24 cols
    DAU sheet:         [Date col] + [10 app cols] = 12 cols (no market share section)
"""

import openpyxl
import json
import datetime
import os
from collections import OrderedDict

WORK = os.path.dirname(os.path.abspath(__file__))
EXCEL_PATH = os.path.join(WORK, '【中金互联网】海外OTA用户数据2607_副本.xlsx')
OUTPUT_PATH = os.path.join(WORK, 'st_data_副本.json')

# Region definitions
REGIONS = OrderedDict([
    ('中国香港', 'hk'), ('新加坡', 'sg'), ('日本', 'jp'), ('韩国', 'kr'),
    ('泰国', 'th'), ('马来西亚', 'my'), ('印度', 'in'), ('菲律宾', 'ph'),
    ('越南', 'vn'), ('东南亚', 'se_asia'), ('东亚', 'e_asia'), ('大洋洲', 'oceania'),
    ('欧洲', 'europe'), ('北美', 'north_america'), ('中东', 'middle_east'), ('全球', 'global')
])

REGION_NAMES_EN = {
    '中国香港': 'Hong Kong', '新加坡': 'Singapore', '日本': 'Japan', '韩国': 'South Korea',
    '泰国': 'Thailand', '马来西亚': 'Malaysia', '印度': 'India', '菲律宾': 'Philippines',
    '越南': 'Vietnam', '东南亚': 'Southeast Asia', '东亚': 'East Asia', '大洋洲': 'Oceania',
    '欧洲': 'Europe', '北美': 'North America', '中东': 'Middle East', '全球': 'Global'
}

CONTINENT_NAMES = ['东南亚', '东亚', '大洋洲', '欧洲', '北美', '中东']
CONTINENT_KEYS = ['se_asia', 'e_asia', 'oceania', 'europe', 'north_america', 'middle_east']

# Global common apps (appear in all regions, used for "按App" tab)
GLOBAL_APPS = ['Airbnb', 'Agoda', 'Booking.com', 'Expedia', 'Skyscanner', 'Trip.com']
GLOBAL_APP_KEYS = ['airbnb', 'agoda', 'booking_com', 'expedia', 'skyscanner', 'trip_com']

# Sheet configuration: (sheet_name, has_market_share_section)
SHEET_CONFIG = {
    'MAU-（月）': True,
    'DAU-（月均） ': False,
    '下载量-（月） ': True
}

# Column offsets per region (data section date column)
# MAU/下载量: 24 cols per region, DAU: 12 cols per region
REGION_DATE_COL_MAU = {
    '中国香港': 1, '新加坡': 25, '日本': 49, '韩国': 73, '泰国': 97,
    '马来西亚': 121, '印度': 145, '菲律宾': 169, '越南': 193,
    '东南亚': 217, '东亚': 241, '大洋洲': 265, '欧洲': 289,
    '北美': 313, '中东': 337, '全球': 361
}

REGION_DATE_COL_DAU = {
    '中国香港': 1, '新加坡': 13, '日本': 25, '韩国': 37, '泰国': 49,
    '马来西亚': 61, '印度': 73, '菲律宾': 85, '越南': 97,
    '东南亚': 109, '东亚': 121, '大洋洲': 133, '欧洲': 145,
    '北美': 157, '中东': 169, '全球': 181
}


def month_to_key(date_val):
    if isinstance(date_val, datetime.datetime):
        return f"{date_val.year % 100}M{date_val.month}"
    return None


def parse_value(val):
    if val is None or val == '' or val == '':
        return None
    try:
        fval = float(val)
        return fval if fval > 0 else None
    except (ValueError, TypeError):
        return None


def get_region_apps(ws, date_col):
    """Read 10 app names starting from date_col + 1"""
    apps = []
    for i in range(10):
        app_name = ws.cell(row=2, column=date_col + 1 + i).value
        apps.append(app_name if app_name else f"App_{i+1}")
    return apps


def load_metric_data(wb, sheet_name, region_date_cols):
    """Load metric data from a sheet, returning {region: {app: {month: value}}}"""
    ws = wb[sheet_name]
    data = {}

    for region_name, date_col in region_date_cols.items():
        apps = get_region_apps(ws, date_col)
        data[region_name] = {}

        for app_idx, app_name in enumerate(apps):
            app_col = date_col + 1 + app_idx
            monthly = {}

            for row in range(3, ws.max_row + 1):
                date_val = ws.cell(row=row, column=date_col).value
                val = ws.cell(row=row, column=app_col).value
                mk = month_to_key(date_val)
                if mk:
                    parsed = parse_value(val)
                    if parsed is not None:
                        monthly[mk] = parsed

            data[region_name][app_name] = monthly

    return data


def month_sort_key(m):
    parts = m.split('M')
    return (int(parts[0]), int(parts[1]))


def month_to_numeric(m):
    parts = m.split('M')
    return int(parts[0]) * 12 + int(parts[1])


def get_valid_months(metric_data, min_month='21M1'):
    """Get months that have data across any region/app, from min_month onwards"""
    month_has_data = set()
    min_numeric = month_to_numeric(min_month)
    for region in metric_data:
        for app in metric_data[region]:
            for m, val in metric_data[region][app].items():
                if month_to_numeric(m) >= min_numeric and val is not None and val > 0:
                    month_has_data.add(m)
    return sorted(month_has_data, key=month_sort_key)


def scale_to_millions(values):
    result = []
    for v in values:
        if v is None or v == '-':
            result.append(v)
        else:
            result.append(round(v / 1_000_000, 2))
    return result


def compute_yoy(monthly_values, months_list):
    yoy = {}
    for m in months_list:
        parts = m.split('M')
        year = int(parts[0]) + 2000
        month = int(parts[1])
        prev_year = (year - 1) % 100
        prev_year_m = f"{prev_year}M{month}"
        curr_val = monthly_values.get(m)
        prev_val = monthly_values.get(prev_year_m)
        if curr_val is not None and prev_val is not None and prev_val != 0:
            yoy[m] = round((curr_val / prev_val - 1) * 100, 1)
        else:
            yoy[m] = None
    return yoy


def compute_share(app_monthly, total_monthly, months_list):
    """Compute share percentage: app value / total value * 100"""
    share_list = []
    for m in months_list:
        app_val = app_monthly.get(m)
        total_val = total_monthly.get(m)
        if app_val is not None and total_val is not None and total_val > 0:
            share_list.append(round(app_val / total_val * 100, 1))
        else:
            share_list.append(0.0)
    return share_list


def sum_across_apps(region_data, region_name, months_list, app_names=None):
    """Sum values across all apps for a region"""
    result = {}
    for m in months_list:
        total = 0
        has_data = False
        apps_to_sum = app_names if app_names else list(region_data.get(region_name, {}).keys())
        for app in apps_to_sum:
            if app in region_data.get(region_name, {}):
                val = region_data[region_name][app].get(m)
                if val is not None and val > 0:
                    total += val
                    has_data = True
        result[m] = total if has_data else None
    return result


def build_output():
    print(f"Loading Excel: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)

    # Load all three metrics
    print("\nLoading MAU data...")
    mau_data = load_metric_data(wb, 'MAU-（月）', REGION_DATE_COL_MAU)
    print(f"  Loaded {len(mau_data)} regions")
    for region, apps in mau_data.items():
        print(f"    {region}: {len(apps)} apps -> {list(apps.keys())}")

    print("\nLoading DAU data...")
    dau_data = load_metric_data(wb, 'DAU-（月均） ', REGION_DATE_COL_DAU)
    print(f"  Loaded {len(dau_data)} regions")

    print("\nLoading Downloads data...")
    dl_data = load_metric_data(wb, '下载量-（月） ', REGION_DATE_COL_MAU)
    print(f"  Loaded {len(dl_data)} regions")

    # Determine valid months
    mau_months = set(get_valid_months(mau_data))
    dau_months = set(get_valid_months(dau_data))
    dl_months = set(get_valid_months(dl_data))

    all_valid = mau_months | dau_months | dl_months
    months_list = sorted([m for m in all_valid if month_to_numeric(m) >= month_to_numeric('21M1')], key=month_sort_key)
    print(f"\nValid months: {months_list[0]} to {months_list[-1]} ({len(months_list)} months)")

    # Build output structure
    by_country = {
        'metrics': ['MAU', 'DAU', '下载量'],
        'global': {},
        'continents': {},
        'countries': {}
    }

    metric_sources = [
        ('MAU', mau_data),
        ('DAU', dau_data),
        ('下载量', dl_data)
    ]

    # --- Build global, continent, and country data ---
    for region_name, region_key in REGIONS.items():
        for metric_name, metric_data in metric_sources:
            region_apps = list(metric_data.get(region_name, {}).keys())

            # Sum across all apps for this region
            region_total = sum_across_apps(metric_data, region_name, months_list, region_apps)

            # For share calculation of sub-regions, we need global total
            global_total = sum_across_apps(metric_data, '全球', months_list)

            # Build by_app data for this region (as array, ordered to match apps list)
            by_app = []
            for app_name in region_apps:
                app_monthly = metric_data.get(region_name, {}).get(app_name, {})

                app_abs = scale_to_millions([app_monthly.get(m) for m in months_list])
                app_yoy_map = compute_yoy(app_monthly, months_list)
                app_yoy_list = [app_yoy_map.get(m) for m in months_list]

                # Share: app's share within this region's total
                share_list = compute_share(app_monthly, region_total, months_list)

                by_app.append({
                    'name': app_name,
                    'abs': app_abs,
                    'yoy': app_yoy_list,
                    'share': share_list
                })

            # Build the metric entry
            abs_values = [region_total.get(m) for m in months_list]
            abs_scaled = scale_to_millions(abs_values)

            yoy_map = compute_yoy(region_total, months_list)
            yoy_list = [yoy_map.get(m) for m in months_list]

            # Region's share of global
            if region_name != '全球':
                share_to_global = compute_share(region_total, global_total, months_list)
            else:
                share_to_global = [100.0] * len(months_list)

            entry = {
                'name': metric_name,
                'apps': region_apps,
                'abs': abs_scaled,
                'yoy': yoy_list,
                'share': share_to_global,
                'unit': 'Mn',
                'by_app': by_app
            }

            # Place in correct location
            if region_name == '全球':
                by_country['global'][metric_name] = entry
            elif region_name in CONTINENT_NAMES:
                cont_key = CONTINENT_KEYS[CONTINENT_NAMES.index(region_name)]
                if cont_key not in by_country['continents']:
                    by_country['continents'][cont_key] = {
                        'name': REGION_NAMES_EN.get(region_name, region_name),
                        'metrics': {}
                    }
                by_country['continents'][cont_key]['metrics'][metric_name] = entry
            else:
                country_key = REGIONS[region_name]
                if country_key not in by_country['countries']:
                    by_country['countries'][country_key] = {
                        'name': region_name,
                        'metrics': {}
                    }
                by_country['countries'][country_key]['metrics'][metric_name] = entry

    # --- Build by_app section (for "按App" tab) ---
    # This uses the 6 global common apps, showing their global-level data
    by_app = {
        'apps': GLOBAL_APP_KEYS,
        'app_names': GLOBAL_APPS
    }

    for app_key, app_name in zip(GLOBAL_APP_KEYS, GLOBAL_APPS):
        by_app[app_key] = {
            'name': app_name,
            'metrics': {}
        }
        for metric_name, metric_data in metric_sources:
            # Get global data for this specific app
            app_monthly = metric_data.get('全球', {}).get(app_name, {})

            entry_abs = scale_to_millions([app_monthly.get(m) for m in months_list])
            entry_yoy_map = compute_yoy(app_monthly, months_list)
            entry_yoy_list = [entry_yoy_map.get(m) for m in months_list]

            # Share: this app's share of global total
            global_total = sum_across_apps(metric_data, '全球', months_list)
            share_list = compute_share(app_monthly, global_total, months_list)

            by_app[app_key]['metrics'][metric_name] = {
                'name': metric_name,
                'abs': entry_abs,
                'yoy': entry_yoy_list,
                'share': share_list,
                'unit': 'Mn'
            }

    output = {
        'months': months_list,
        'by_country': by_country,
        'by_app': by_app
    }

    print(f"\nWriting output to {OUTPUT_PATH}...")
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Validation
    print(f"\n{'='*60}")
    print("Validation Report")
    print(f"{'='*60}")
    print(f"  Months: {output['months'][0]} to {output['months'][-1]} ({len(output['months'])} months)")

    print(f"\n  Global region apps:")
    g_apps = output['by_country']['global']['MAU']['apps']
    print(f"    {g_apps}")

    print(f"\n  Sample regions & their apps (MAU):")
    for region_key in ['hk', 'jp', 'se_asia', 'europe', 'global']:
        for rname, rkey in REGIONS.items():
            if rkey == region_key:
                if region_key == 'global':
                    apps = output['by_country']['global']['MAU']['apps']
                elif region_key in CONTINENT_KEYS:
                    apps = output['by_country']['continents'][region_key]['metrics']['MAU']['apps']
                else:
                    apps = output['by_country']['countries'][region_key]['metrics']['MAU']['apps']
                print(f"    {rname} ({region_key}): {apps}")
                break

    g_mau = output['by_country']['global']['MAU']
    last_idx = len(months_list) - 1
    print(f"\n  Global MAU latest ({months_list[last_idx]}): abs={g_mau['abs'][last_idx]}Mn")
    print(f"  Global MAU YoY latest: {g_mau['yoy'][last_idx]}%")

    print(f"\n  Continent keys: {list(output['by_country']['continents'].keys())}")
    print(f"  Country keys: {list(output['by_country']['countries'].keys())}")
    print(f"  By-app keys: {list(output['by_app'].keys())}")

    # Check a country's data
    jp_mau = output['by_country']['countries']['jp']['metrics']['MAU']
    print(f"\n  Japan MAU latest ({months_list[last_idx]}): abs={jp_mau['abs'][last_idx]}Mn")
    print(f"  Japan MAU apps: {jp_mau['apps']}")
    print(f"  Japan MAU by_app count: {len(jp_mau['by_app'])} apps")
    print(f"  Japan MAU by_app[0]: {jp_mau['by_app'][0]['name']}")

    print(f"\nDone! Output file: {OUTPUT_PATH}")
    return 0


if __name__ == '__main__':
    exit(build_output())
