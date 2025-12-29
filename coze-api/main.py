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
    print(f">>> [Horizontal-Overview] 开始处理: {input.file_url}")
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

        # ==================== 1. 概况 (修改：拆分国外 + 横向表格) ====================
        inv_auth = inv_app = utility = design = 0
        foreign_app = foreign_auth = 0 # 初始化国外数据

        # 1.1 统计国内各类 (保持原逻辑，统计全量)
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            inv_auth = int(pt.apply(lambda x: '发明' in x and '授权' in x).sum())
            inv_app = int(pt.apply(lambda x: '发明' in x and '授权' not in x).sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
        
        # 1.2 统计国外 (新增逻辑：拆分申请与授权)
        if '公开国别' in cols and '专利类型' in cols:
            # 筛选出 非中国 的数据
            foreign_df = df[~df['公开国别'].astype(str).str.contains("中国")]
            if not foreign_df.empty:
                f_pt = foreign_df['专利类型'].astype(str)
                # 统计国外授权
                foreign_auth = int(f_pt.str.contains("授权").sum())
                # 剩下的就是国外申请
                foreign_app = int(len(foreign_df)) - foreign_auth

        # 1.3 生成横向表格 Markdown
        # 表头
        md1 = "### 1. 专利概况\n"
        md1 += "| 申请总量 | 发明授权 | 发明申请 | 实用新型 | 外观设计 | 国外申请 | 国外授权 |\n"
        md1 += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        # 数据行
        md1 += f"| {total} | {inv_auth} | {inv_app} | {utility} | {design} | {foreign_app} | {foreign_auth} |\n\n"

        # ==================== 2. IPC (保持不变) ====================
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

        md1 += "### 2. IPC 主分类分布\n| 序号 | IPC部 | 释义 | 数量 | 占比 |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for i, r in enumerate(ipc_rows, 1):
            md1 += f"| {i} | {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        # ==================== 3. 主要发明人 (保持不变) ====================
        inv_rows = []
        if '发明人' in cols:
            temp_inv = df['发明人'].astype(str).str.replace('，', ';').str.replace(',', ';')
            inv_exploded = temp_inv.str.split(';').explode().str.strip()
            inv_exploded = inv_exploded[(inv_exploded.notna()) & (inv_exploded != '') & (inv_exploded != 'nan')]
            inv_counts = inv_exploded.value_counts().reset_index()
            inv_counts.columns = ['name', 'count'] 
            for i, row in inv_counts.head(20).iterrows():
                inv_rows.append([row['name'], row['count']])

        md2 = "### 3. 主要发明人 (Top 20)\n| 发明人 | 发明频率 |\n| :--- | :--- |\n"
        if not inv_rows: md2 += "| 暂无数据 | 0 |\n"
        else:
            for r in inv_rows: md2 += f"| {r[0]} | {r[1]} |\n"

        # ==================== 4. 高价值 (保持简版清单逻辑) ====================
        hv_rows = []
        if '合享价值度' in cols and '专利类型' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            # 筛选 >=9 分 AND 包含 "授权"
            hv_df = df[(df['score_num'] >= 9) & (df['专利类型'].astype(str).str.contains("授权"))].copy()
            
            if not hv_df.empty:
                hv_df = hv_df.sort_values(by='score_num', ascending=False)
                for i, (_, row) in enumerate(hv_df.iterrows(), 1):
                    title = str(row.get('标题 (中文)', row.get('标题', '')))
                    pub_no = str(row.get('公开（公告）号', row.get('公开号', '')))
                    industry = str(row.get('新兴产业分类', '-'))
                    inventor = str(row.get('发明人', ''))
                    
                    if industry == 'nan': industry = '-'
                    if title == 'nan': title = '-'
                    hv_rows.append([i, title, pub_no, industry, inventor])

        md2 += "\n### 4. 高价值授权专利推荐 (>=9分)\n| 序号 | 标题 | 公开号 | 新兴产业分类 | 发明人 |\n| :--- | :--- | :--- | :--- | :--- |\n"
        if not hv_rows: md2 += "| - | 暂无符合条件的授权专利 | - | - | - |\n"
        else:
            for r in hv_rows:
                md2 += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |\n"

        # ==================== 5. 转让 (保持不变) ====================
        tf_rows = []
        if '受让人' in cols:
            tf_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            t_targets = ['公开（公告）号', '标题 (中文)', '发明人', '受让人']
            for _, row in tf_df.iterrows():
                vals = []
                for t in t_targets:
                    vals.append(str(row.get(t, "")) if pd.notna(row.get(t, "")) else "")
                tf_rows.append(vals)

        md3 = "### 5. 专利转让情况\n| 公开号 | 标题 | 发明人 | 受让人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in tf_rows:
            md3 += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        return {"report_part1": md1, "report_part2": md2, "report_part3": md3}

    except Exception as e:
        return {"report_part1": f"❌ Error: {str(e)}", "report_part2": "", "report_part3": ""}
