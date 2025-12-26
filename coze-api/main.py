from fastapi import FastAPI
from pydantic import BaseModel
import pandas as pd
import numpy as np
import io
import requests

app = FastAPI(openapi_version="3.0.2")

class FileInput(BaseModel):
    file_url: str

@app.post("/analyze_patent")
async def analyze_patent(input: FileInput):
    print(f">>> [Split-Output] 开始处理: {input.file_url}")
    try:
        # 1. 下载与读取
        response = requests.get(input.file_url)
        content = response.content
        
        df = None
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except:
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
            except:
                df = pd.read_csv(io.BytesIO(content), encoding='gbk')

        if df is None:
            return {"report_part1": "❌ 读取失败", "report_part2": "", "report_part3": ""}

        # 清洗列名
        df.columns = df.columns.astype(str).str.strip()
        cols = df.columns.tolist()
        total = len(df)

        # === 1. 概况 & 2. IPC ===
        inv_auth = inv_app = utility = design = foreign = 0
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            inv_auth = int(pt.apply(lambda x: '发明' in x and '授权' in x).sum())
            inv_app = int(pt.apply(lambda x: '发明' in x and '授权' not in x).sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
        if '公开国别' in cols:
            country = df['公开国别'].astype(str)
            foreign = int(len(df[~country.str.contains("中国")]))

        ipc_rows = []
        if 'IPC主分类-部' in cols:
            group_cols = ['IPC主分类-部']
            if 'IPC主分类-部(释义)' in cols:
                group_cols.append('IPC主分类-部(释义)')
            ipc_counts = df.groupby(group_cols).size().reset_index(name='count')
            ipc_counts['percent'] = (ipc_counts['count'] / total * 100).round(2).astype(str) + '%'
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False)
            for _, row in ipc_counts.iterrows():
                sec = row['IPC主分类-部']
                desc = row['IPC主分类-部(释义)'] if 'IPC主分类-部(释义)' in cols else ""
                ipc_rows.append([sec, desc, row['count'], row['percent']])

        # 生成第一部分报告 (概况 + IPC)
        md1 = "### 1. 专利概况\n| 指标 | 数量 |\n| :--- | :--- |\n"
        md1 += f"| 申请总量 | {total} |\n| 发明授权 | {inv_auth} |\n| 发明申请 | {inv_app} |\n"
        md1 += f"| 实用新型 | {utility} |\n| 外观设计 | {design} |\n| 外国专利 | {foreign} |\n\n"
        md1 += "### 2. IPC 主分类分布\n| 序号 | IPC部 | 释义 | 数量 | 占比 |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for i, r in enumerate(ipc_rows, 1):
            md1 += f"| {i} | {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        # === 3. 高价值 (拆分产业) ===
        hv_rows = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            hv_df = df[df['score_num'] >= 9].copy()
            if '新兴产业分类' in cols and not hv_df.empty:
                # 核心拆分逻辑
                hv_df['temp_industry'] = hv_df['新兴产业分类'].astype(str).str.replace(';', ',').str.replace('，', ',')
                hv_df['temp_industry_list'] = hv_df['temp_industry'].str.split(',')
                hv_exploded = hv_df.explode('temp_industry_list')
                hv_exploded['single_industry'] = hv_exploded['temp_industry_list'].str.strip()
                hv_exploded = hv_exploded[(hv_exploded['single_industry'].notna()) & (hv_exploded['single_industry'] != '') & (hv_exploded['single_industry'] != 'nan')]
                ind_counts = hv_exploded['single_industry'].value_counts()
                hv_exploded['industry_fmt'] = hv_exploded['single_industry'].apply(lambda x: f"{x} ({ind_counts.get(x, 0)}件)")
                hv_exploded = hv_exploded.sort_values(by=['industry_fmt', '公开（公告）号'], ascending=[True, False])
                
                target_map = {'公开号': '公开（公告）号', '标题': '标题 (中文)', '发明人': '发明人'}
                for _, row in hv_exploded.iterrows():
                    vals = [row['industry_fmt']]
                    for k, v in target_map.items():
                        vals.append(str(row.get(v, "")) if pd.notna(row.get(v)) else "")
                    hv_rows.append(vals)

        # 生成第二部分报告 (仅高价值)
        md2 = "### 3. 高价值专利推荐 (>=9分)\n| 新兴产业分类 | 公开号 | 标题 | 发明人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in hv_rows:
            md2 += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        # === 4. 转让 ===
        tf_rows = []
        if '受让人' in cols:
            tf_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            t_targets = ['公开（公告）号', '标题 (中文)', '发明人', '受让人']
            for _, row in tf_df.iterrows():
                vals = []
                for t in t_targets:
                    vals.append(str(row.get(t, "")) if pd.notna(row.get(t, "")) else "")
                tf_rows.append(vals)

        # 生成第三部分报告 (转让)
        md3 = "### 4. 专利转让情况\n| 公开号 | 标题 | 发明人 | 受让人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in tf_rows:
            md3 += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        return {
            "report_part1": md1,
            "report_part2": md2,
            "report_part3": md3
        }

    except Exception as e:
        return {"report_part1": f"❌ Error: {str(e)}", "report_part2": "", "report_part3": ""}
