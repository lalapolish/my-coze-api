from fastapi import FastAPI, HTTPException
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
    print(f">>> [1/5] 开始下载: {input.file_url}")
    try:
        response = requests.get(input.file_url)
        response.raise_for_status()
        content = response.content
        
        # 读取逻辑
        df = None
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except:
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
            except:
                df = pd.read_csv(io.BytesIO(content), encoding='gbk')

        if df is None:
            return {"error": "读取失败"}

        # 清洗列名
        df.columns = df.columns.astype(str).str.strip()
        cols = df.columns.tolist()
        total = len(df)

        # 1. 统计概况
        invention = utility = design = foreign = 0
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            invention = int(pt.str.contains("发明").sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
        
        if '公开国别' in cols:
            country = df['公开国别'].astype(str)
            foreign = int(len(df[~country.str.contains("中国")]))

        stats = {
            "total": total,
            "invention": invention,
            "utility": utility,
            "design": design,
            "foreign": foreign
        }

        # 2. IPC 数据 (转为英文键名)
        ipc_data = []
        if 'IPC主分类-部' in cols:
            # 如果有释义列就用，没有就忽略
            group_cols = ['IPC主分类-部']
            if 'IPC主分类-部(释义)' in cols:
                group_cols.append('IPC主分类-部(释义)')
            
            ipc_counts = df.groupby(group_cols).size().reset_index(name='count')
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False).head(10)
            
            # 重命名为英文 (标准化)
            rename_map = {
                'IPC主分类-部': 'section',
                'IPC主分类-部(释义)': 'desc',
                'count': 'count'
            }
            ipc_counts = ipc_counts.rename(columns=rename_map)
            # 只保留需要的列
            safe_cols = [c for c in ['section', 'desc', 'count'] if c in ipc_counts.columns]
            ipc_data = ipc_counts[safe_cols].to_dict(orient='records')

        # 3. 高价值数据 (转为英文键名)
        high_value_data = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            high_value_df = df[df['score_num'] >= 9].copy()
            
            # 提取并重命名
            data_map = {
                '标题 (中文)': 'title',
                '申请人': 'applicant',
                '合享价值度': 'score'
            }
            
            records = []
            for _, row in high_value_df.head(20).iterrows():
                item = {}
                for ch_col, en_col in data_map.items():
                    if ch_col in cols:
                        item[en_col] = row[ch_col]
                if item:
                    records.append(item)
            high_value_data = records

        result = {
            "message": "success",
            "stats": stats,
            "ipc_data": ipc_data,
            "high_value_data": high_value_data
        }
        print(f">>> 返回数据示例: {result}")
        return result

    except Exception as e:
        return {"error": str(e)}
