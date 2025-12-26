from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import numpy as np
import io
import requests

app = FastAPI(openapi_version="3.0.2")

class FileInput(BaseModel):
    file_url: str  # 扣子会把用户上传的 CSV 变成一个 URL 传过来

@app.post("/analyze_patent")
async def analyze_patent(input: FileInput):
    try:
        # 1. 从 URL 下载 CSV 文件
        response = requests.get(input.file_url)
        response.raise_for_status()
        content = response.content
        
        # 2. 读取 CSV (优先尝试 utf-8，失败尝试 gbk)
        try:
            df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(content), encoding='gbk')

        # --- 任务一：专利概况 ---
        total = len(df)
        # 容错处理：先统一转字符串再判断
        patent_types = df['专利类型'].astype(str) if '专利类型' in df.columns else pd.Series()
        
        stats = {
            "total": total,
            "invention": int(patent_types.str.contains("发明").sum()),
            "utility": int(patent_types.str.contains("实用新型").sum()),
            "design": int(patent_types.str.contains("外观设计").sum()),
            "foreign": int(len(df[~df['公开国别'].astype(str).str.contains("中国")])) if '公开国别' in df.columns else 0
        }
        stats['other'] = total - (stats['invention'] + stats['utility'] + stats['design'])

        # --- 任务二：IPC 分布 ---
        ipc_data = []
        if 'IPC主分类-部' in df.columns and 'IPC主分类-部(释义)' in df.columns:
            ipc_counts = df.groupby(['IPC主分类-部', 'IPC主分类-部(释义)']).size().reset_index(name='count')
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False).head(10) # 取前10
            ipc_data = ipc_counts.to_dict(orient='records')

        # --- 任务三：高价值专利 (>=9) ---
        high_value_data = []
        if '合享价值度' in df.columns:
            # 强制转数字，无法转换的变 NaN 然后填充 0
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            high_value_df = df[df['score_num'] >= 9].copy()
            
            if '新兴产业分类' in df.columns:
                high_value_df = high_value_df.sort_values(by='新兴产业分类')
            
            # 选取需要的列输出
            cols_needed = ['标题 (中文)', '申请人', '公开（公告）号', '新兴产业分类', '合享价值度']
            # 确保列存在，防止报错
            available_cols = [c for c in cols_needed if c in df.columns]
            high_value_data = high_value_df[available_cols].head(20).to_dict(orient='records') # 限制返回数量防止包太大

        # --- 任务四：转让情况 ---
        transfer_data = []
        if '受让人' in df.columns:
            # 筛选受让人不为空且长度大于1
            transfer_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            cols_needed_t = ['标题 (中文)', '申请人', '受让人', '当前法律状态', '公开（公告）日']
            available_cols_t = [c for c in cols_needed_t in df.columns]
            transfer_data = transfer_df[available_cols_t].head(20).to_dict(orient='records')

        return {
            "message": "success",
            "stats": stats,
            "ipc_data": ipc_data,
            "high_value_data": high_value_data,
            "high_value_count": len(high_value_data),
            "transfer_data": transfer_data
        }

    except Exception as e:
        return {"error": str(e)}
