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
    print(f">>> [Auto-Table] 开始处理: {input.file_url}")
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
            return {"markdown_report": "❌ 文件读取失败，请检查格式。"}

        # 清洗列名
        df.columns = df.columns.astype(str).str.strip()
        cols = df.columns.tolist()
        total = len(df)

        # ==================== 1. 计算逻辑 (保持不变) ====================
        
        # A. 专利概况
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

        # B. IPC
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

        # C. 高价值
        hv_rows = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            hv_df = df[df['score_num'] >= 9].copy()
            if '新兴产业分类' in cols:
                ind_counts = hv_df['新兴产业分类'].value_counts()
                hv_df['新兴产业分类_fmt'] = hv_df['新兴产业分类'].apply(lambda x: f"{x} ({ind_counts.get(x,0)}件)")
                hv_df = hv_df.sort_values(by='新兴产业分类', ascending=False)
            
            target_cols = ['新兴产业分类_fmt' if '新兴产业分类' in cols else '新兴产业分类', 
                           '公开（公告）号', '标题 (中文)', '发明人']
            
            for _, row in hv_df.iterrows():
                vals = []
                for t in target_cols:
                    val = str(row.get(t, "")) if pd.notna(row.get(t, "")) else ""
                    vals.append(val)
                hv_rows.append(vals)

        # D. 转让
        tf_rows = []
        if '受让人' in cols:
            tf_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            t_targets = ['公开（公告）号', '标题 (中文)', '发明人', '受让人']
            for _, row in tf_df.iterrows():
                vals = []
                for t in t_targets:
                    val = str(row.get(t, "")) if pd.notna(row.get(t, "")) else ""
                    vals.append(val)
                tf_rows.append(vals)

        # ==================== 2. 生成 Markdown 表格字符串 ====================
        
        md = "### 1. 专利概况\n"
        md += "| 指标 | 数量 |\n| :--- | :--- |\n"
        md += f"| 申请总量 | {total} |\n"
        md += f"| 发明授权 | {inv_auth} |\n"
        md += f"| 发明申请 | {inv_app} |\n"
        md += f"| 实用新型 | {utility} |\n"
        md += f"| 外观设计 | {design} |\n"
        md += f"| 外国专利 | {foreign} |\n\n"

        md += "### 2. IPC 主分类分布\n"
        md += "| 序号 | IPC部 | 释义 | 数量 | 占比 |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for i, r in enumerate(ipc_rows, 1):
            md += f"| {i} | {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"
        md += "\n"

        md += "### 3. 高价值专利推荐 (>=9分)\n"
        md += "| 新兴产业分类 | 公开号 | 标题 | 发明人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in hv_rows:
            md += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"
        md += "\n"

        md += "### 4. 专利转让情况\n"
        md += "| 公开号 | 标题 | 发明人 | 受让人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in tf_rows:
            md += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        print(f">>> 报告生成完毕，长度: {len(md)}")
        # 核心：只返回一个长字符串
        return {"markdown_report": md}

    except Exception as e:
        return {"markdown_report": f"❌ 处理出错: {str(e)}"}
