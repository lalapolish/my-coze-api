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
    print(f">>> [Simple-HighValue] 开始处理: {input.file_url}")
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

        # ==================== 1. 概况 & 2. IPC (保持不变) ====================
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

        # ==================== 4. 高价值 (修改版：简化清单) ====================
        hv_rows = []
        if '合享价值度' in cols and '专利类型' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            
            # 1. 筛选逻辑：分数>=9 且 包含"授权"
            hv_df = df[
                (df['score_num'] >= 9) & 
                (df['专利类型'].astype(str).str.contains("授权"))
            ].copy()
            
            # 2. 如果有数据，直接提取字段，不进行拆分统计
            if not hv_df.empty:
                # 尝试按价值度降序排列（可选，这样高分的在前）
                hv_df = hv_df.sort_values(by='score_num', ascending=False)

                # 遍历生成行数据 (序号从1开始)
                for i, (_, row) in enumerate(hv_df.iterrows(), 1):
                    # 获取字段，兼容不同列名写法
                    title = str(row.get('标题 (中文)', row.get('标题', '')))
                    pub_no = str(row.get('公开（公告）号', row.get('公开号', '')))
                    industry = str(row.get('新兴产业分类', '-'))
                    inventor = str(row.get('发明人', ''))
                    
                    # 简单清洗 NaN
                    if industry == 'nan': industry = '-'
                    if title == 'nan': title = '-'

                    # 按照：序号、标题、公开号、新兴产业分类、发明人 顺序添加
                    hv_rows.append([i, title, pub_no, industry, inventor])

        # 生成第二部分报告
        md2 = "### 3. 主要发明人 (Top 20)\n| 发明人 | 发明频率 |\n| :--- | :--- |\n"
        if not inv_rows:
            md2 += "| 暂无数据 | 0 |\n"
        else:
            for r in inv_rows:
                md2 += f"| {r[0]} | {r[1]} |\n"
        
        # 修改表头以匹配新逻辑
        md2 += "\n### 4. 高价值授权专利推荐 (>=9分)\n| 序号 | 标题 | 公开号 | 新兴产业分类 | 发明人 |\n| :--- | :--- | :--- | :--- | :--- |\n"
        if not hv_rows:
            md2 += "| - | 暂无符合条件的授权专利 | - | - | - |\n"
        else:
            for r in hv_rows:
                # r[0]=序号, r[1]=标题, r[2]=公开号, r[3]=产业, r[4]=发明人
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

        return {
            "report_part1": md1,
            "report_part2": md2,
            "report_part3": md3
        }

    except Exception as e:
        return {"report_part1": f"❌ Error: {str(e)}", "report_part2": "", "report_part3": ""}
